"""Instala um certificado digital na sessao de quem esta usando a maquina.

Veio de `core/instalador_certificado.py` do Hardlyze 2.2.0 (que por sua vez
copiou o esquema de `agent/installer_client.py` deste repositorio). A bandeja
pega o token na fila do portal (`/api/estacao/instalacoes`) e chama `instalar`.

── Por que so a bandeja pode rodar isto ─────────────────────────────────

`certutil -user ... My` importa no repositorio pessoal DA CONTA QUE EXECUTA O
PROCESSO. Rodando como LocalSystem, o certificado entraria no perfil do SYSTEM:
o certutil retornaria sucesso, o portal registraria INSTALADO — e a pessoa nao
veria nada no navegador nem no e-CAC. Falha que se apresenta como exito.

── Por que nao ha pasta local a consultar ───────────────────────────────

O `/claim` troca o token de uso unico (que expira em minutos) pelo bundle, e a
senha do PFX vem nele, cifrada pelo mesmo ECDH efemero desta execucao.
"""

from __future__ import annotations

import base64
import logging
import os
import subprocess
import tempfile

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ec import (
    ECDH,
    SECP256R1,
    EllipticCurvePublicKey,
    generate_private_key,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

LOGGER = logging.getLogger(__name__)

TEMPO_LIMITE = 60


class InstalacaoIndisponivel(RuntimeError):
    """Falta configuracao para instalar certificados nesta estacao."""


def _decifrar(privada, bloco: dict) -> bytes:
    """ECDH + HKDF + AES-256-GCM — o mesmo esquema do portal de certificados.

    O `info=b"cert-installer-v1"` do HKDF tem de bater exatamente com o do
    servidor; qualquer divergencia da erro de autenticacao do GCM, nao texto
    errado. Copiado de `agent/installer_client.py` do robot_cert.
    """
    servidor = serialization.load_der_public_key(base64.b64decode(bloco["serverPublicKey"]))
    if not isinstance(servidor, EllipticCurvePublicKey):
        raise ValueError("Chave publica do servidor invalida")

    compartilhado = privada.exchange(ECDH(), servidor)
    chave = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"cert-installer-v1"
    ).derive(compartilhado)

    aesgcm = AESGCM(chave)
    return aesgcm.decrypt(
        base64.b64decode(bloco["iv"]),
        base64.b64decode(bloco["ciphertext"]) + base64.b64decode(bloco["authTag"]),
        None,
    )


def _importar(pfx: bytes, senha: str) -> tuple[bool, str]:
    """Importa no repositorio do USUARIO, marcado como nao-exportavel.

    `-user` e o ponto: com ele o certificado vai para quem executa o processo,
    e e por isso que este codigo tem de rodar na bandeja. `NoExport` impede que
    a chave privada seja copiada dali para outro lugar.
    """
    pasta = tempfile.mkdtemp(prefix="cert_inst_")
    caminho = os.path.join(pasta, "temp.pfx")
    try:
        with open(caminho, "wb") as f:
            f.write(pfx)
        r = subprocess.run(
            ["certutil", "-f", "-user", "-p", senha or "", "-importpfx", "My", caminho, "NoExport"],
            capture_output=True,
            text=True,
            timeout=30,
            # `check=False` explicito: o returncode e tratado logo abaixo,
            # porque a mensagem do certutil e o que a pessoa precisa ver.
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if r.returncode == 0:
            return True, "Instalado no repositorio do usuario (NoExport)"
        erro = r.stderr.strip() or r.stdout.strip() or f"codigo {r.returncode}"
        return False, f"certutil falhou: {erro}"
    except Exception as e:
        LOGGER.exception("Erro ao importar PFX")
        return False, str(e)
    finally:
        # Sobrescreve antes de apagar: `unlink` so tira a entrada do diretorio,
        # e o conteudo — uma chave privada — continuaria no disco ate ser
        # reaproveitado.
        try:
            if os.path.exists(caminho):
                with open(caminho, "wb") as f:
                    f.write(b"\x00" * len(pfx))
                os.remove(caminho)
            os.rmdir(pasta)
        except OSError:
            LOGGER.warning("Nao consegui limpar %s", pasta)


def instalar(token: str, portal: str | None = None, sessao=None,
             cabecalhos: dict | None = None) -> list[dict]:
    """Resgata o bundle com o token e instala cada certificado.

    Devolve a lista de resultados, que quem chama reporta ao portal.

    `sessao` e injetada nos testes; em producao usa `httpx` direto.
    `cabecalhos`: a credencial da bandeja (`X-Device-Secret`). Com ela o
    portal confere que quem resgata e a maquina-alvo, com vinculo autorizado.
    """
    base = (portal or "").strip().rstrip("/")
    if not base:
        raise InstalacaoIndisponivel("Sem o endereco do portal de certificados.")
    if not (token or "").strip():
        raise InstalacaoIndisponivel("Comando de instalacao sem token.")

    http = sessao or httpx
    privada = generate_private_key(SECP256R1())
    publica = base64.b64encode(
        privada.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    ).decode()

    r = http.post(
        f"{base}/api/cert-installer/claim",
        json={"token": token, "clientPublicKey": publica},
        headers=dict(cabecalhos or {}),
        timeout=TEMPO_LIMITE,
    )
    if r.status_code != 200:
        detalhe = ""
        try:
            detalhe = str((r.json() or {}).get("detail") or "")
        except Exception:
            detalhe = (getattr(r, "text", "") or "")[:200]
        raise RuntimeError(detalhe or f"O portal recusou o resgate ({r.status_code}).")

    certificados = (r.json() or {}).get("certificates") or []
    if not certificados:
        raise RuntimeError("O portal nao devolveu certificado nenhum para este token.")

    resultados: list[dict] = []
    for item in certificados:
        fingerprint = item.get("fingerprint", "")
        pfx = b""
        try:
            pfx = _decifrar(privada, item)
            senha = ""
            if item.get("pfxPassword"):
                senha = _decifrar(privada, item["pfxPassword"]).decode("utf-8")
            if not senha:
                # Falhar aqui, com causa nomeada, em vez de deixar o certutil
                # recusar por "senha incorreta" — que aponta para o lugar errado.
                resultados.append({
                    "certificateId": item.get("certificateId", ""),
                    "fingerprint": fingerprint,
                    "status": "FALHA",
                    "detail": "O portal nao enviou a senha deste certificado (cofre).",
                })
                continue
            ok, detalhe = _importar(pfx, senha)
            resultados.append({
                "certificateId": item.get("certificateId", ""),
                "fingerprint": fingerprint,
                "status": "OK" if ok else "FALHA",
                "detail": detalhe,
            })
        except Exception as e:
            LOGGER.exception("Falha ao instalar %s", fingerprint[:16])
            resultados.append({
                "certificateId": item.get("certificateId", ""),
                "fingerprint": fingerprint,
                "status": "FALHA",
                "detail": f"Erro ao decifrar ou importar: {e}",
            })
        finally:
            # Zera o PFX da memoria assim que sai de uso.
            pfx = b"\x00" * len(pfx)

    # Reportar e melhor esforco: o certificado JA esta instalado, e uma falha de
    # rede aqui nao pode transformar sucesso em erro para o usuario.
    try:
        http.post(
            f"{base}/api/cert-installer/report-avulso",
            json={"token": token, "results": resultados},
            timeout=TEMPO_LIMITE,
        )
    except Exception:
        LOGGER.warning("Instalacao concluida, mas o relatorio nao chegou ao portal.")

    return resultados
