"""Paginação por OFFSET com desempate (revisão de 21/11/2026, P3-1 e P8-2).

Todas as linhas de uma varredura têm o mesmo `ultima_data_registrada`, e a
remoção grava o mesmo `atualizado_em` em todas as linhas da estação. Ordenar só
por essas colunas deixa o Postgres devolver os empates em qualquer ordem a cada
página: linhas se repetem e somem entre páginas (e na exportação em lotes).

O banco falso ordena de forma estável e não reproduz o sintoma, então estes
testes conferem as chaves de ordenação que cada consulta pede."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.test_seguranca_lote1 import _Query
from tests.test_seguranca_lote4 import ADMIN, AGORA, DOC_A, _h
from tests.test_seguranca_lote4 import banco  # noqa: F401


@pytest.fixture
def ordens(monkeypatch):
    """(tabela, [(coluna, desc), ...]) de cada consulta que ordenou."""
    vistas: list = []
    original = _Query.execute

    def execute(self):
        if self._order:
            vistas.append((getattr(self, "_t", None) or getattr(self, "_tabela", None), list(self._order)))
        return original(self)

    monkeypatch.setattr(_Query, "execute", execute)
    return vistas


def _historico(banco) -> None:
    banco.tabelas["cert_history"] += [
        {"arquivo_chave": str(i) * 64, "nome_publico": f"N{i}_{DOC_A}", "nome": f"N{i}", "documento": DOC_A,
         "status_ultimo": "ok", "vencimento_certificado": None, "ultima_data_registrada": AGORA.isoformat()}
        for i in range(1, 4)
    ]


def _chaves_cert_history(ordens) -> list:
    return [o for _t, o in ordens if o and o[0] == ("ultima_data_registrada", True)]


def test_historico_paginado_desempata_pela_chave(client: TestClient, banco, ordens) -> None:
    _historico(banco)
    r = client.get("/api/certificados/historico?pagina=1&por_pagina=2", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert _chaves_cert_history(ordens) and all(
        o == [("ultima_data_registrada", True), ("arquivo_chave", False)] for o in _chaves_cert_history(ordens))


def test_historico_em_lotes_desempata_pela_chave(client: TestClient, banco, ordens) -> None:
    _historico(banco)
    r = client.get("/api/certificados/historico?todas_filtradas=true", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert _chaves_cert_history(ordens) and all(
        o == [("ultima_data_registrada", True), ("arquivo_chave", False)] for o in _chaves_cert_history(ordens))


def test_relatorio_de_remocao_desempata_pelo_id(client: TestClient, banco, ordens) -> None:
    banco.tabelas["remocao_estacao"] = [
        {"id": i, "machine_id": "m", "usuario_windows": "w", "user_id": None, "fingerprint": str(i) * 64,
         "documento": DOC_A, "estado": "removeria", "atualizado_em": "2026-11-14T10:00:00+00:00"}
        for i in range(1, 4)
    ]
    r = client.get("/api/remocao", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    rel = [o for _t, o in ordens if o and o[0] == ("atualizado_em", True)]
    assert rel == [[("atualizado_em", True), ("id", True)]]
