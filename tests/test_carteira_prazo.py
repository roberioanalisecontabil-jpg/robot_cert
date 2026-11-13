"""Prazo da liberacao na carteira: vigencia e limite de 700 dias."""

from datetime import date, timedelta
from typing import Any, Dict, List

import pytest

import app.cert_installer as ci

H = date(2026, 11, 13)


class _Res:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _Q:
    def __init__(self, linhas: List[Dict[str, Any]]) -> None:
        self._l, self._f = linhas, []

    def select(self, *_c: str) -> "_Q":
        return self

    def eq(self, c: str, v: Any) -> "_Q":
        self._f.append((c, v))
        return self

    def execute(self) -> _Res:
        return _Res([dict(r) for r in self._l if all(r.get(c) == v for c, v in self._f)])


class _Fake:
    def __init__(self) -> None:
        self.carteira: List[Dict[str, Any]] = []

    def table(self, nome: str) -> _Q:
        assert nome == "carteira"
        return _Q(self.carteira)


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake()
    monkeypatch.setattr(ci, "_banco", lambda: fake)
    return fake


def test_700_aceita_701_recusa():
    ci.validar_prazo(H, H + timedelta(days=700), H)
    with pytest.raises(ci.PrazoInvalido):
        ci.validar_prazo(H, H + timedelta(days=701), H)


def test_inicio_no_passado_recusa():
    with pytest.raises(ci.PrazoInvalido):
        ci.validar_prazo(H - timedelta(days=1), None, H)


def test_fim_antes_do_inicio_recusa():
    with pytest.raises(ci.PrazoInvalido):
        ci.validar_prazo(H + timedelta(days=5), H + timedelta(days=4), H)


def test_vigente():
    assert ci.vigente({"valido_desde": "2026-11-13", "valido_ate": None}, H)
    assert ci.vigente({}, H)  # linha antiga, antes da migration
    assert ci.vigente({"valido_desde": H, "valido_ate": H}, H)  # objetos date
    assert not ci.vigente({"valido_desde": "2026-11-14"}, H)
    assert not ci.vigente({"valido_desde": "2026-01-01", "valido_ate": "2026-11-12"}, H)


def test_inicio_futuro_nao_instala(banco):
    banco.carteira = [{"user_id": "u1", "documento": "111", "valido_desde": "2099-01-01", "valido_ate": None}]
    assert ci.listar_carteira("u1") == set()
    assert [l["documento"] for l in ci.detalhar_carteira("u1")] == ["111"]


def test_vencida_nao_instala_e_vigente_sim(banco):
    banco.carteira = [
        {"user_id": "u1", "documento": "111", "valido_desde": "2020-01-01", "valido_ate": "2020-02-01"},
        {"user_id": "u1", "documento": "222", "valido_desde": "2020-01-01", "valido_ate": None},
    ]
    assert ci.listar_carteira("u1") == {"222"}
