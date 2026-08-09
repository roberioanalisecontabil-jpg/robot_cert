"""
Cliente do Módulo Instalador de Certificados para o Agente Windows.

Responsável por:
1. Enviar arquivos PFX encontrados no scan local para o servidor (/upload-pfx)
2. Processar o comando de instalação 'instalar_certificados':
   - Gera chaves efêmeras ECDH (P-256)
   - Executa handshake redeem com o servidor (/redeem)
   - Descriptografa PFXs e senhas exclusivamente em memória / temp seguro
   - Importa no repositório do Windows marcado como NÃO-EXPORTÁVEL (certutil NoExport)
   - Envia relatório de execução ao servidor (/report)
"""

from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import tempfile
from typing import Any, Dict, List, Optional

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ec import (
    ECDH,
    EllipticCurvePublicKey,
    SECP256R1,
    generate_private_key,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.cert_scanner import CertInfo

LOGGER = logging.getLogger("analise_certidigital_agent")


def _buscar_fingerprints_autorizados(
    client: httpx.Client,
    base_url: str,
    headers: dict,
    machine_id: str,
) -> Optional[set]:
    """
    Lista de certificados autorizados a ir para o cofre.

    Devolve None se a consulta falhar — o chamador interpreta como "não enviar
    nada". Falha fechada de propósito: na dúvida, não copiar chave privada para
    o servidor.
    """
    try:
        r = client.get(
            f"{base_url}/api/cert-installer/vault-optin",
            headers=headers,
            params={"machine_id": machine_id},
            timeout=30,
        )
        if r.status_code != 200:
            LOGGER.warning("Não foi possível obter a lista do cofre (%s).", r.status_code)
            return None
        return {str(f) for f in (r.json().get("fingerprints") or [])}
    except Exception as e:
        LOGGER.warning("Falha ao consultar a lista do cofre: %s", e)
        return None


def upload_pfx_files(
    client: httpx.Client,
    base_url: str,
    headers: dict,
    machine_id: str,
    items: List[CertInfo],
) -> None:
    """
    Envia ao cofre APENAS os .pfx explicitamente autorizados.

    Antes esta função enviava todos os certificados lidos, a cada ciclo de scan.
    Numa base de mil certificados, isso copiava mil chaves privadas (e suas
    senhas) para o Supabase sem que ninguém tivesse decidido — e reenviava tudo
    a cada varredura.
    """
    autorizados = _buscar_fingerprints_autorizados(client, base_url, headers, machine_id)
    if autorizados is None:
        LOGGER.info("Sincronização com o cofre ignorada: lista de autorizações indisponível.")
        return
    if not autorizados:
        LOGGER.debug("Nenhum certificado autorizado ao cofre; nada a enviar.")
        return

    enviados = 0
    for c in items:
        if not c.path or not c.path.is_file():
            continue
        # Só envia certificados válidos/lidos que possuam fingerprint
        if not c.fingerprint_sha256:
            continue
        if c.fingerprint_sha256 not in autorizados:
            continue

        try:
            pfx_bytes = c.path.read_bytes()
            pfx_b64 = base64.b64encode(pfx_bytes).decode("utf-8")

            payload = {
                "fingerprint": c.fingerprint_sha256,
                "machine_id": machine_id,
                "pfx_b64": pfx_b64,
                # A senha NÃO é mais enviada: o servidor a descarta e o agente
                # a lê do nome do arquivo local na hora de instalar.
                "nome_titular": c.nome_titular,
                "documento": c.documento_numero,
                "documento_tipo": c.documento_tipo,
                "subject": c.subject,
                "not_before": c.not_before.isoformat() if c.not_before else None,
                "not_after": c.not_after.isoformat() if c.not_after else None,
                "friendly_name": c.display_name,
            }

            resp = client.post(
                f"{base_url}/api/cert-installer/upload-pfx",
                headers=headers,
                json=payload,
            )
            if resp.status_code == 200:
                enviados += 1
                LOGGER.debug("PFX %s enviado com sucesso ao servidor.", c.file_name)
            else:
                LOGGER.warning(
                    "Aviso ao enviar PFX %s (%s): %s",
                    c.file_name,
                    resp.status_code,
                    resp.text,
                )
        except Exception as ex:
            LOGGER.exception("Falha ao enviar arquivo PFX %s: %s", c.file_name, ex)

    if enviados:
        LOGGER.info(
            "Cofre sincronizado: %d de %d certificados autorizados enviados.",
            enviados,
            len(autorizados),
        )


def _decrypt_payload_ecdh(
    client_private_key,
    bundle: dict,
) -> bytes:
    """Decifram um objeto cifrado via ECDH + HKDF + AES-256-GCM."""
    server_pub_b64 = bundle["serverPublicKey"]
    iv_b64 = bundle["iv"]
    tag_b64 = bundle["authTag"]
    ciphertext_b64 = bundle["ciphertext"]

    server_pub_bytes = base64.b64decode(server_pub_b64)
    server_pub_key = serialization.load_der_public_key(server_pub_bytes)
    if not isinstance(server_pub_key, EllipticCurvePublicKey):
        raise ValueError("Chave pública do servidor inválida")

    shared_key = client_private_key.exchange(ECDH(), server_pub_key)
    derived_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"cert-installer-v1",
    ).derive(shared_key)

    aesgcm = AESGCM(derived_key)
    nonce = base64.b64decode(iv_b64)
    ciphertext = base64.b64decode(ciphertext_b64)
    auth_tag = base64.b64decode(tag_b64)

    return aesgcm.decrypt(nonce, ciphertext + auth_tag, None)


def _import_pfx_non_exportable(pfx_bytes: bytes, password: str) -> tuple[bool, str]:
    """
    Importa um PFX no Windows Certificate Store (My/User) marcado como NÃO-EXPORTÁVEL.
    Usa certutil via subprocess.
    """
    temp_dir = tempfile.mkdtemp(prefix="cert_inst_")
    temp_pfx_path = os.path.join(temp_dir, "temp_cert.pfx")

    try:
        # Grava o PFX temporário
        with open(temp_pfx_path, "wb") as f:
            f.write(pfx_bytes)

        # Executa certutil para importar como NoExport no repositório do Usuário (My)
        cmd = [
            "certutil",
            "-f",
            "-user",
            "-p",
            password or "",
            "-importpfx",
            "My",
            temp_pfx_path,
            "NoExport",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        if result.returncode == 0:
            LOGGER.info("Certificado importado com sucesso como NÃO-EXPORTÁVEL.")
            return True, "Instalado com sucesso no Windows Certificate Store (NoExport)"
        else:
            err_msg = result.stderr.strip() or result.stdout.strip() or f"Código de saída {result.returncode}"
            LOGGER.error("Falha ao importar PFX via certutil: %s", err_msg)
            return False, f"Certutil falhou: {err_msg}"

    except Exception as ex:
        LOGGER.exception("Erro ao executar importação do PFX: %s", ex)
        return False, str(ex)

    finally:
        # Sanitiza e apaga o arquivo temporário
        try:
            if os.path.exists(temp_pfx_path):
                file_size = os.path.getsize(temp_pfx_path)
                with open(temp_pfx_path, "wb") as f:
                    f.write(b"\x00" * file_size)
                os.remove(temp_pfx_path)
            if os.path.exists(temp_dir):
                os.rmdir(temp_dir)
        except Exception:
            pass


def _senhas_por_fingerprint(source_dir) -> dict:
    """
    Mapeia fingerprint -> senha, lida do nome dos arquivos locais.

    A senha do PFX deixou de ser armazenada no servidor no endurecimento de
    03/08 (era cifrada com a MESMA chave do PFX, então guardá-la junto não
    protegia nada). O plano registrado em `cert_installer.py` era o agente
    extraí-la do nome do arquivo na hora de instalar — mas essa parte nunca foi
    escrita: o bundle chega com `pfxPassword: None` e a instalação seguia com
    senha vazia, fazendo o certutil recusar todo PFX protegido, que são todos.

    A extração já existia em `cert_scanner` (padrão «nome» senha «valor».pfx,
    exposto em `CertInfo.password_from_name`); faltava ligar as duas pontas.
    """
    if not source_dir:
        return {}
    try:
        from app.cert_scanner import scan_folder

        mapa = {}
        for c in scan_folder(source_dir, recursive=True):
            if c.fingerprint_sha256 and c.password_from_name:
                mapa[c.fingerprint_sha256] = c.password_from_name
        return mapa
    except Exception as ex:
        LOGGER.warning("Não foi possível ler as senhas dos arquivos locais: %s", ex)
        return {}


def process_install_command(
    client: httpx.Client,
    base_url: str,
    headers: dict,
    token: str,
    source_dir=None,
) -> bool:
    """
    Executa o ciclo completo de resgate e instalação de certificados via comando remoto.

    `source_dir` é a pasta de certificados da estação: é de onde sai a senha de
    cada PFX, já que o servidor não a guarda mais.
    """
    LOGGER.info("Iniciando processo de instalação remota de certificados (token %s...)", token[:8])

    # 1. Gerar par de chaves ECDH P-256 efêmero
    client_private_key = generate_private_key(SECP256R1())
    client_public_key = client_private_key.public_key()
    pub_spki_bytes = client_public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    client_pub_b64 = base64.b64encode(pub_spki_bytes).decode("utf-8")

    # 2. Requisitar o bundle de certificados em /redeem
    redeem_payload = {
        "token": token,
        "clientPublicKey": client_pub_b64,
    }

    try:
        resp = client.post(
            f"{base_url}/api/cert-installer/redeem",
            headers=headers,
            json=redeem_payload,
        )
        if resp.status_code != 200:
            LOGGER.error("Falha no redeem do token (%s): %s", resp.status_code, resp.text)
            return False
        data = resp.json()
    except Exception as ex:
        LOGGER.exception("Erro ao conectar com /redeem: %s", ex)
        return False

    certificates = data.get("certificates", [])
    if not certificates:
        LOGGER.warning("Nenhum certificado retornado no bundle do token %s.", token)
        return False

    results = []

    # Senhas dos arquivos locais. Lidas uma vez só: a varredura da pasta leva
    # alguns segundos numa base grande e o bundle costuma trazer vários itens.
    senhas_locais = _senhas_por_fingerprint(source_dir)

    # 3. Processar cada certificado no bundle
    for item in certificates:
        cert_id = item.get("certificateId", "")
        fingerprint = item.get("fingerprint", "")
        try:
            pfx_bytes = _decrypt_payload_ecdh(client_private_key, item)

            # Ordem: senha do arquivo local primeiro; o bundle só como
            # compatibilidade com registros anteriores ao endurecimento, que
            # ainda podem trazer `pfxPassword` preenchido.
            password = senhas_locais.get(fingerprint, "")
            if not password:
                pwd_bundle = item.get("pfxPassword")
                if pwd_bundle:
                    pwd_bytes = _decrypt_payload_ecdh(client_private_key, pwd_bundle)
                    password = pwd_bytes.decode("utf-8")

            if not password:
                # Falhar aqui, com causa nomeada, em vez de deixar o certutil
                # recusar por "senha incorreta" — que aponta para o lugar errado.
                LOGGER.error(
                    "Senha não encontrada para o certificado %s. O arquivo precisa "
                    "existir na pasta local seguindo «nome» senha «valor».pfx",
                    fingerprint[:16],
                )
                results.append({
                    "certificateId": cert_id,
                    "fingerprint": fingerprint,
                    "status": "FALHA",
                    "detail": (
                        "Senha do PFX não encontrada: o arquivo não está na pasta "
                        "local desta estação, ou o nome não segue o padrão "
                        "«nome» senha «valor».pfx"
                    ),
                })
                pfx_bytes = b"\x00" * len(pfx_bytes)
                continue

            success, detail = _import_pfx_non_exportable(pfx_bytes, password)

            # Zerar buffers
            pfx_bytes = b"\x00" * len(pfx_bytes)

            results.append({
                "certificateId": cert_id,
                "fingerprint": fingerprint,
                "status": "OK" if success else "FALHA",
                "detail": detail,
            })
        except Exception as ex:
            LOGGER.exception("Erro ao processar certificado ID %s: %s", cert_id, ex)
            results.append({
                "certificateId": cert_id,
                "fingerprint": fingerprint,
                "status": "FALHA",
                "detail": f"Erro de descriptografia ou importação: {ex}",
            })

    # 4. Enviar relatório com os resultados ao servidor em /report
    report_payload = {
        "token": token,
        "results": results,
    }

    try:
        report_resp = client.post(
            f"{base_url}/api/cert-installer/report",
            headers=headers,
            json=report_payload,
        )
        if report_resp.status_code == 200:
            LOGGER.info("Relatório de instalação enviado com sucesso!")
        else:
            LOGGER.warning("Aviso no /report (%s): %s", report_resp.status_code, report_resp.text)
    except Exception as ex:
        LOGGER.exception("Erro ao enviar relatório em /report: %s", ex)

    return True
