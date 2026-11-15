"""Aba Uso em Carteiras e a rota que a alimenta (Frente C, Task 6)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_seguranca_lote4 import ADMIN, FISCAL, GESTOR, SOLTO, FISCAL_OP, DOC_A, DOC_B, _h
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401

RAIZ = Path(__file__).resolve().parents[1]
JS = RAIZ / "static" / "carteiras-uso.js"
HORA = datetime(2026, 11, 15, 15, 0, tzinfo=timezone.utc).isoformat()


def _uso(uid, doc, maquina="m1", fp="a" * 64, **extra) -> dict:
    return {"machine_id": maquina, "sid": "S-1", "usuario_windows": "win", "conteiner": "c", "hora": HORA,
            "primeiro_em": HORA, "ultimo_em": HORA, "quantidade": 2, "ultimo_record": 1,
            "fingerprint": fp, "documento": doc, "user_id": uid, **extra}


@pytest.fixture
def banco(banco_base):  # noqa: F811
    banco_base.tabelas["uso_certificado"] = [
        _uso("u-fis", DOC_A),
        _uso("u-sol", DOC_B),          # fora do departamento do gestor
        _uso(None, DOC_A, usuario_windows="perfil"),  # sem login
        _uso("u-fis", DOC_A, fp=None, documento=None),  # pendente
    ]
    banco_base.tabelas["uso_coleta"] = [{"machine_id": "m1", "ultima_em": HORA, "auditoria": "desligada"}]
    banco_base.tabelas["agent_devices"] = [{"machine_id": "m1", "nome": "PC-FISCAL", "visto_em": HORA}]
    return banco_base


def _get(client, quem, qs=""):
    return client.get("/api/carteira/uso?desde=2026-11-01" + qs, headers=_h(*quem))


def test_admin_ve_tudo_inclusive_sem_login(client: TestClient, banco) -> None:
    j = _get(client, ADMIN).json()
    assert len(j["linhas"]) == 3
    sem = [l for l in j["linhas"] if l["sem_login"]]
    assert len(sem) == 1 and sem[0]["usuario_windows"] == "perfil"
    por_pessoa = [l for l in j["linhas"] if not l["sem_login"] and l["email"] == "fis@x.com"]
    assert por_pessoa[0]["nome_maquina"] == "PC-FISCAL" and por_pessoa[0]["titular"] == "ALFA"
    assert j["coletas"]["m1"]["auditoria"] == "desligada"


def test_gestor_so_ve_os_departamentos_dele(client: TestClient, banco) -> None:
    j = _get(client, GESTOR).json()
    assert [l["email"] for l in j["linhas"]] == ["fis@x.com"]
    assert not any(l["sem_login"] for l in j["linhas"])


def test_gestor_com_user_id_de_fora_recebe_vazio(client: TestClient, banco) -> None:
    r = _get(client, GESTOR, "&user_id=u-sol")
    assert r.status_code == 200 and r.json()["linhas"] == []


def test_operador_recebe_403(client: TestClient, banco) -> None:
    assert _get(client, FISCAL_OP).status_code == 403
    assert _get(client, SOLTO).status_code == 403


def test_pendente_nao_aparece(client: TestClient, banco) -> None:
    assert all(l["documento"] for l in _get(client, ADMIN).json()["linhas"])


def test_filtros_e_paginacao(client: TestClient, banco) -> None:
    assert len(_get(client, ADMIN, "&documento=" + DOC_B).json()["linhas"]) == 1
    assert _get(client, ADMIN, "&desde=2026-11-16").json()["linhas"] == []
    banco.tabelas["uso_certificado"] += [_uso("u-fis", DOC_A) for _ in range(60)]
    j = _get(client, ADMIN).json()
    assert len(j["linhas"]) == 50 and j["tem_mais"] is True
    assert _get(client, ADMIN, "&pagina=2").json()["tem_mais"] is False


def test_aba_uso_existe_e_abre_pelo_link(client: TestClient) -> None:
    html = client.get("/carteiras?aba=uso").text
    assert 'id="sec-uso"' in html and "/static/carteiras-uso.js" in html
    assert re.search(r'data-aba="uso" aria-selected="true"', html)
    assert re.search(r'data-aba="pessoas" aria-selected="false"', html)


def test_js_nunca_monta_html_com_dado_da_estacao() -> None:
    assert "innerHTML" not in JS.read_text(encoding="utf-8")


def test_paginas_com_a_mesma_hora_nao_repetem_nem_perdem_linhas(client: TestClient, banco) -> None:
    # hora é balde de uma hora: empate é a regra, e o desempate pelo id mantém as páginas disjuntas.
    banco.tabelas["uso_certificado"] = [_uso("u-fis", DOC_A, id=i, quantidade=i) for i in range(1, 76)]
    ids = []
    for p in (1, 2):
        j = _get(client, ADMIN, f"&pagina={p}").json()
        ids += [l["quantidade"] for l in j["linhas"]]
    assert sorted(ids) == list(range(1, 76))  # sem repetir nem perder
    assert ids[:3] == [75, 74, 73]
