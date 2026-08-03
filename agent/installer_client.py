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


def upload_pfx_files(
    client: httpx.Client,
    base_url: str,
    headers: dict,
    machine_id: str,
    items: List[CertInfo],
) -> None:
    """Envia os arquivos .pfx lidos para o servidor armazenar com criptografia."""
    for c in items:
        if not c.path or not c.path.is_file():
            continue
        # Só envia certificados válidos/lidos que possuam fingerprint
        if not c.fingerprint_sha256:
            continue

        try:
            pfx_bytes = c.path.read_bytes()
            pfx_b64 = base64.b64encode(pfx_bytes).decode("utf-8")

            payload = {
                "fingerprint": c.fingerprint_sha256,
                "machine_id": machine_id,
                "pfx_b64": pfx_b64,
                "password": c.password_from_name,
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


def process_install_command(
    client: httpx.Client,
    base_url: str,
    headers: dict,
    token: str,
) -> bool:
    """
    Executa o ciclo completo de resgate e instalação de certificados via comando remoto.
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

    # 3. Processar cada certificado no bundle
    for item in certificates:
        cert_id = item.get("certificateId", "")
        fingerprint = item.get("fingerprint", "")
        try:
            pfx_bytes = _decrypt_payload_ecdh(client_private_key, item)

            password = ""
            pwd_bundle = item.get("pfxPassword")
            if pwd_bundle:
                pwd_bytes = _decrypt_payload_ecdh(client_private_key, pwd_bundle)
                password = pwd_bytes.decode("utf-8")

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
