"""
Módulo Instalador de Certificados Digitais.

Lógica de negócio para:
- Cifrar/decifrar PFX em repouso (AES-256-GCM com chave do servidor)
- Armazenar PFX cifrado no Supabase (cert_pfx_store)
- Gerar tokens de instalação de uso único com TTL
- Montar bundle criptografado ponta a ponta (ECDH + AES-256-GCM)
- Trilha de auditoria (install_log)
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric.ec import (
    ECDH,
    EllipticCurvePublicKey,
)
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes, serialization

from app import config

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# Helpers de criptografia
# ──────────────────────────────────────────────────────────────────────────

# Versão atual da chave de cifragem em repouso. Gravada em cada linha de
# cert_pfx_store para permitir rotação incremental: ao trocar a chave, sobe-se
# esta constante e os registros antigos continuam decifráveis pela chave da
# versão deles, em vez de exigir recifrar tudo numa janela só.
CURRENT_KEY_VERSION = 1


def _get_server_key(version: int = CURRENT_KEY_VERSION) -> bytes:
    """
    Chave AES-256 do servidor (32 bytes) a partir do hex no .env.

    `version` sustenta a rotação: a chave em vigor vem de CERT_ENCRYPTION_KEY e
    as anteriores de CERT_ENCRYPTION_KEY_V<n>, que o config carrega do ambiente.
    Até 15/08 esse segundo caminho não funcionava — o config não expunha as
    variáveis, e qualquer versão anterior estourava como "chave não configurada".
    """
    if version == CURRENT_KEY_VERSION:
        raw = config.CERT_ENCRYPTION_KEY
    else:
        raw = getattr(config, f"CERT_ENCRYPTION_KEY_V{version}", "") or ""

    if not raw or len(raw) != 64:
        raise RuntimeError(
            f"CERT_ENCRYPTION_KEY (versão {version}) não configurada ou inválida. "
            "Gere com: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    return bytes.fromhex(raw)


def _get_password_key() -> bytes:
    """
    Chave AES-256 dedicada à senha do PFX.

    Separada de propósito de `_get_server_key`: guardar senha e certificado sob
    a mesma chave foi o defeito que tirou a senha do banco em 03/08. Recusa-se a
    operar se as duas forem iguais — seria o mesmo defeito com outro nome.
    """
    raw = config.CERT_PASSWORD_ENCRYPTION_KEY
    if not raw or len(raw) != 64:
        raise RuntimeError(
            "CERT_PASSWORD_ENCRYPTION_KEY não configurada ou inválida. "
            "Gere com: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    if raw == config.CERT_ENCRYPTION_KEY:
        raise RuntimeError(
            "CERT_PASSWORD_ENCRYPTION_KEY não pode ser igual a CERT_ENCRYPTION_KEY: "
            "senha e PFX sob a mesma chave anulam a separação que justifica guardar a senha."
        )
    return bytes.fromhex(raw)


def encrypt_password_at_rest(password: str) -> Tuple[str, str, str]:
    """Cifra a senha do PFX com a chave dedicada. Retorna (ct_b64, iv_b64, tag_b64)."""
    key = _get_password_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, password.encode("utf-8"), None)
    return (
        base64.b64encode(ct[:-16]).decode(),
        base64.b64encode(nonce).decode(),
        base64.b64encode(ct[-16:]).decode(),
    )


def decrypt_password_at_rest(ct_b64: str, iv_b64: str, tag_b64: str) -> str:
    """Inverso de `encrypt_password_at_rest`."""
    key = _get_password_key()
    aesgcm = AESGCM(key)
    nonce = base64.b64decode(iv_b64)
    ct = base64.b64decode(ct_b64)
    tag = base64.b64decode(tag_b64)
    return aesgcm.decrypt(nonce, ct + tag, None).decode("utf-8")


def encrypt_pfx_at_rest(pfx_bytes: bytes) -> Tuple[str, str, str]:
    """
    Cifra um PFX com AES-256-GCM usando a chave do servidor.
    Retorna (ciphertext_b64, iv_b64, auth_tag_b64).
    """
    key = _get_server_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 96 bits para AES-GCM
    # AESGCM.encrypt appends the 16-byte tag to the ciphertext
    ct_with_tag = aesgcm.encrypt(nonce, pfx_bytes, None)
    # Split: last 16 bytes are the tag
    ciphertext = ct_with_tag[:-16]
    auth_tag = ct_with_tag[-16:]
    return (
        base64.b64encode(ciphertext).decode(),
        base64.b64encode(nonce).decode(),
        base64.b64encode(auth_tag).decode(),
    )


def decrypt_pfx_at_rest(
    ciphertext_b64: str,
    iv_b64: str,
    auth_tag_b64: str,
    key_version: int = CURRENT_KEY_VERSION,
) -> bytes:
    """Decifra um PFX armazenado no banco, com a chave da versão em que foi gravado."""
    key = _get_server_key(key_version)
    aesgcm = AESGCM(key)
    nonce = base64.b64decode(iv_b64)
    ciphertext = base64.b64decode(ciphertext_b64)
    auth_tag = base64.b64decode(auth_tag_b64)
    # AESGCM.decrypt expects ciphertext || tag
    return aesgcm.decrypt(nonce, ciphertext + auth_tag, None)


def encrypt_bundle_for_client(
    pfx_bytes: bytes,
    client_public_key_spki_b64: str,
) -> Dict[str, str]:
    """
    Cifra um PFX para um cliente usando ECDH efêmero + AES-256-GCM.
    
    O cliente enviou sua chave pública ECDH (SPKI, base64).
    O servidor:
    1. Gera par ECDH efêmero
    2. Deriva chave compartilhada via ECDH + HKDF
    3. Cifra o PFX com AES-256-GCM usando a chave derivada
    4. Retorna: server_public_key + iv + auth_tag + ciphertext
    """
    from cryptography.hazmat.primitives.asymmetric.ec import (
        generate_private_key,
        SECP256R1,
    )

    # Decodificar chave pública do cliente
    client_pub_bytes = base64.b64decode(client_public_key_spki_b64)
    client_pub_key = serialization.load_der_public_key(client_pub_bytes)
    if not isinstance(client_pub_key, EllipticCurvePublicKey):
        raise ValueError("Chave pública do cliente não é ECDH/EC válida")

    # Gerar par efêmero do servidor
    server_private = generate_private_key(SECP256R1())
    server_public = server_private.public_key()

    # Derivar chave compartilhada
    shared_key = server_private.exchange(ECDH(), client_pub_key)
    derived_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"cert-installer-v1",
    ).derive(shared_key)

    # Cifrar PFX
    aesgcm = AESGCM(derived_key)
    nonce = os.urandom(12)
    ct_with_tag = aesgcm.encrypt(nonce, pfx_bytes, None)
    ciphertext = ct_with_tag[:-16]
    auth_tag = ct_with_tag[-16:]

    # Exportar chave pública do servidor para o cliente derivar a mesma chave
    server_pub_bytes = server_public.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    return {
        "serverPublicKey": base64.b64encode(server_pub_bytes).decode(),
        "iv": base64.b64encode(nonce).decode(),
        "authTag": base64.b64encode(auth_tag).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }


# ──────────────────────────────────────────────────────────────────────────
# Supabase helpers (reutiliza singleton de settings_state)
# ──────────────────────────────────────────────────────────────────────────

def _supabase():
    from app.settings_state import _supabase as _sb
    return _sb()


# ──────────────────────────────────────────────────────────────────────────
# CRUD — cert_pfx_store
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class StoredPfx:
    id: str
    fingerprint: str
    machine_id: str
    nome_titular: Optional[str]
    documento: Optional[str]
    documento_tipo: Optional[str]
    subject: Optional[str]
    not_before: Optional[str]
    not_after: Optional[str]
    friendly_name: Optional[str]
    uploaded_at: str


def upsert_pfx(
    fingerprint: str,
    pfx_bytes: bytes,
    machine_id: str,
    password: Optional[str] = None,
    nome_titular: Optional[str] = None,
    documento: Optional[str] = None,
    documento_tipo: Optional[str] = None,
    subject: Optional[str] = None,
    not_before: Optional[str] = None,
    not_after: Optional[str] = None,
    friendly_name: Optional[str] = None,
) -> str:
    """
    Cifra e armazena (ou atualiza) um PFX no banco.
    Retorna o ID do registro.
    """
    client = _supabase()
    if not client:
        raise RuntimeError("Supabase não configurado")

    encrypted_pfx, pfx_iv, pfx_auth_tag = encrypt_pfx_at_rest(pfx_bytes)

    # A senha volta ao banco — sob chave PRÓPRIA (ver `_get_password_key`).
    #
    # Ela saiu em 03/08 porque estava cifrada com a mesma chave do PFX (um
    # vazamento entregava os dois) e porque o agente podia lê-la do nome do
    # arquivo na pasta de origem. Esse segundo argumento vale para o agente, não
    # para o instalador avulso: a máquina do usuário final não tem a pasta, logo
    # não tem de onde tirar a senha. Sem isto, o certutil recusa todo PFX.
    pwd_ct = pwd_iv = pwd_tag = None
    if password:
        pwd_ct, pwd_iv, pwd_tag = encrypt_password_at_rest(password)

    now = datetime.now(timezone.utc).isoformat()
    row = {
        "fingerprint": fingerprint,
        "machine_id": machine_id,
        "nome_titular": nome_titular,
        "documento": documento,
        "documento_tipo": documento_tipo,
        "subject": subject,
        "not_before": not_before,
        "not_after": not_after,
        "friendly_name": friendly_name,
        "encrypted_pfx": encrypted_pfx,
        "pfx_iv": pfx_iv,
        "pfx_auth_tag": pfx_auth_tag,
        # A coluna antiga continua sem uso: guardava a senha sob a chave do PFX.
        "pfx_password": None,
        "pfx_password_enc": pwd_ct,
        "pfx_password_iv": pwd_iv,
        "pfx_password_tag": pwd_tag,
        "key_version": CURRENT_KEY_VERSION,
        "updated_at": now,
    }

    try:
        r = (
            client.table("cert_pfx_store")
            .upsert(row, on_conflict="machine_id,fingerprint")
            .execute()
        )
        data = r.data
        if data and len(data) > 0:
            return str(data[0].get("id", ""))
        return ""
    except Exception:
        logger.exception("Falha ao gravar PFX no cert_pfx_store")
        raise


def list_available_pfx(machine_id: Optional[str] = None) -> List[StoredPfx]:
    """Lista certificados disponíveis para instalação (sem dados cifrados)."""
    client = _supabase()
    if not client:
        return []

    fields = (
        "id, fingerprint, machine_id, nome_titular, documento, documento_tipo, "
        "subject, not_before, not_after, friendly_name, uploaded_at"
    )
    try:
        q = client.table("cert_pfx_store").select(fields)
        if machine_id:
            q = q.eq("machine_id", machine_id)
        q = q.order("uploaded_at", desc=True)
        r = q.execute()
        return [
            StoredPfx(
                id=str(row["id"]),
                fingerprint=str(row.get("fingerprint", "")),
                machine_id=str(row.get("machine_id", "")),
                nome_titular=row.get("nome_titular"),
                documento=row.get("documento"),
                documento_tipo=row.get("documento_tipo"),
                subject=row.get("subject"),
                not_before=row.get("not_before"),
                not_after=row.get("not_after"),
                friendly_name=row.get("friendly_name"),
                uploaded_at=str(row.get("uploaded_at", "")),
            )
            for row in (r.data or [])
        ]
    except Exception:
        logger.exception("Falha ao listar cert_pfx_store")
        return []


def get_pfx_by_ids(cert_ids: List[str]) -> List[Dict[str, Any]]:
    """Busca PFX cifrados por lista de IDs (para montagem do bundle)."""
    client = _supabase()
    if not client:
        return []
    try:
        r = (
            client.table("cert_pfx_store")
            .select("*")
            .in_("id", cert_ids)
            .execute()
        )
        return list(r.data or [])
    except Exception:
        logger.exception("Falha ao buscar PFX por IDs")
        return []


# ──────────────────────────────────────────────────────────────────────────
# Custódia do cofre — quais certificados podem ter o PFX armazenado
#
# Desde 15/08/2026 o modelo é OPT-OUT: todo certificado válido do inventário
# entra, menos os que o admin bloqueou. Antes era opt-in, e o resultado eram
# 33 de 560 guardados.
#
# A inversão traz um perigo que não existia. No opt-in, "não consegui ler a
# lista" e "a lista está vazia" levavam ao MESMO resultado seguro: não enviar
# nada. No opt-out são opostos — lista de bloqueios vazia significa "mande
# tudo". Traduzir o código antigo literalmente transformaria falha fechada em
# falha aberta, numa mudança de três linhas e sem sintoma nenhum: tudo
# continuaria funcionando, e chaves privadas demais subiriam.
#
# Por isso as funções abaixo **levantam** em vez de devolver vazio. Quem chama
# é obrigado a decidir o que fazer com o erro, e o `except` distraído deixa de
# ser o caminho de menor resistência.
# ──────────────────────────────────────────────────────────────────────────

class CustodiaIndisponivel(RuntimeError):
    """
    Não deu para determinar com segurança o que pode ir ao cofre.

    Existe para que "não sei" seja um estado próprio, distinto de "nada está
    bloqueado". Quem trata isto tem de fechar: não enviar, não aceitar.
    """


def listar_bloqueios(machine_id: str) -> Set[str]:
    """
    Fingerprints com a custódia desativada pelo admin nesta máquina.

    Levanta `CustodiaIndisponivel` se a consulta falhar. Devolver vazio aqui
    seria dizer "nada bloqueado, pode mandar tudo" — exatamente o contrário do
    que uma falha significa.
    """
    client = _supabase()
    if not client:
        raise CustodiaIndisponivel("Supabase não configurado")
    try:
        r = (
            client.table("cert_vault_bloqueio")
            .select("fingerprint")
            .eq("machine_id", machine_id)
            .execute()
        )
        return {str(row["fingerprint"]) for row in (r.data or []) if row.get("fingerprint")}
    except Exception as e:
        logger.exception("Falha ao listar bloqueios do cofre")
        raise CustodiaIndisponivel(str(e)) from e


def fingerprints_do_inventario(machine_id: str) -> Set[str]:
    """
    Fingerprints que a máquina reportou na varredura mais recente.

    O agente envia o snapshot (`/api/ingest`) ANTES de sincronizar o cofre no
    mesmo ciclo, então o inventário lido aqui é o desta varredura.

    Certificado vencido fica de fora: não instala, e guardar chave privada que
    não serve para nada é passivo puro. Certificado sem fingerprint idem — o
    scanner não conseguiu lê-lo.
    """
    client = _supabase()
    if not client:
        raise CustodiaIndisponivel("Supabase não configurado")
    try:
        r = (
            client.table("cert_snapshots")
            .select("items")
            .eq("machine_id", machine_id)
            .order("scanned_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.exception("Falha ao ler o inventário da máquina %s", machine_id)
        raise CustodiaIndisponivel(str(e)) from e

    linhas = r.data or []
    if not linhas:
        # Máquina que ainda não mandou varredura nenhuma. Não é erro: é uma
        # máquina sem certificados conhecidos, e o resultado correto é não
        # autorizar nada até ela se apresentar.
        return set()

    out: Set[str] = set()
    for item in (linhas[0].get("items") or []):
        fp = str(item.get("fingerprint_sha256") or "").strip()
        if not fp:
            continue
        if str(item.get("status") or "").strip().lower() in _STATUS_NAO_CUSTODIAVEL:
            continue
        out.add(fp)
    return out


# Vencido não instala; 'erro' e 'fora_do_padrao' o scanner não conseguiu ler.
# Guardar a chave privada destes é passivo sem contrapartida.
_STATUS_NAO_CUSTODIAVEL = {"expirado", "vencido", "erro", "fora_do_padrao"}


def fingerprints_autorizados(machine_id: str) -> Set[str]:
    """
    O que a máquina pode enviar ao cofre: inventário válido MENOS bloqueados.

    É a lista que o agente consome. O contrato com ele não mudou na inversão —
    ele sempre perguntou "o que posso mandar?" e agiu só sobre a resposta. O
    que mudou foi o que entra na resposta, e é por isso que o `.exe` instalado
    no ANALISESRV não precisou ser recompilado.
    """
    return fingerprints_do_inventario(machine_id) - listar_bloqueios(machine_id)


def reativar_custodia(fingerprint: str, machine_id: str) -> None:
    """
    Devolve o certificado ao cofre: apaga o bloqueio.

    O material volta sozinho na varredura seguinte — o agente passa a receber
    este fingerprint na lista de autorizados e reenvia o PFX. Não há o que
    restaurar aqui, porque o cofre é derivado dos arquivos do ANALISESRV.
    """
    client = _supabase()
    if not client:
        raise RuntimeError("Supabase não configurado")
    (
        client.table("cert_vault_bloqueio")
        .delete()
        .eq("fingerprint", fingerprint)
        .eq("machine_id", machine_id)
        .execute()
    )


def bloquear_custodia(
    fingerprint: str,
    machine_id: str,
    bloqueado_por: str,
    motivo: Optional[str] = None,
) -> None:
    """
    Tira o certificado do cofre e impede que ele volte.

    **O registro do bloqueio é a parte indispensável.** Sob opt-in bastava
    apagar a autorização e o material: sem autorização, o agente não reenviava.
    Sob opt-out, apagar só o material não resolve nada — o certificado continua
    no inventário, volta a ser autorizado no ciclo seguinte e o PFX sobe de
    novo. Seria um botão que parece funcionar e desfaz a si mesmo em 24 horas.

    O `machine_id` é obrigatório de propósito: sob a chave composta, agir só
    por fingerprint alcançaria todas as máquinas que têm o mesmo certificado.
    """
    client = _supabase()
    if not client:
        raise RuntimeError("Supabase não configurado")

    client.table("cert_vault_bloqueio").upsert(
        {
            "machine_id": machine_id,
            "fingerprint": fingerprint,
            "motivo": motivo,
            "bloqueado_por": bloqueado_por,
        },
        on_conflict="machine_id,fingerprint",
    ).execute()
    # A autorização legada sai junto: enquanto existir, ela contradiz o
    # bloqueio na trilha, e alguém lendo as duas tabelas veria o certificado
    # como autorizado e bloqueado ao mesmo tempo.
    (
        client.table("cert_vault_optin")
        .delete()
        .eq("fingerprint", fingerprint)
        .eq("machine_id", machine_id)
        .execute()
    )
    # Bloquear sem apagar o material deixaria a chave privada no servidor
    # indefinidamente — o oposto da intenção.
    (
        client.table("cert_pfx_store")
        .delete()
        .eq("fingerprint", fingerprint)
        .eq("machine_id", machine_id)
        .execute()
    )


# ──────────────────────────────────────────────────────────────────────────
# Carteira — quais clientes cada operador pode instalar
#
# É a outra metade do modelo de 15/08, e o inverso da custódia. A custódia
# ABRE por padrão (todo certificado válido entra no cofre, o admin desativa);
# o acesso FECHA por padrão (operador sem atribuição não instala nada). Os
# dois defaults são opostos de propósito: guardar a mais é desperdício,
# liberar a mais é vazamento.
# ──────────────────────────────────────────────────────────────────────────

PAPEIS_COM_ALCANCE_TOTAL = ("admin", "gestor")


class CarteiraIndisponivel(RuntimeError):
    """
    Não deu para determinar o que este usuário pode instalar.

    Mesma razão de `CustodiaIndisponivel`: "não sei" precisa ser um estado
    próprio. Um `except` que devolvesse carteira vazia negaria acesso — o lado
    seguro —, mas devolvê-la sem distinguir do caso real esconderia uma queda
    de banco atrás de um 403 confuso, e a próxima pessoa a mexer aqui poderia
    "consertar" invertendo o default.
    """


class ForaDaCarteira(PermissionError):
    """Pedido inclui certificado que o solicitante não pode instalar."""

    def __init__(self, documentos_negados: List[str]) -> None:
        self.documentos_negados = documentos_negados
        super().__init__(
            "Certificados fora da sua carteira: " + ", ".join(sorted(documentos_negados))
        )


def so_digitos(documento: Optional[str]) -> str:
    """
    Normaliza CNPJ/CPF para comparação.

    `cert_pfx_store.documento` e o inventário guardam só dígitos, mas nada
    impede alguém de atribuir "33.706.943/0001-93" pela tela. Formatos
    divergentes fariam a carteira nunca casar — sem erro, o operador só nunca
    conseguiria instalar, e ninguém saberia por quê.
    """
    return "".join(c for c in str(documento or "") if c.isdigit())


def listar_carteira(user_id: str) -> Set[str]:
    """
    Documentos que este usuário pode instalar.

    Levanta `CarteiraIndisponivel` se a consulta falhar, em vez de devolver
    vazio — ver a docstring da exceção.
    """
    client = _supabase()
    if not client:
        raise CarteiraIndisponivel("Supabase não configurado")
    try:
        r = (
            client.table("carteira")
            .select("documento")
            .eq("user_id", user_id)
            .execute()
        )
        return {so_digitos(row.get("documento")) for row in (r.data or []) if row.get("documento")}
    except Exception as e:
        logger.exception("Falha ao listar carteira de %s", user_id)
        raise CarteiraIndisponivel(str(e)) from e


def documentos_dos_certificados(certificate_ids: List[str]) -> Dict[str, str]:
    """
    Mapa `id do certificado -> documento`, para conferir contra a carteira.

    Certificado ausente do cofre não aparece no mapa; quem chama trata isso
    como negado, não como permitido.
    """
    client = _supabase()
    if not client:
        raise CarteiraIndisponivel("Supabase não configurado")
    try:
        r = (
            client.table("cert_pfx_store")
            .select("id, documento")
            .in_("id", certificate_ids)
            .execute()
        )
        return {str(row["id"]): so_digitos(row.get("documento")) for row in (r.data or [])}
    except Exception as e:
        logger.exception("Falha ao resolver documentos dos certificados")
        raise CarteiraIndisponivel(str(e)) from e


def assegurar_carteira(user_id: str, role: str, certificate_ids: List[str]) -> None:
    """
    Barreira de servidor do acesso. Levanta se algum certificado estiver fora.

    **Toda rota que cria um token de instalação precisa chamar isto.** Hoje são
    duas — a que enfileira para o agente e a que gera o download avulso — e
    `tests/test_carteira.py` percorre o código para falhar se alguma rota nova
    esquecer. Esconder ou desabilitar na tela é conveniência; a barreira é aqui.

    `admin` e `gestor` têm alcance total. Para o gestor isso é consequência da
    decisão de 15/08: quem pode atribuir qualquer cliente a qualquer operador
    pode atribuir a si mesmo, então limitá-lo seria teatro. Fica explícito em
    vez de implícito.

    Certificado sem documento é negado ao operador: não há como saber de quem
    ele é, logo não há como dizer que está na carteira de alguém.
    """
    if (role or "").strip().lower() in PAPEIS_COM_ALCANCE_TOTAL:
        return

    carteira = listar_carteira(user_id)
    documentos = documentos_dos_certificados(certificate_ids)

    negados: List[str] = []
    for cid in certificate_ids:
        doc = documentos.get(str(cid))
        if not doc or doc not in carteira:
            # Devolve o documento quando existe (o operador reconhece o
            # cliente); sem documento, identifica pelo id do certificado.
            negados.append(doc or f"certificado {cid}")

    if negados:
        raise ForaDaCarteira(negados)


# Motivos pelos quais um certificado do inventário não pode ser instalado.
# A ordem em que são avaliados importa: o motivo mostrado deve ser o mais
# fundamental, não o primeiro que a consulta encontrar. De nada adianta dizer
# "fora da sua carteira" sobre um certificado vencido — resolver a carteira não
# tornaria aquele instalável.
ESTADO_OK = "ok"
ESTADO_VENCIDO = "vencido"
ESTADO_ILEGIVEL = "ilegivel"
ESTADO_BLOQUEADO = "bloqueado"
ESTADO_FORA_DA_CARTEIRA = "fora_da_carteira"
ESTADO_NAO_ENVIADO = "nao_enviado"


def estado_de_instalabilidade(
    machine_id: str, user_id: str, role: str
) -> Dict[str, Dict[str, Any]]:
    """
    Para cada certificado do inventário desta máquina: dá para instalar, e se
    não, por quê.

    Uma chamada só, porque a tela precisa das quatro fontes cruzadas — o
    inventário, os bloqueios, o cofre e a carteira de quem está olhando — e
    fazer esse cruzamento no cliente espalharia a regra por dois lugares. A
    barreira de verdade continua em `assegurar_carteira`; isto existe para a
    tela não convidar o usuário a um erro que o servidor vai recusar depois.

    Levanta `CustodiaIndisponivel`/`CarteiraIndisponivel` em vez de degradar:
    uma tela que, na dúvida, marca tudo como instalável é pior que uma tela que
    diz "não consegui verificar".
    """
    client = _supabase()
    if not client:
        raise CustodiaIndisponivel("Supabase não configurado")

    try:
        r = (
            client.table("cert_snapshots")
            .select("items")
            .eq("machine_id", machine_id)
            .order("scanned_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as e:
        raise CustodiaIndisponivel(str(e)) from e

    linhas = r.data or []
    itens = (linhas[0].get("items") or []) if linhas else []

    bloqueados = listar_bloqueios(machine_id)
    no_cofre = {c.fingerprint: c.id for c in list_available_pfx(machine_id=machine_id)}

    alcance_total = (role or "").strip().lower() in PAPEIS_COM_ALCANCE_TOTAL
    carteira: Set[str] = set() if alcance_total else listar_carteira(user_id)

    out: Dict[str, Dict[str, Any]] = {}
    for item in itens:
        fp = str(item.get("fingerprint_sha256") or "").strip()
        if not fp:
            # Sem fingerprint não há o que instalar nem como identificar a
            # linha; a tela mostra pelo status do próprio inventário.
            continue

        status = str(item.get("status") or "").strip().lower()
        doc = so_digitos(item.get("documento_numero"))

        if status in ("expirado", "vencido"):
            estado = ESTADO_VENCIDO
        elif status in ("erro", "fora_do_padrao"):
            estado = ESTADO_ILEGIVEL
        elif fp in bloqueados:
            estado = ESTADO_BLOQUEADO
        elif not alcance_total and (not doc or doc not in carteira):
            estado = ESTADO_FORA_DA_CARTEIRA
        elif fp not in no_cofre:
            # Sob custódia e permitido, mas o agente ainda não subiu o material.
            # É estado transitório — some no próximo ciclo — e precisa ser dito,
            # senão a linha parece indevidamente bloqueada.
            estado = ESTADO_NAO_ENVIADO
        else:
            estado = ESTADO_OK

        out[fp] = {"id": no_cofre.get(fp), "estado": estado}

    return out


def atribuir_carteira(
    user_id: str,
    documentos: List[str],
    atribuido_por: Optional[str],
    atribuido_por_email: str,
) -> int:
    """Acrescenta documentos à carteira. Devolve quantos foram gravados."""
    client = _supabase()
    if not client:
        raise RuntimeError("Supabase não configurado")

    linhas = []
    for doc in documentos:
        d = so_digitos(doc)
        if not d:
            continue
        linhas.append(
            {
                "user_id": user_id,
                "documento": d,
                "atribuido_por": atribuido_por,
                "atribuido_por_email": atribuido_por_email,
            }
        )
    if not linhas:
        return 0

    client.table("carteira").upsert(linhas, on_conflict="user_id,documento").execute()
    return len(linhas)


def remover_da_carteira(user_id: str, documento: str) -> None:
    client = _supabase()
    if not client:
        raise RuntimeError("Supabase não configurado")
    (
        client.table("carteira")
        .delete()
        .eq("user_id", user_id)
        .eq("documento", so_digitos(documento))
        .execute()
    )


# ──────────────────────────────────────────────────────────────────────────
# Nome do arquivo baixado
#
# O `{token}` NÃO é decoração: o instalador avulso lê o token do próprio
# `argv[0]`. O binário é o mesmo para todo download — de propósito, para poder
# ser assinado uma vez e acumular reputação no SmartScreen —, então o nome do
# arquivo é o único canal por onde o token viaja até ele.
#
# Um template sem `{token}` produz um executável que abre, não encontra token
# nenhum e não instala nada. E o sintoma aparece na máquina do usuário final,
# a um agente e um servidor de distância de quem editou o campo.
# ──────────────────────────────────────────────────────────────────────────

TEMPLATE_NOME_PADRAO = "Instalar {nome} -{token}.exe"

_CARACTERES_PROIBIDOS = set('/\\:*?"<>|')


def validar_template_nome(template: str) -> str:
    """
    Devolve o template normalizado ou levanta `ValueError` com o motivo.

    Recusar na hora de salvar é a única defesa possível: depois de gravado, o
    defeito só se manifesta na máquina de quem baixou.
    """
    t = (template or "").strip()
    if not t:
        return ""   # vazio = usar o padrão do código

    if "{token}" not in t:
        raise ValueError(
            "O template precisa conter {token}: o instalador lê o token do "
            "próprio nome do arquivo. Sem ele, nada é instalado."
        )
    if not t.lower().endswith(".exe"):
        raise ValueError("O nome do arquivo precisa terminar em .exe.")
    if any(c in _CARACTERES_PROIBIDOS for c in t.replace("{nome}", "").replace("{token}", "")):
        raise ValueError('O nome não pode conter / \\ : * ? " < > |.')
    if len(t) > 120:
        raise ValueError("O template ficou longo demais (máximo 120 caracteres).")

    desconhecidos = set(re.findall(r"\{(\w+)\}", t)) - {"nome", "token"}
    if desconhecidos:
        raise ValueError(
            "Marcadores desconhecidos: "
            + ", ".join("{" + d + "}" for d in sorted(desconhecidos))
            + ". Use apenas {nome} e {token}."
        )
    return t


def montar_nome_do_arquivo(template: str, nome: str, token: str) -> str:
    """
    Aplica o template. O `nome` é sanitizado; o `token` nunca.

    Sanitizar o token o corromperia — ele precisa chegar íntegro ao instalador.
    Quem o gera é o servidor (`secrets`), e `_TOKEN_SEGURO` já o valida na
    rota de download antes de chegar aqui.
    """
    seguro = re.sub(r"[^A-Za-z0-9 _-]", "", str(nome or ""))[:60].strip() or "Certificado"
    try:
        t = validar_template_nome(template) or TEMPLATE_NOME_PADRAO
    except ValueError:
        # Template inválido gravado por algum caminho que escapou da validação:
        # cair no padrão entrega um instalador que funciona, em vez de um nome
        # quebrado. O erro fica no log, não na mão do usuário.
        logger.warning("Template de nome inválido em uso; caindo no padrão.")
        t = TEMPLATE_NOME_PADRAO
    return t.replace("{nome}", seguro).replace("{token}", token)


# ──────────────────────────────────────────────────────────────────────────
# Diagnóstico do cofre e das chaves
#
# Escrito depois do incidente de 15/08/2026: a CERT_ENCRYPTION_KEY foi trocada
# no painel da Vercel sem passar pela rotação, e TODO o conteúdo do cofre virou
# lixo cifrado. Nada na interface disse isso. Descobriu-se por um `InvalidTag`
# no meio de outra investigação, e o caminho documentado para consertar
# (CERT_ENCRYPTION_KEY_V<n>) estava ele próprio quebrado.
#
# O que segue existe para que a próxima rotação seja vista, não descoberta.
# ──────────────────────────────────────────────────────────────────────────

def diagnostico_do_cofre() -> Dict[str, Any]:
    """Números do cofre, agrupados pelo que costuma dar errado."""
    client = _supabase()
    if not client:
        raise RuntimeError("Supabase não configurado")

    r = (
        client.table("cert_pfx_store")
        .select("machine_id, key_version, updated_at, pfx_password_enc, pfx_password")
        .execute()
    )
    linhas = r.data or []

    por_maquina: Dict[str, int] = {}
    por_versao: Dict[str, int] = {}
    sem_senha = 0
    senha_em_claro = 0
    ultimo = None
    for row in linhas:
        por_maquina[str(row.get("machine_id") or "?")] = (
            por_maquina.get(str(row.get("machine_id") or "?"), 0) + 1
        )
        v = str(row.get("key_version") if row.get("key_version") is not None else "?")
        por_versao[v] = por_versao.get(v, 0) + 1
        if not row.get("pfx_password_enc"):
            sem_senha += 1
        if row.get("pfx_password"):
            senha_em_claro += 1
        u = row.get("updated_at")
        if u and (ultimo is None or u > ultimo):
            ultimo = u

    try:
        b = client.table("cert_vault_bloqueio").select("fingerprint").execute()
        bloqueios = len(b.data or [])
    except Exception:
        logger.exception("Falha ao contar bloqueios")
        bloqueios = None

    return {
        "total": len(linhas),
        "por_maquina": por_maquina,
        "por_key_version": por_versao,
        "ultimo_upload": ultimo,
        # Foi a causa ÚNICA das seis falhas de instalação registradas em
        # produção: "Senha ausente no cofre". Sem este número, descobrir isso
        # exigiu ler o agent.log de uma máquina remota.
        "sem_senha_cifrada": sem_senha,
        # Deve ser sempre zero. A coluna antiga guardava a senha sob a MESMA
        # chave do PFX, o que um vazamento entregava junto.
        "senha_em_claro": senha_em_claro,
        "bloqueios": bloqueios,
    }


def diagnostico_das_chaves() -> Dict[str, Any]:
    """
    Quais versões de chave existem, quais estão configuradas, e quais faltam.

    O campo que importa é `versoes_sem_chave`: versão com linhas vivas no cofre
    e sem chave no ambiente significa material **indecifrável agora**. É
    exatamente o estado em que o cofre ficou em 15/08, e ninguém viu.
    """
    from app import config

    diag = diagnostico_do_cofre()
    versoes_no_cofre = {
        int(v) for v in diag["por_key_version"] if str(v).isdigit()
    }

    configuradas = {CURRENT_KEY_VERSION} if getattr(config, "CERT_ENCRYPTION_KEY", "") else set()
    prefixo = "CERT_ENCRYPTION_KEY_V"
    for nome in dir(config):
        if nome.startswith(prefixo) and nome[len(prefixo):].isdigit():
            if (getattr(config, nome, "") or "").strip():
                configuradas.add(int(nome[len(prefixo):]))

    return {
        "versao_corrente": CURRENT_KEY_VERSION,
        "versoes_configuradas": sorted(configuradas),
        "versoes_no_cofre": sorted(versoes_no_cofre),
        "versoes_sem_chave": sorted(versoes_no_cofre - configuradas),
        "linhas_por_versao": diag["por_key_version"],
    }


def revalidar_cofre() -> List[Dict[str, Any]]:
    """
    Tenta decifrar UM PFX de cada `key_version` e reporta o que aconteceu.

    Contar linhas não prova nada: em 15/08 o cofre tinha uma linha íntegra, com
    todos os campos preenchidos, e completamente indecifrável. A única prova de
    que a chave certa está no ambiente é decifrar de fato. Uma amostra por
    versão basta — todas as linhas de uma versão usam a mesma chave.
    """
    client = _supabase()
    if not client:
        raise RuntimeError("Supabase não configurado")

    versoes = [
        int(v) for v in diagnostico_do_cofre()["por_key_version"] if str(v).isdigit()
    ]

    out: List[Dict[str, Any]] = []
    for versao in sorted(versoes):
        amostra = (
            client.table("cert_pfx_store")
            .select("id, fingerprint, encrypted_pfx, pfx_iv, pfx_auth_tag")
            .eq("key_version", versao)
            .limit(1)
            .execute()
        )
        linhas = amostra.data or []
        if not linhas:
            continue
        row = linhas[0]
        try:
            dados = decrypt_pfx_at_rest(
                row["encrypted_pfx"], row["pfx_iv"], row["pfx_auth_tag"], key_version=versao
            )
            ok, detalhe = True, f"{len(dados)} bytes decifrados"
        except Exception as e:  # noqa: BLE001
            ok, detalhe = False, str(e)
        out.append(
            {
                "key_version": versao,
                "ok": ok,
                "detalhe": detalhe,
                "fingerprint_amostra": str(row.get("fingerprint") or "")[:16],
            }
        )
    return out


# ──────────────────────────────────────────────────────────────────────────
# Validade do token e retenção do log
# ──────────────────────────────────────────────────────────────────────────

TTL_TOKEN_MIN = 1
TTL_TOKEN_MAX = 1440   # 24h


def ttl_do_token() -> int:
    """
    Minutos de validade do token de instalação.

    A configuração vence o ambiente; zero significa "usar o padrão do
    ambiente", não "expirar na hora". Os limites existem porque os dois
    extremos machucam: abaixo de um minuto o usuário perde a janela enquanto
    lê a tela, e acima de um dia o link fica vivo numa caixa de e-mail muito
    depois de ter servido.

    Nunca levanta: um token com validade padrão é melhor que uma instalação
    recusada porque a configuração estava ilegível.
    """
    try:
        from app.settings_state import load_settings

        valor = int(load_settings().install_token_ttl_min or 0)
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao ler o TTL configurado; usando o do ambiente")
        valor = 0

    if valor <= 0:
        valor = config.CERT_INSTALL_TOKEN_TTL_MIN
    return max(TTL_TOKEN_MIN, min(TTL_TOKEN_MAX, valor))


def expurgar_install_log(dias: Optional[int] = None) -> Dict[str, Any]:
    """
    Apaga registros de `install_log` mais antigos que a retenção configurada.

    `install_log` guarda `client_ip` e `user_email` e não tinha política de
    expurgo nenhuma: crescia para sempre com dado pessoal. Zero mantém o
    comportamento anterior (guardar tudo) de propósito — ligar o expurgo é
    decisão de quem responde pelos dados, não default de migration.

    Devolve o que fez, para o cron reportar em vez de trabalhar em silêncio.
    """
    if dias is None:
        try:
            from app.settings_state import load_settings

            dias = int(load_settings().install_log_retencao_dias or 0)
        except Exception as e:  # noqa: BLE001
            logger.exception("Falha ao ler a retenção configurada")
            return {"executado": False, "motivo": f"configuração ilegível: {e}"}

    if not dias or dias <= 0:
        return {"executado": False, "motivo": "retenção desligada (0 = guardar tudo)"}

    client = _supabase()
    if not client:
        return {"executado": False, "motivo": "Supabase não configurado"}

    corte = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    try:
        r = (
            client.table("install_log")
            .delete()
            .lt("created_at", corte)
            .execute()
        )
        apagados = len(r.data or [])
        logger.info("Expurgo de install_log: %s registros anteriores a %s", apagados, corte)
        return {"executado": True, "apagados": apagados, "corte": corte, "retencao_dias": dias}
    except Exception as e:  # noqa: BLE001
        logger.exception("Falha no expurgo de install_log")
        return {"executado": False, "motivo": str(e)}


# ──────────────────────────────────────────────────────────────────────────
# CRUD — install_token
# ──────────────────────────────────────────────────────────────────────────

def create_install_token(
    user_id: str,
    user_email: str,
    target_machine: str,
    certificate_ids: List[str],
    client_ip: Optional[str] = None,
) -> Tuple[str, str, datetime]:
    """
    Cria um token de uso único para instalação.
    Retorna (token_raw, token_id, expires_at).
    """
    client = _supabase()
    if not client:
        raise RuntimeError("Supabase não configurado")

    token_raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token_raw.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=ttl_do_token())

    row = {
        "token_hash": token_hash,
        "user_id": user_id,
        "user_email": user_email,
        "target_machine": target_machine,
        "certificate_ids": certificate_ids,
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "client_ip": client_ip,
    }

    try:
        r = client.table("install_token").insert(row).execute()
        token_id = str(r.data[0]["id"]) if r.data else ""
        return token_raw, token_id, expires_at
    except Exception:
        logger.exception("Falha ao criar install_token")
        raise


def validate_and_consume_token(token_raw: str) -> Optional[Dict[str, Any]]:
    """
    Valida e consome um token de instalação, de forma atômica.

    Retorna os dados do token se válido; None se inválido, expirado ou já
    consumido.

    A implementação anterior fazia SELECT e depois UPDATE em duas chamadas: dois
    resgates simultâneos passavam pelo SELECT antes de qualquer UPDATE e ambos
    recebiam o bundle — "uso único" era apenas intenção. O blueprint previa
    `SELECT ... FOR UPDATE`, que não existe na API REST do Supabase.

    A solução equivalente é um compare-and-swap: o UPDATE traz as condições
    (`consumed_at IS NULL` e `expires_at > agora`) na própria cláusula WHERE.
    O Postgres serializa UPDATEs concorrentes na mesma linha, então exatamente
    um deles encontra `consumed_at IS NULL` e escreve; o outro casa com zero
    linhas. Quem recebe linha de volta é o dono do token.
    """
    client = _supabase()
    if not client:
        return None

    token_hash = hashlib.sha256(token_raw.encode()).hexdigest()
    now = datetime.now(timezone.utc)

    try:
        r = (
            client.table("install_token")
            .update({"consumed_at": now.isoformat()})
            .eq("token_hash", token_hash)
            .is_("consumed_at", "null")
            .gt("expires_at", now.isoformat())
            .execute()
        )
        rows = r.data or []
        if not rows:
            # Não distinguimos os motivos para o chamador: token inexistente,
            # expirado, já consumido e perda da corrida produzem a mesma
            # resposta, para não virar oráculo de tokens válidos.
            logger.info("Resgate de token recusado (inexistente, expirado, consumido ou corrida).")
            return None

        if len(rows) > 1:
            # token_hash é UNIQUE na migration; se isto aparecer, o índice sumiu.
            logger.error("install_token com token_hash duplicado — verifique o índice UNIQUE.")

        return rows[0]
    except Exception:
        logger.exception("Falha ao validar/consumir install_token")
        return None


# ──────────────────────────────────────────────────────────────────────────
# CRUD — install_log
# ──────────────────────────────────────────────────────────────────────────

def log_event(
    event: str,
    user_id: str,
    user_email: Optional[str] = None,
    token_id: Optional[str] = None,
    certificate_id: Optional[str] = None,
    fingerprint: Optional[str] = None,
    target_machine: Optional[str] = None,
    status: Optional[str] = None,
    detail: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> None:
    """Grava um evento de auditoria na tabela install_log."""
    client = _supabase()
    if not client:
        logger.warning("Supabase indisponível; log de instalação não gravado: %s", event)
        return

    row: Dict[str, Any] = {
        "event": event,
        "user_id": user_id,
        "user_email": user_email,
    }
    if token_id:
        row["token_id"] = token_id
    if certificate_id:
        row["certificate_id"] = certificate_id
    if fingerprint:
        row["fingerprint"] = fingerprint
    if target_machine:
        row["target_machine"] = target_machine
    if status:
        row["status"] = status
    if detail:
        # Truncar detail para evitar overflow
        row["detail"] = (detail or "")[:2000]
    if client_ip:
        row["client_ip"] = client_ip

    try:
        client.table("install_log").insert(row).execute()
    except Exception:
        logger.exception("Falha ao gravar install_log (event=%s)", event)


def list_install_logs(
    limit: int = 100,
    user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lista logs de instalação ordenados por data decrescente."""
    client = _supabase()
    if not client:
        return []
    try:
        q = client.table("install_log").select("*")
        if user_id:
            q = q.eq("user_id", user_id)
        q = q.order("created_at", desc=True).limit(limit)
        r = q.execute()
        return list(r.data or [])
    except Exception:
        logger.exception("Falha ao listar install_log")
        return []


# Ordem em que os eventos acontecem numa instalação bem-sucedida. Serve para
# dizer ONDE a cadeia parou, que é a única coisa que a lista plana não dizia.
ORDEM_DOS_EVENTOS = ["SOLICITADO", "REDIMIDO", "CONCLUIDO"]


def cadeias_de_instalacao(
    limite: int = 500,
    desde: Optional[str] = None,
    user_email: Optional[str] = None,
    apenas_com_falha: bool = False,
) -> List[Dict[str, Any]]:
    """
    Agrupa `install_log` por token: uma linha por tentativa de instalação.

    A lista plana mostrava eventos soltos em ordem cronológica, e o que importa
    é **onde a cadeia quebrou**. Os números de produção explicam por quê:

        SOLICITADO 9  →  REDIMIDO 8  →  CONCLUIDO 2
                                        ERRO      6

    Lidos em fila, são 25 linhas sem forma. Agrupados, são nove tentativas das
    quais seis morreram no mesmo ponto e pela mesma causa — que foi como se
    descobriu que a senha estava ausente no cofre.

    `desde` é ISO-8601; a filtragem por período vai no banco, a por usuário e
    falha em memória (o agrupamento precisa da cadeia inteira para saber se ela
    falhou, então filtrar antes cortaria eventos da mesma tentativa).

    O limite é fixado em 1.000 porque é o teto do PostgREST: pedir mais devolve
    mil assim mesmo, **sem avisar que truncou**. Melhor um teto declarado que um
    número que parece completo e não é — foi assim que a curva de vencimento do
    dashboard perdeu 29 certificados em silêncio.
    """
    limite = min(limite, 1000)
    client = _supabase()
    if not client:
        return []

    try:
        q = client.table("install_log").select("*")
        if desde:
            q = q.gte("created_at", desde)
        r = q.order("created_at", desc=True).limit(limite).execute()
        eventos = list(r.data or [])
    except Exception:
        logger.exception("Falha ao listar install_log para agrupar")
        return []

    por_token: Dict[str, Dict[str, Any]] = {}
    for ev in eventos:
        # Evento sem token é raro mas existe (falha antes de o token nascer);
        # cai num balde próprio em vez de sumir da trilha.
        chave = str(ev.get("token_id") or f"sem-token:{ev.get('id')}")
        cadeia = por_token.setdefault(
            chave,
            {
                "token_id": ev.get("token_id"),
                "user_email": ev.get("user_email"),
                "target_machine": ev.get("target_machine"),
                "client_ip": ev.get("client_ip"),
                "eventos": [],
                "certificados": set(),
            },
        )
        cadeia["eventos"].append(
            {
                "event": ev.get("event"),
                "status": ev.get("status"),
                "detail": ev.get("detail"),
                "created_at": ev.get("created_at"),
                "certificate_id": ev.get("certificate_id"),
            }
        )
        if ev.get("certificate_id"):
            cadeia["certificados"].add(str(ev["certificate_id"]))

    saida: List[Dict[str, Any]] = []
    for cadeia in por_token.values():
        cadeia["eventos"].sort(key=lambda e: e["created_at"] or "")
        nomes = {e["event"] for e in cadeia["eventos"]}
        falhou = "ERRO" in nomes or any(e["status"] == "FALHA" for e in cadeia["eventos"])
        concluiu = "CONCLUIDO" in nomes

        if concluiu and not falhou:
            desfecho, parou_em = "concluido", None
        elif falhou:
            desfecho = "falhou"
            # Onde parou = último marco da ordem canônica que chegou a acontecer.
            alcancados = [e for e in ORDEM_DOS_EVENTOS if e in nomes]
            parou_em = alcancados[-1] if alcancados else None
        else:
            desfecho = "incompleto"
            alcancados = [e for e in ORDEM_DOS_EVENTOS if e in nomes]
            parou_em = alcancados[-1] if alcancados else None

        motivos = [
            e["detail"] for e in cadeia["eventos"]
            if e["detail"] and (e["event"] == "ERRO" or e["status"] == "FALHA")
        ]

        cadeia.update(
            {
                "certificados": len(cadeia["certificados"]),
                "desfecho": desfecho,
                "parou_em": parou_em,
                "motivos": sorted(set(motivos)),
                "inicio": cadeia["eventos"][0]["created_at"] if cadeia["eventos"] else None,
                "fim": cadeia["eventos"][-1]["created_at"] if cadeia["eventos"] else None,
            }
        )
        saida.append(cadeia)

    if user_email:
        alvo = user_email.strip().lower()
        saida = [c for c in saida if (c.get("user_email") or "").lower() == alvo]
    if apenas_com_falha:
        saida = [c for c in saida if c["desfecho"] == "falhou"]

    saida.sort(key=lambda c: c["inicio"] or "", reverse=True)
    return saida


def resumo_das_cadeias(cadeias: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Funil e causas, para a tela mostrar o número antes da tabela.

    `causas` é o campo que resolveu o caso real: as seis falhas de produção
    tinham a MESMA causa, e isso só aparece contando os motivos.
    """
    total = len(cadeias)
    concluidas = sum(1 for c in cadeias if c["desfecho"] == "concluido")
    falhadas = sum(1 for c in cadeias if c["desfecho"] == "falhou")

    causas: Dict[str, int] = {}
    for c in cadeias:
        for m in c["motivos"]:
            causas[m] = causas.get(m, 0) + 1

    return {
        "total": total,
        "concluidas": concluidas,
        "falhadas": falhadas,
        "incompletas": total - concluidas - falhadas,
        "taxa_conclusao": round(100 * concluidas / total) if total else None,
        "causas": dict(sorted(causas.items(), key=lambda kv: -kv[1])),
    }


# ──────────────────────────────────────────────────────────────────────────
# Montagem do bundle criptografado para o agente
# ──────────────────────────────────────────────────────────────────────────

def build_encrypted_bundle(
    certificate_ids: List[str],
    client_public_key_b64: str,
) -> Dict[str, Any]:
    """
    Busca os PFX, decifra do repouso, e re-cifra para o cliente via ECDH.
    Retorna o payload completo para o agente.
    """
    rows = get_pfx_by_ids(certificate_ids)
    if not rows:
        raise ValueError("Nenhum certificado encontrado para os IDs fornecidos")

    certificates = []
    for row in rows:
        # Decifrar PFX do repouso, com a chave da versão em que foi gravado
        pfx_bytes = decrypt_pfx_at_rest(
            row["encrypted_pfx"],
            row["pfx_iv"],
            row["pfx_auth_tag"],
            key_version=int(row.get("key_version") or CURRENT_KEY_VERSION),
        )

        # Re-cifrar para o cliente via ECDH
        bundle = encrypt_bundle_for_client(pfx_bytes, client_public_key_b64)
        bundle["certificateId"] = str(row["id"])
        bundle["fingerprint"] = str(row.get("fingerprint", ""))
        bundle["friendlyName"] = row.get("friendly_name") or row.get("nome_titular") or ""

        # A senha viaja cifrada para ESTE cliente (mesmo ECDH efêmero do PFX),
        # nunca em claro. O consumidor já esperava este formato desde o
        # endurecimento — ver installer_client._decrypt_payload_ecdh. Fica None
        # quando o registro é anterior à volta da senha ao cofre; nesse caso o
        # agente ainda a resolve pelo nome do arquivo local.
        bundle["pfxPassword"] = None
        if row.get("pfx_password_enc"):
            senha = decrypt_password_at_rest(
                row["pfx_password_enc"],
                row["pfx_password_iv"],
                row["pfx_password_tag"],
            )
            bundle["pfxPassword"] = encrypt_bundle_for_client(
                senha.encode("utf-8"), client_public_key_b64
            )

        certificates.append(bundle)

        # Nota: não há como zerar `pfx_bytes` de forma confiável aqui. `bytes` é
        # imutável em Python; reatribuir o nome (como se fazia antes) só cria um
        # objeto novo e deixa o PFX em claro na memória até o GC. Registrado como
        # limitação em vez de fingir mitigação.

    return {"certificates": certificates}


# ──────────────────────────────────────────────────────────────────────────
# Enfileirar comando de instalação na agent_command_queue
# ──────────────────────────────────────────────────────────────────────────

def enqueue_install_command(
    target_machine: str,
    token_raw: str,
) -> str:
    """
    Enfileira um comando 'instalar_certificados' para o agente, carregando o
    token de uso único no payload.

    A versão anterior recebia `token_raw` e não o gravava: o insert só tinha
    id/machine_id/command/status/created_at. O agente recebia o comando sem
    token, registrava "instalar_certificados recebido sem token" e nunca
    chamava /redeem — a instalação jamais acontecia.

    Reusa `command_queue.enqueue` em vez de inserir direto, para herdar a
    validação de comando e o fallback em disco quando o Supabase cai.
    """
    from app.command_queue import enqueue

    try:
        return enqueue(target_machine, "instalar_certificados", payload=token_raw)
    except Exception:
        logger.exception("Falha ao enfileirar comando de instalação")
        raise


# ──────────────────────────────────────────────────────────────────────────
# Limpeza de tokens expirados
# ──────────────────────────────────────────────────────────────────────────

def cleanup_expired_tokens() -> int:
    """Remove tokens expirados há mais de 1 dia. Retorna quantidade removida."""
    client = _supabase()
    if not client:
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    try:
        r = (
            client.table("install_token")
            .delete()
            .lt("expires_at", cutoff)
            .execute()
        )
        count = len(r.data or [])
        if count:
            logger.info("Tokens expirados removidos: %d", count)
        return count
    except Exception:
        logger.exception("Falha ao limpar tokens expirados")
        return 0
