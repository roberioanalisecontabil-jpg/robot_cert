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


# ── Escritas manuais: prazo e histórico ──────────────────────────────────

from tests.test_seguranca_lote1 import _Fake as _Grande  # noqa: E402


@pytest.fixture
def g(monkeypatch: pytest.MonkeyPatch) -> _Grande:
    fake = _Grande({"carteira": [], "carteira_historico": [], "users": [{"id": "u1", "email": "u1@x"}]})
    monkeypatch.setattr(ci, "_banco", lambda: fake)
    return fake


def test_atribuir_com_prazo_grava_e_historico(g):
    assert ci.atribuir_carteira("u1", ["111"], "a", "a@x", H, H + timedelta(days=30), hoje=H) == 1
    assert g.tabelas["carteira"][0]["valido_ate"] == "2026-12-13"
    h = g.tabelas["carteira_historico"]
    assert [(x["movimento"], x["origem"], x["documento"], x["user_email"], x["feito_por_email"]) for x in h] == [
        ("entrada", "manual", "111", "u1@x", "a@x")
    ]


def test_prazo_nao_toca_linha_do_acessorias(g):
    g.tabelas["carteira"] = [{"user_id": "u1", "documento": "111", "origem": "acessorias", "valido_ate": None}]
    assert ci.atribuir_carteira("u1", ["111"], "a", "a@x", H, H + timedelta(days=30), hoje=H) == 0
    assert g.tabelas["carteira"] == [{"user_id": "u1", "documento": "111", "origem": "acessorias", "valido_ate": None}]
    assert g.tabelas["carteira_historico"] == []


def test_reatribuir_manual_muda_prazo_sem_historico_novo(g):
    ci.atribuir_carteira("u1", ["111"], "a", "a@x", H, H + timedelta(days=30), hoje=H)
    ci.atribuir_carteira("u1", ["111"], "a", "a@x", H, H + timedelta(days=60), hoje=H)
    assert g.tabelas["carteira"][0]["valido_ate"] == "2027-01-12" and len(g.tabelas["carteira"]) == 1
    assert len(g.tabelas["carteira_historico"]) == 1


def test_remover_manual_grava_saida(g):
    ci.atribuir_carteira("u1", ["111"], "a", "a@x", hoje=H)
    ci.remover_da_carteira("u1", "111", "adm", "adm@x")
    ci.remover_da_carteira("u1", "111", "adm", "adm@x")  # já não existe: sem 2a saída
    assert g.tabelas["carteira"] == []
    assert [(x["movimento"], x["origem"], x["feito_por"]) for x in g.tabelas["carteira_historico"]][1:] == [
        ("saida", "manual", "adm")
    ]


def test_prazo_invalido_nao_grava(g):
    with pytest.raises(ci.PrazoInvalido):
        ci.atribuir_carteira("u1", ["111"], "a", "a@x", H, H + timedelta(days=701), hoje=H)
    assert g.tabelas["carteira"] == []


def test_planilha_preserva_manual_com_prazo(g):
    ci.atribuir_carteira("u1", ["111"], "a", "a@x", H, H + timedelta(days=30), hoje=H)
    antes = [dict(l) for l in g.tabelas["carteira"]]
    assert ci.atribuir_carteira("u1", ["111", "222"], "a", "a@x", hoje=H, preservar_existentes=True) == 1
    assert g.tabelas["carteira"][0] == antes[0]
    assert [x["documento"] for x in g.tabelas["carteira_historico"]] == ["111", "222"]


# ── Laço de vencimento ───────────────────────────────────────────────────

def _venc(g, monkeypatch, linhas):
    g.tabelas["carteira"] = linhas
    chamadas: List[str] = []
    monkeypatch.setattr(ci, "revogar_tokens_pendentes", lambda uid: chamadas.append(uid) or 0)
    return chamadas


def test_vencida_sai_com_historico_e_tokens(g, monkeypatch):
    rev = _venc(g, monkeypatch, [
        {"user_id": "u1", "documento": "111", "origem": "manual", "valido_ate": str(H - timedelta(days=1))},
        {"user_id": "u1", "documento": "222", "origem": "manual", "valido_ate": str(H)},
        {"user_id": "u1", "documento": "333", "origem": "acessorias", "valido_ate": None},
    ])
    assert ci.expirar_prazos(H) == 1
    assert [l["documento"] for l in g.tabelas["carteira"]] == ["222", "333"]
    h = g.tabelas["carteira_historico"]
    assert [(x["movimento"], x["origem"], x["documento"], x["feito_por"], x["feito_por_email"]) for x in h] == [
        ("saida", "prazo", "111", None, "prazo")
    ]
    assert rev == ["u1"]


def test_falha_numa_linha_nao_para_as_outras(g, monkeypatch):
    ontem = str(H - timedelta(days=1))
    _venc(g, monkeypatch, [
        {"user_id": "u1", "documento": "111", "origem": "manual", "valido_ate": ontem},
        {"user_id": "u1", "documento": "222", "origem": "manual", "valido_ate": ontem},
    ])
    exec_orig = type(g.table("carteira")).execute

    def execute(self):
        if self._op == "delete" and ("documento", "eq", "111") in self._f:
            raise RuntimeError("falha")
        return exec_orig(self)

    monkeypatch.setattr(type(g.table("carteira")), "execute", execute)
    assert ci.expirar_prazos(H) == 1
    assert [l["documento"] for l in g.tabelas["carteira"]] == ["111"]


def test_renovada_entre_select_e_delete_nao_sai(g, monkeypatch):
    rev = _venc(g, monkeypatch, [
        {"user_id": "u1", "documento": "111", "origem": "manual", "valido_ate": str(H - timedelta(days=1))},
    ])
    orig = g.table

    def table(n):
        q = orig(n)
        od = q.delete

        def delete():
            g.tabelas["carteira"][0]["valido_ate"] = str(H + timedelta(days=30))  # renovada agora
            return od()

        q.delete = delete
        return q

    monkeypatch.setattr(g, "table", table)
    assert ci.expirar_prazos(H) == 0
    assert len(g.tabelas["carteira"]) == 1
    assert g.tabelas["carteira_historico"] == [] and rev == []


def test_nao_manual_com_prazo_vencido_fica(g, monkeypatch):
    rev = _venc(g, monkeypatch, [
        {"user_id": "u1", "documento": "111", "origem": "acessorias", "valido_ate": str(H - timedelta(days=1))},
    ])
    assert ci.expirar_prazos(H) == 0
    assert len(g.tabelas["carteira"]) == 1 and rev == []


def test_origem_nao_manual_nunca_some_por_prazo(banco):
    banco.carteira = [{"user_id": "u1", "documento": "111", "origem": "acessorias", "valido_desde": "2020-01-01", "valido_ate": "2020-02-01"}]
    assert ci.listar_carteira("u1") == {"111"}
    assert ci.vigente({"origem": "acessorias", "valido_ate": "2020-02-01"}, H)
    assert not ci.vigente({"origem": "manual", "valido_ate": "2020-02-01"}, H)
