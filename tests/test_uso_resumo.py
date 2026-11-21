"""Aba Uso, visão por certificado (proposta B, 21/11/2026): a rota que soma o
período para a lista de certificados, o gráfico por dia e "Quem usou"."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_seguranca_lote4 import ADMIN, GESTOR, FISCAL_OP, DOC_A, DOC_B, _h
from tests.test_uso_tela import _uso, banco  # noqa: F401
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401


def _get(client, quem, qs=""):
    return client.get("/api/carteira/uso/resumo?desde=2026-11-14&ate=2026-11-16" + qs, headers=_h(*quem))


def test_lista_soma_por_certificado_do_mais_usado(client: TestClient, banco) -> None:
    j = _get(client, ADMIN).json()
    assert [(c["documento"], c["usos"], c["pessoas"]) for c in j["certificados"]] == [(DOC_A, 4, 2), (DOC_B, 2, 1)]
    assert j["certificados"][0]["titular"] == "ALFA" and j["certificados"][0]["ultimo_em"]
    assert j["detalhe"] is None


def test_detalhe_do_certificado(client: TestClient, banco) -> None:
    d = _get(client, ADMIN, "&documento=" + DOC_A).json()["detalhe"]
    assert (d["documento"], d["titular"], d["usos"], d["pessoas"], d["maquinas"]) == (DOC_A, "ALFA", 4, 2, 1)
    # 15/11 15:00 UTC é 12:00 em Brasília: cai no dia 15, e os dias sem uso vêm com 0.
    assert d["por_dia"] == [{"dia": "2026-11-14", "usos": 0}, {"dia": "2026-11-15", "usos": 4},
                            {"dia": "2026-11-16", "usos": 0}]
    pessoa = client.get("/api/carteira/uso?desde=2026-11-01&documento=" + DOC_A + "&user_id=u-fis",
                        headers=_h(*ADMIN)).json()["linhas"][0]["pessoa"]
    assert sorted((q["nome"], q["usos"], q["sem_login"]) for q in d["quem"]) == sorted(
        [(pessoa, 2, False), ("perfil", 2, True)])


def test_gestor_so_soma_os_departamentos_dele(client: TestClient, banco) -> None:
    j = _get(client, GESTOR).json()
    assert [(c["documento"], c["usos"], c["pessoas"]) for c in j["certificados"]] == [(DOC_A, 2, 1)]
    assert _get(client, GESTOR, "&documento=" + DOC_B).json()["detalhe"] is None
    assert _get(client, GESTOR, "&user_id=u-sol").json()["certificados"] == []


def test_filtro_de_pessoa_e_operador_403(client: TestClient, banco) -> None:
    j = _get(client, ADMIN, "&user_id=u-sol").json()
    assert [c["documento"] for c in j["certificados"]] == [DOC_B]
    assert _get(client, FISCAL_OP).status_code == 403


def test_passa_de_mil_linhas(client: TestClient, banco, monkeypatch) -> None:
    # PostgREST corta em 1000 em silêncio: a soma tem que ler tudo.
    from tests.test_seguranca_lote1 import _Query

    original = _Query.execute

    def cortado(self):
        r = original(self)
        r.data = (r.data or [])[:1000] if isinstance(r.data, list) else r.data
        return r

    monkeypatch.setattr(_Query, "execute", cortado)
    banco.tabelas["uso_certificado"] += [_uso("u-fis", DOC_A, quantidade=1, id=i) for i in range(1500)]
    assert _get(client, ADMIN).json()["certificados"][0]["usos"] == 1504
