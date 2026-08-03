"""
Testes unitários e de integração para o Módulo Instalador de Certificados Digitais.
"""

import base64
import os
import secrets
import pytest
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ec import (
    ECDH,
    SECP256R1,
    generate_private_key,
)

from app import cert_installer, config


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    """Gera uma chave de teste de 64 hex chars para o CERT_ENCRYPTION_KEY."""
    test_key = secrets.token_hex(32)
    monkeypatch.setattr(config, "CERT_ENCRYPTION_KEY", test_key)
    monkeypatch.setattr(config, "CERT_INSTALL_TOKEN_TTL_MIN", 5)


def test_encrypt_decrypt_at_rest():
    """Testa cifra e decifra de PFX com AES-256-GCM em repouso."""
    payload = b"DADOS_PFX_DE_TESTE_123456789"
    ct_b64, iv_b64, tag_b64 = cert_installer.encrypt_pfx_at_rest(payload)

    assert isinstance(ct_b64, str)
    assert isinstance(iv_b64, str)
    assert isinstance(tag_b64, str)

    decrypted = cert_installer.decrypt_pfx_at_rest(ct_b64, iv_b64, tag_b64)
    assert decrypted == payload


def test_ecdh_bundle_roundtrip():
    """Testa cifra de bundle pelo servidor e decifra pelo cliente via ECDH efêmero."""
    # 1. Cliente gera par ECDH P-256
    client_priv = generate_private_key(SECP256R1())
    client_pub = client_priv.public_key()
    pub_spki = client_pub.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    client_pub_b64 = base64.b64encode(pub_spki).decode()

    # 2. Servidor cifra payload
    pfx_bytes = b"SECRET_PFX_DATA_FOR_CLIENT"
    bundle = cert_installer.encrypt_bundle_for_client(pfx_bytes, client_pub_b64)

    assert "serverPublicKey" in bundle
    assert "iv" in bundle
    assert "authTag" in bundle
    assert "ciphertext" in bundle

    # 3. Cliente decifra com sua chave privada efêmera
    from agent.installer_client import _decrypt_payload_ecdh
    decrypted = _decrypt_payload_ecdh(client_priv, bundle)
    assert decrypted == pfx_bytes


def test_stored_pfx_dataclass():
    """Testa inicialização do dataclass StoredPfx."""
    pfx = cert_installer.StoredPfx(
        id="test-id",
        fingerprint="sha256-abc",
        machine_id="machine-1",
        nome_titular=" Fulano de Tal",
        documento="12345678901",
        documento_tipo="cpf",
        subject="CN=Fulano",
        not_before="2026-01-01T00:00:00Z",
        not_after="2027-01-01T00:00:00Z",
        friendly_name="Cert-1",
        uploaded_at="2026-08-03T00:00:00Z",
    )
    assert pfx.id == "test-id"
    assert pfx.documento_tipo == "cpf"


def test_invalid_key_raises():
    """Garante erro claro se a chave AES não estiver configurada."""
    with patch.object(config, "CERT_ENCRYPTION_KEY", ""):
        with pytest.raises(RuntimeError, match="CERT_ENCRYPTION_KEY não configurada"):
            cert_installer._get_server_key()
