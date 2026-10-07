"""
Campos ICP-Brasil lidos do certificado (06/10/2026, modal de detalhes).

Até a 1.6.1 o agente só guardava datas, sujeito, emissor, série e
fingerprint. O modal do Início pede responsável, CPF e nascimento do
responsável e e-mail, que moram no SubjectAltName como otherName
(DOC-ICP-04): no e-CNPJ, 2.16.76.1.3.2 = nome do responsável e
2.16.76.1.3.4 = nascimento DDMMAAAA + CPF + NIS + RG + órgão; no e-CPF,
2.16.76.1.3.1 traz os mesmos dados do próprio titular.

Os certificados aqui são gerados no teste, com os otherName codificados
como OCTET STRING (o que as ACs usam) e PrintableString (já visto).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from app.cert_scanner import campos_icp, cert_to_public_dict, scan_folder

CPF_RESP = "05375987406"
NASC = "14081984"


def _der(tag: int, conteudo: bytes) -> bytes:
    assert len(conteudo) < 128
    return bytes([tag, len(conteudo)]) + conteudo


def _octet(texto: str) -> bytes:
    return _der(0x04, texto.encode("ascii"))


def _printable(texto: str) -> bytes:
    return _der(0x13, texto.encode("ascii"))


def _cert(cn: str, outros: list, email: str | None = None, org: str = "ICP-Brasil",
          emissor_cn: str = "AC SAFEWEB RFB v5"):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sujeito = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "BR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, org),
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
    ])
    emissor = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ICP-Brasil"),
        x509.NameAttribute(NameOID.COMMON_NAME, emissor_cn),
    ])
    nomes = [x509.OtherName(x509.ObjectIdentifier(oid), valor) for oid, valor in outros]
    if email:
        nomes.append(x509.RFC822Name(email))
    agora = datetime.now(timezone.utc)
    b = (
        x509.CertificateBuilder()
        .subject_name(sujeito).issuer_name(emissor).public_key(key.public_key())
        .serial_number(0x66FFEEF438C45637)
        .not_valid_before(agora - timedelta(days=1))
        .not_valid_after(agora + timedelta(days=108))
    )
    if nomes:
        b = b.add_extension(x509.SubjectAlternativeName(nomes), critical=False)
    return key, b.sign(key, hashes.SHA256())


def test_ecnpj_traz_responsavel_cpf_nascimento_email_e_emissor() -> None:
    _k, cert = _cert(
        "A G LIMA:30822879000118",
        [
            ("2.16.76.1.3.4", _octet(NASC + CPF_RESP + "0" * 11 + "0" * 15 + "SSP PE")),
            ("2.16.76.1.3.2", _octet("ANTONIO GALDINO LIMA")),
            ("2.16.76.1.3.3", _octet("30822879000118")),
        ],
        email="ANTONIOGALDINOLIMA@GMAIL.COM",
    )
    c = campos_icp(cert)
    assert c == {
        "tipo_icp": "e-CNPJ",
        "organizacao": "ICP-Brasil",
        "emissor": "AC SAFEWEB RFB v5",
        "responsavel_nome": "ANTONIO GALDINO LIMA",
        "responsavel_cpf": CPF_RESP,
        "responsavel_nascimento": "1984-08-14",
        "email": "ANTONIOGALDINOLIMA@GMAIL.COM",
    }


def test_ecpf_usa_o_proprio_titular_como_responsavel() -> None:
    _k, cert = _cert(
        "MARIA DA SILVA:12345678901",
        [("2.16.76.1.3.1", _printable("01021990" + "12345678901" + "0" * 11))],
    )
    c = campos_icp(cert)
    assert c["tipo_icp"] == "e-CPF"
    assert c["responsavel_nome"] == "MARIA DA SILVA"
    assert c["responsavel_cpf"] == "12345678901"
    assert c["responsavel_nascimento"] == "1990-02-01"
    assert c["email"] is None


def test_campos_zerados_ou_ausentes_viram_none() -> None:
    """ICP preenche com zeros o que não informa; zero não é CPF nem data."""
    _k, cert = _cert("SEM DADOS LTDA:11111111000191", [("2.16.76.1.3.4", _octet("0" * 19))])
    c = campos_icp(cert)
    assert c["responsavel_cpf"] is None and c["responsavel_nascimento"] is None
    assert c["responsavel_nome"] is None
    _k, sem_san = _cert("SEM SAN LTDA:11111111000191", [])
    c = campos_icp(sem_san)
    assert c["tipo_icp"] == "e-CNPJ" and c["responsavel_cpf"] is None and c["email"] is None


def test_otherName_inesperado_nao_derruba_a_leitura() -> None:
    # DER válido, mas uma SEQUENCE com INTEGER no lugar do texto.
    _k, cert = _cert("TORTO LTDA:11111111000191", [("2.16.76.1.3.4", b"\x30\x03\x02\x01\x05")])
    c = campos_icp(cert)
    assert c["responsavel_cpf"] is None and c["emissor"] == "AC SAFEWEB RFB v5"


def test_leitor_de_tlv_aguenta_bytes_truncados() -> None:
    from app.cert_scanner import _texto_do_der
    assert _texto_do_der(b"\x04\x85") is None
    assert _texto_do_der(b"\x04\x05abc") is None
    assert _texto_do_der(b"") is None
    assert _texto_do_der(b"\x04\x81\x03abc") == "abc"


def test_varredura_leva_os_campos_ao_inventario(tmp_path: Path) -> None:
    key, cert = _cert(
        "A G LIMA:30822879000118",
        [("2.16.76.1.3.4", _octet(NASC + CPF_RESP)), ("2.16.76.1.3.2", _octet("ANTONIO GALDINO LIMA"))],
        email="antonio@x.com.br",
    )
    pfx = pkcs12.serialize_key_and_certificates(b"t", key, cert, None, serialization.BestAvailableEncryption(b"s1"))
    (tmp_path / "A G LIMA senha s1.pfx").write_bytes(pfx)
    [info] = scan_folder(tmp_path)
    d = cert_to_public_dict(info)
    assert d["responsavel_nome"] == "ANTONIO GALDINO LIMA"
    assert d["responsavel_cpf"] == CPF_RESP and d["responsavel_nascimento"] == "1984-08-14"
    assert d["email"] == "antonio@x.com.br" and d["emissor"] == "AC SAFEWEB RFB v5"
    assert d["organizacao"] == "ICP-Brasil" and d["tipo_icp"] == "e-CNPJ"
    assert d["serial_number"] == "66ffeef438c45637"
