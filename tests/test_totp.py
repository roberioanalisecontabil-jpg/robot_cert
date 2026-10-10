"""TOTP (RFC 6238) contra os vetores oficiais da RFC — apêndice B."""

import base64
import hashlib

from app import totp

# Semente do apêndice B para SHA1: "12345678901234567890" (20 bytes).
SEMENTE = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
# (tempo Unix, código de 8 dígitos esperado)
VETORES = [(59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"),
           (1234567890, "89005924"), (2000000000, "69279037"), (20000000000, "65353130")]


def test_vetores_da_rfc_6238() -> None:
    for t, esperado in VETORES:
        assert totp.codigo(SEMENTE, t // 30, digitos=8, algoritmo=hashlib.sha1) == esperado, t


def test_verificar_aceita_um_passo_de_folga_e_devolve_o_passo() -> None:
    s = totp.novo_segredo()
    agora = 1_700_000_000
    atual = totp.passo_atual(agora)
    assert totp.verificar(s, totp.codigo(s, atual), agora) == atual
    assert totp.verificar(s, totp.codigo(s, atual - 1), agora) == atual - 1
    assert totp.verificar(s, totp.codigo(s, atual + 1), agora) == atual + 1
    assert totp.verificar(s, totp.codigo(s, atual - 3), agora) is None


def test_formato_errado_nao_passa() -> None:
    s = totp.novo_segredo()
    for ruim in ("", "12345", "1234567", "abcdef", None):
        assert totp.verificar(s, ruim, 1_700_000_000) is None


def test_segredo_e_uri() -> None:
    s = totp.novo_segredo()
    assert len(s) == 32 and "=" not in s
    u = totp.uri(s, "ana@x.com")
    assert u.startswith("otpauth://totp/") and f"secret={s}" in u
    assert totp.agrupado("ABCDEFGH") == "ABCD EFGH"
