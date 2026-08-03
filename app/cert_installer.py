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
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

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

def _get_server_key() -> bytes:
    """Retorna a chave AES-256 do servidor (32 bytes) a partir do hex no .env."""
    raw = config.CERT_ENCRYPTION_KEY
    if not raw or len(raw) != 64:
        raise RuntimeError(
            "CERT_ENCRYPTION_KEY não configurada ou inválida. "
            "Gere com: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    return bytes.fromhex(raw)


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


def decrypt_pfx_at_rest(ciphertext_b64: str, iv_b64: str, auth_tag_b64: str) -> bytes:
    """Decifra um PFX armazenado no banco."""
    key = _get_server_key()
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

    # Cifrar a senha do PFX junto (se fornecida)
    encrypted_password = None
    if password:
        pwd_ct, pwd_iv, pwd_tag = encrypt_pfx_at_rest(password.encode("utf-8"))
        # Armazenar como JSON compacto: iv:tag:ct
        encrypted_password = f"{pwd_iv}:{pwd_tag}:{pwd_ct}"

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
        "pfx_password": encrypted_password,
        "updated_at": now,
    }

    try:
        r = (
            client.table("cert_pfx_store")
            .upsert(row, on_conflict="fingerprint")
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
    expires_at = now + timedelta(minutes=config.CERT_INSTALL_TOKEN_TTL_MIN)

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
    Valida e consome um token de instalação.
    Retorna os dados do token se válido, None se inválido/expirado/já consumido.
    """
    client = _supabase()
    if not client:
        return None

    token_hash = hashlib.sha256(token_raw.encode()).hexdigest()
    now = datetime.now(timezone.utc)

    try:
        r = (
            client.table("install_token")
            .select("*")
            .eq("token_hash", token_hash)
            .is_("consumed_at", "null")
            .execute()
        )
        rows = r.data or []
        if not rows:
            return None

        token_row = rows[0]

        # Verificar expiração
        expires_at = datetime.fromisoformat(token_row["expires_at"].replace("Z", "+00:00"))
        if now > expires_at:
            logger.warning("Token expirado (expires_at=%s)", token_row["expires_at"])
            return None

        # Marcar como consumido
        client.table("install_token").update(
            {"consumed_at": now.isoformat()}
        ).eq("id", token_row["id"]).execute()

        return token_row
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
        # Decifrar PFX do repouso
        pfx_bytes = decrypt_pfx_at_rest(
            row["encrypted_pfx"],
            row["pfx_iv"],
            row["pfx_auth_tag"],
        )

        # Decifrar senha do PFX (se houver)
        pfx_password = None
        if row.get("pfx_password"):
            parts = row["pfx_password"].split(":", 2)
            if len(parts) == 3:
                pwd_bytes = decrypt_pfx_at_rest(parts[2], parts[0], parts[1])
                pfx_password = pwd_bytes.decode("utf-8")

        # Re-cifrar para o cliente via ECDH
        bundle = encrypt_bundle_for_client(pfx_bytes, client_public_key_b64)
        bundle["certificateId"] = str(row["id"])
        bundle["fingerprint"] = str(row.get("fingerprint", ""))
        bundle["friendlyName"] = row.get("friendly_name") or row.get("nome_titular") or ""

        # Senha do PFX cifrada junto no bundle para o agente
        if pfx_password:
            pwd_bundle = encrypt_bundle_for_client(
                pfx_password.encode("utf-8"),
                client_public_key_b64,
            )
            bundle["pfxPassword"] = pwd_bundle
        else:
            bundle["pfxPassword"] = None

        certificates.append(bundle)

        # Zerar PFX em claro da memória
        pfx_bytes = b"\x00" * len(pfx_bytes)

    return {"certificates": certificates}


# ──────────────────────────────────────────────────────────────────────────
# Enfileirar comando de instalação na agent_command_queue
# ──────────────────────────────────────────────────────────────────────────

def enqueue_install_command(
    target_machine: str,
    token_raw: str,
) -> str:
    """
    Enfileira um comando 'instalar_certificados' na fila do agente.
    Retorna o ID do comando.
    """
    client = _supabase()
    if not client:
        raise RuntimeError("Supabase não configurado")

    cid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    try:
        client.table("agent_command_queue").insert({
            "id": cid,
            "machine_id": target_machine,
            "command": "instalar_certificados",
            "status": "pending",
            "created_at": now,
        }).execute()
        return cid
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
