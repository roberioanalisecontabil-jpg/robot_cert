"""
Auditoria run-2, item 11: o cofre tira fingerprint e CNPJ do certificado dentro
do PFX, mas aceitava qualquer montagem — um autoassinado com "CLIENTE:<CNPJ>"
no CN, ou o certificado verdadeiro do cliente com outra chave — e arquivava
sob o CNPJ do cliente.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import cert_installer
from tests.pfx_de_teste import DOC_PADRAO, SENHA_PADRAO, ac_de_teste, gerar_pfx


def _montar(*, autoassinado: bool = False, sem_chave: bool = False) -> bytes:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sujeito = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"VITIMA LTDA:{DOC_PADRAO}")])
    ac_chave, ac_nome = ac_de_teste()
    agora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(sujeito).issuer_name(sujeito if autoassinado else ac_nome)
        .public_key(chave.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1)).not_valid_after(agora + timedelta(days=30))
        .sign(chave if autoassinado else ac_chave, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        b"x", None if sem_chave else chave, cert, None, serialization.BestAvailableEncryption(SENHA_PADRAO.encode()))


def test_pfx_emitido_por_ac_com_a_propria_chave_entra() -> None:
    lido = cert_installer.ler_metadados_do_pfx(gerar_pfx()["bytes"], SENHA_PADRAO)
    assert lido["documento"] == DOC_PADRAO


@pytest.mark.parametrize("montagem", [{"autoassinado": True}, {"sem_chave": True}])
def test_pfx_montado_e_recusado(montagem: dict) -> None:
    with pytest.raises(ValueError):
        cert_installer.ler_metadados_do_pfx(_montar(**montagem), SENHA_PADRAO)


def test_certificado_verdadeiro_com_outra_chave_e_recusado(monkeypatch: pytest.MonkeyPatch) -> None:
    """A `cryptography` se recusa a montar esse PFX, mas outra ferramenta
    monta; aqui a leitura devolve o par trocado."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12

    _chave, cert, extras = pkcs12.load_key_and_certificates(gerar_pfx()["bytes"], SENHA_PADRAO.encode())
    outra = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(pkcs12, "load_key_and_certificates", lambda *_a, **_k: (outra, cert, extras))
    with pytest.raises(ValueError, match="chave"):
        cert_installer.ler_metadados_do_pfx(b"qualquer", SENHA_PADRAO)
