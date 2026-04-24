"""Testes unitários do leitor de nomes e serialização."""

from pathlib import Path

import pytest

from app.cert_scanner import (
    CertStatus,
    cert_to_public_dict,
    extract_cn_rfc4514,
    formatar_cnpj_cpf,
    parse_nome_cnpj_cpf_from_cn,
    parse_pfx_filename,
)


@pytest.mark.parametrize(
    "filename,expected_logical,expected_pwd",
    [
        ("Minha Loja senha segredo123.pfx", "Minha Loja", "segredo123"),
        ("ACME senha x.pfx", "ACME", "x"),
    ],
)
def test_parse_pfx_filename_ok(
    filename: str, expected_logical: str, expected_pwd: str
) -> None:
    r = parse_pfx_filename(filename)
    assert r is not None
    logical, pwd = r
    assert logical == expected_logical
    assert pwd == expected_pwd


@pytest.mark.parametrize(
    "filename",
    [
        "sem-senha-no-nome.pfx",
        "nome.pfx",
        "",
    ],
)
def test_parse_pfx_filename_invalid(filename: str) -> None:
    assert parse_pfx_filename(filename) is None


def test_cn_cnpj_cpf_br() -> None:
    r = "CN=INSTITUTO SILVA E DINA:66030755000147"
    cn = extract_cn_rfc4514(r)
    assert cn and "INSTITUTO" in cn
    n, d, t = parse_nome_cnpj_cpf_from_cn(cn)
    assert n == "INSTITUTO SILVA E DINA"
    assert t == "cnpj"
    assert len(d) == 14
    assert formatar_cnpj_cpf(d, t) == "66.030.755/0001-47"


def test_cpf_from_cn() -> None:
    n, d, t = parse_nome_cnpj_cpf_from_cn("ALGUEM:12345678901")
    assert t == "cpf" and len(d) == 11


def test_cert_to_public_dict() -> None:
    from app.cert_scanner import CertInfo

    c = CertInfo(
        path=Path("/x/teste senha abc.pfx"),
        file_name="teste senha abc.pfx",
        display_name="teste",
        status=CertStatus.OK,
    )
    d = cert_to_public_dict(c)
    assert d["status"] == "ok"
    assert d["file_name"] == "teste senha abc.pfx"
    assert d["nome"] == "teste"
    assert "path" in d
    assert "not_before" in d and "not_after" in d
