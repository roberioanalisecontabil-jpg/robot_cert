"""De quem é esta chave: a estação descobre o `machine_id` que o portal conhece
(plano 2026-11-20-identidade-pela-chave, Task 1)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import computadores
from tests.test_computadores_rotas import PC_FIS, PC_SOL, _chave
from tests.test_computadores_rotas import banco  # noqa: F401
from tests.test_remocao_rotas import _fixar
from tests.test_seguranca_lote1 import _Fake
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401


def test_identidade_devolve_a_maquina_da_chave(client: TestClient, banco: _Fake) -> None:
    _fixar(banco, PC_SOL)
    r = client.post("/api/estacao/identidade", json={"chave": _chave(PC_SOL)})
    assert r.status_code == 200 and r.json() == {"machine_id": PC_SOL}


def test_identidade_chave_desconhecida_404(client: TestClient, banco: _Fake) -> None:
    _fixar(banco, PC_SOL)
    assert client.post("/api/estacao/identidade", json={"chave": "x" * 43}).status_code == 404


def test_identidade_chave_fora_do_formato_422(client: TestClient, banco: _Fake) -> None:
    assert client.post("/api/estacao/identidade", json={"chave": "curta"}).status_code == 422


def test_identidade_banco_fora_503(client: TestClient, banco: _Fake, monkeypatch) -> None:
    def _fora(_h):
        raise RuntimeError("banco fora")

    monkeypatch.setattr(computadores, "maquina_da_chave", _fora)
    assert client.post("/api/estacao/identidade", json={"chave": _chave(PC_SOL)}).status_code == 503


def test_chave_em_duas_maquinas_vale_a_mais_recente(banco: _Fake) -> None:
    h = computadores.hash_da_chave(_chave(PC_SOL))
    banco.tabelas[computadores.TABELA_CHAVE] = [
        {"machine_id": PC_FIS, "chave_hash": h, "fixada_em": "2026-10-01T12:00:00+00:00"},
        {"machine_id": PC_SOL.upper(), "chave_hash": h, "fixada_em": "2026-11-01T12:00:00+00:00"},
        {"machine_id": "aa:aa:aa:aa:aa:03", "chave_hash": "outra", "fixada_em": "2026-12-01T12:00:00+00:00"},
    ]
    assert computadores.maquina_da_chave(h) == PC_SOL
    assert computadores.maquina_da_chave("nenhuma") is None
