"""Frente 2, itens 13 e 14: o teto vale entre instâncias; a fila não duplica.

O que está preso aqui:

  * `taxa.permitir` conta no BANCO — a janela é uma só para todas as
    instâncias serverless, que era o furo do R5 (memória de instância dilui o
    teto em cold starts)
  * sem banco, degrada para a janela em memória (o comportamento antigo), e
    o teto continua valendo dentro da instância
  * o pop da fila usa a RPC atômica; sem a função no banco, cai no caminho de
    duas idas COM aviso — deploy antes da migration não para a fila
  * fila vazia pela RPC é resposta final (None), não desculpa para reler tudo
  * /api/login e /claim respondem 429 quando o teto diz não
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from app import command_queue as cq
from app import taxa


# ──────────────────────────────────────────────────────────────────────────
# Banco falso mínimo para a tabela de tentativas (eq/gte/lt sobre `quando`)
# ──────────────────────────────────────────────────────────────────────────


class _Res:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _QueryTaxa:
    def __init__(self, linhas: List[Dict[str, Any]]) -> None:
        self._linhas = linhas
        self._op = "select"
        self._payload: Dict[str, Any] | None = None
        self._filtros: List[tuple] = []

    def select(self, *_c: str) -> "_QueryTaxa":
        return self

    def insert(self, payload: Dict[str, Any]) -> "_QueryTaxa":
        self._op, self._payload = "insert", payload
        return self

    def delete(self) -> "_QueryTaxa":
        self._op = "delete"
        return self

    def eq(self, col: str, val: Any) -> "_QueryTaxa":
        self._filtros.append(("eq", col, val))
        return self

    def gte(self, col: str, val: Any) -> "_QueryTaxa":
        self._filtros.append(("gte", col, val))
        return self

    def lt(self, col: str, val: Any) -> "_QueryTaxa":
        self._filtros.append(("lt", col, val))
        return self

    def _casa(self, linha: Dict[str, Any]) -> bool:
        for op, col, val in self._filtros:
            atual = linha.get(col)
            if op == "eq" and atual != val:
                return False
            if op == "gte" and not (str(atual) >= str(val)):
                return False
            if op == "lt" and not (str(atual) < str(val)):
                return False
        return True

    def execute(self) -> _Res:
        if self._op == "insert":
            self._linhas.append(dict(self._payload or {}))
            return _Res([dict(self._payload or {})])
        if self._op == "delete":
            fora = [r for r in self._linhas if self._casa(r)]
            self._linhas[:] = [r for r in self._linhas if not self._casa(r)]
            return _Res(fora)
        return _Res([dict(r) for r in self._linhas if self._casa(r)])


class _FakeBancoTaxa:
    def __init__(self) -> None:
        self.linhas: List[Dict[str, Any]] = []

    def table(self, _nome: str) -> _QueryTaxa:
        return _QueryTaxa(self.linhas)


@pytest.fixture
def banco_taxa(monkeypatch: pytest.MonkeyPatch) -> _FakeBancoTaxa:
    fake = _FakeBancoTaxa()
    monkeypatch.setattr(taxa, "_supabase", lambda: fake)
    return fake


# ──────────────────────────────────────────────────────────────────────────
# 1. Item 13 — a janela durável
# ──────────────────────────────────────────────────────────────────────────


def test_o_teto_conta_no_banco(banco_taxa: _FakeBancoTaxa) -> None:
    for _ in range(3):
        assert taxa.permitir("t:1.2.3.4", 3, 60.0) is True
    assert taxa.permitir("t:1.2.3.4", 3, 60.0) is False
    # E as tentativas estão no BANCO — qualquer instância veria as mesmas.
    assert len(banco_taxa.linhas) == 3


def test_o_teto_e_por_chave(banco_taxa: _FakeBancoTaxa) -> None:
    for _ in range(3):
        taxa.permitir("t:1.2.3.4", 3, 60.0)
    assert taxa.permitir("t:1.2.3.4", 3, 60.0) is False
    assert taxa.permitir("t:5.6.7.8", 3, 60.0) is True


def test_tentativa_fora_da_janela_nao_conta(banco_taxa: _FakeBancoTaxa) -> None:
    banco_taxa.linhas.append(
        {"chave": "t:1.2.3.4", "quando": "2020-01-01T00:00:00+00:00"}
    )
    assert taxa.permitir("t:1.2.3.4", 1, 60.0) is True


def test_a_poda_limpa_o_rastro_antigo_da_chave(banco_taxa: _FakeBancoTaxa) -> None:
    banco_taxa.linhas.append(
        {"chave": "t:1.2.3.4", "quando": "2020-01-01T00:00:00+00:00"}
    )
    taxa.permitir("t:1.2.3.4", 5, 60.0)
    quandos = [linha["quando"] for linha in banco_taxa.linhas]
    assert "2020-01-01T00:00:00+00:00" not in quandos, "a linha velha tinha de sair"


def test_sem_banco_degrada_para_memoria_e_o_teto_continua(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(taxa, "_supabase", lambda: None)
    for _ in range(3):
        assert taxa.permitir("m:1.2.3.4", 3, 60.0) is True
    assert taxa.permitir("m:1.2.3.4", 3, 60.0) is False


def test_banco_quebrado_nao_derruba_a_rota(monkeypatch: pytest.MonkeyPatch) -> None:
    """O limitador degrada; nunca vira a causa de um 500."""

    class _Explode:
        def table(self, _n: str):
            raise RuntimeError("banco fora do ar")

    monkeypatch.setattr(taxa, "_supabase", lambda: _Explode())
    assert taxa.permitir("q:1.2.3.4", 3, 60.0) is True


# ──────────────────────────────────────────────────────────────────────────
# 2. As rotas respeitam o teto (e leem o IP atrás do proxy)
# ──────────────────────────────────────────────────────────────────────────


def test_login_estourado_vira_429(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(taxa, "permitir", lambda *_a, **_k: False)
    r = client.post("/api/login", json={"email": "a@x.com", "password": "x"})
    assert r.status_code == 429


def test_claim_estourado_vira_429(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(taxa, "permitir", lambda *_a, **_k: False)
    r = client.post(
        "/api/cert-installer/claim",
        json={"token": "t" * 32, "clientPublicKey": "x"},
    )
    assert r.status_code == 429


def test_ip_atras_do_proxy_vem_do_x_forwarded_for() -> None:
    """Atrás da Vercel, `request.client.host` é o PROXY: sem ler o cabeçalho,
    o teto "por IP" era um teto global de todo mundo junto."""
    from app.main import _ip_do_cliente

    class _Req:
        headers = {"x-forwarded-for": "203.0.113.7, 10.0.0.1"}
        client = None

    assert _ip_do_cliente(_Req()) == "203.0.113.7"


# ──────────────────────────────────────────────────────────────────────────
# 3. Item 14 — o pop atômico da fila
# ──────────────────────────────────────────────────────────────────────────


_LINHA = {
    "id": "cmd-1",
    "machine_id": "SRV01",
    "command": "rescan",
    "status": "pending",
    "created_at": datetime.now(timezone.utc).isoformat(),
}


class _FakeRpc:
    """Cliente cuja RPC funciona — o caminho novo, atômico."""

    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self._data = data
        self.tabelas_tocadas: List[str] = []

    def rpc(self, nome: str, _params: Dict[str, Any]):
        assert nome == "pop_agent_command"
        return self

    def execute(self) -> _Res:
        return _Res(self._data)

    def table(self, nome: str):
        self.tabelas_tocadas.append(nome)
        raise AssertionError("com a RPC no ar, ninguém deveria ler a tabela")


def test_pop_usa_a_rpc_e_nao_rele_a_tabela() -> None:
    cmd = cq._pop_from_supabase(_FakeRpc([dict(_LINHA)]), "SRV01")
    assert cmd is not None
    assert cmd.id == "cmd-1"
    assert cmd.command == "rescan"
    assert cmd.status == "popped"


def test_fila_vazia_pela_rpc_e_resposta_final() -> None:
    """None da RPC significa 'não há comando' — reler tudo pelo caminho de
    duas idas reintroduziria exatamente a corrida que a RPC fecha."""
    assert cq._pop_from_supabase(_FakeRpc([]), "SRV01") is None


class _FakeSemFuncao:
    """Cliente sem a migration: a RPC explode e o legado tem de assumir."""

    def __init__(self) -> None:
        self.fila = [dict(_LINHA)]
        self._sel = None

    def rpc(self, _nome: str, _params: Dict[str, Any]):
        raise RuntimeError(
            "Could not find the function public.pop_agent_command (PGRST202)"
        )

    def table(self, _nome: str):
        return self

    def select(self, *_c):
        self._op = "select"
        return self

    def eq(self, *_a):
        return self

    def order(self, *_a, **_k):
        return self

    def delete(self):
        self._op = "delete"
        return self

    def execute(self) -> _Res:
        if self._op == "delete":
            apagada = self.fila.pop(0)
            return _Res([apagada])
        return _Res([dict(r) for r in self.fila])


def test_sem_a_migration_o_pop_cai_no_caminho_antigo(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cliente = _FakeSemFuncao()
    with caplog.at_level("WARNING"):
        cmd = cq._pop_from_supabase(cliente, "SRV01")
    assert cmd is not None and cmd.id == "cmd-1"
    assert cliente.fila == [], "o caminho antigo tinha de consumir a linha"
    assert any("20260902110000" in m for m in caplog.messages), (
        "o aviso precisa apontar a migration que falta"
    )
