"""Código de uso único da bandeja (login pela Microsoft): amarrado ao desafio."""

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from app import bandeja_codigo as bc
from tests.test_recuperacao_de_senha import _Fake


@pytest.fixture
def banco() -> _Fake:
    return _Fake({"bandeja_codigo": []})


def test_desafio_e_base64url_do_sha256() -> None:
    assert bc.desafio_de("abc") == "ungWv48Bz-pBQUDeXa4iI7ADYaOWF3qctBD_YfIAFa0"


def test_emitir_guarda_so_o_hash(banco: _Fake) -> None:
    codigo = bc.emitir("u-1", bc.desafio_de("v"), banco)
    (linha,) = banco.tabelas["bandeja_codigo"]
    assert codigo not in [str(v) for v in linha.values()]
    assert linha["codigo_hash"] == hashlib.sha256(codigo.encode()).hexdigest()


def test_queimar_certo_devolve_o_usuario_uma_vez(banco: _Fake) -> None:
    codigo = bc.emitir("u-1", bc.desafio_de("v"), banco)
    assert bc.queimar(codigo, "v", banco) == "u-1"
    assert bc.queimar(codigo, "v", banco) is None


def test_verificador_errado_queima(banco: _Fake) -> None:
    codigo = bc.emitir("u-1", bc.desafio_de("v"), banco)
    assert bc.queimar(codigo, "errado", banco) is None
    assert bc.queimar(codigo, "v", banco) is None


def test_vencido_nao_vale(banco: _Fake) -> None:
    codigo = bc.emitir("u-1", bc.desafio_de("v"), banco)
    passado = datetime.now(timezone.utc) - timedelta(seconds=1)
    banco.tabelas["bandeja_codigo"][0]["expira_em"] = passado.isoformat()
    assert bc.queimar(codigo, "v", banco) is None


def test_codigo_desconhecido_none(banco: _Fake) -> None:
    assert bc.queimar("nao-existe", "v", banco) is None


def test_emitir_apaga_linhas_com_mais_de_um_dia(banco: _Fake) -> None:
    velha = datetime.now(timezone.utc) - timedelta(days=2)
    banco.tabelas["bandeja_codigo"].append(
        {"codigo_hash": "x", "expira_em": velha.isoformat(), "usado_em": None})
    bc.emitir("u-1", bc.desafio_de("v"), banco)
    assert [r["codigo_hash"] for r in banco.tabelas["bandeja_codigo"]] != ["x"]
    assert len(banco.tabelas["bandeja_codigo"]) == 1
