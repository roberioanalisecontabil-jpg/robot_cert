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


def test_paginacao_traz_total_como_no_inicio(client: TestClient, banco) -> None:
    # Barra numerada igual à do Início: precisa do total, não só de "tem mais".
    banco.tabelas["uso_certificado"] += [_uso("u-fis", DOC_A) for _ in range(60)]
    j = _get(client, ADMIN, "&por_pagina=25&pagina=3").json()
    assert (j["total_itens"], j["total_paginas"], j["pagina"]) == (63, 3, 3)
    assert len(j["linhas"]) == 13 and j["tem_mais"] is False
    assert _get(client, ADMIN, "&por_pagina=500").status_code == 422


def test_aba_uso_existe_e_abre_pelo_link(client: TestClient) -> None:
    html = client.get("/carteiras?aba=uso").text
    assert 'id="sec-uso"' in html and "/static/carteiras-uso.js" in html
    assert re.search(r'data-aba="uso" aria-selected="true"', html)
    assert re.search(r'data-aba="pessoas" aria-selected="false"', html)


def test_js_nunca_monta_html_com_dado_da_estacao() -> None:
    assert "innerHTML" not in JS.read_text(encoding="utf-8")


def test_js_mostra_sistema_e_abre_detalhe() -> None:
    js = JS.read_text(encoding="utf-8")
    assert "mostra_sistema" in js and "/janelas" in js and "modalUsoJanelas" in js
    assert "innerHTML" not in js and "cg-uso-futuro" not in js


def test_modal_tem_o_aviso() -> None:
    html = (RAIZ / "templates" / "carteiras.html").read_text(encoding="utf-8")
    assert "É a janela que estava na tela no momento do uso. Um programa em segundo plano não aparece aqui." in html
    assert 'id="modalUsoJanelas"' in html and 'id="uso-th-sistema"' in html


def test_cache_buster_do_js_subiu() -> None:
    html = (RAIZ / "templates" / "carteiras.html").read_text(encoding="utf-8")
    assert "carteiras-uso.js?v=janelas-2026-11-18" in html


def _janela(uso_id, record_id, ordem, programa, titulo) -> dict:
    return {"uso_id": uso_id, "machine_id": "m1", "record_id": record_id, "ordem": ordem,
            "quando": HORA, "programa": programa, "titulo": titulo}


@pytest.fixture
def com_janelas(banco):
    banco.tabelas["uso_certificado"] = [_uso("u-fis", DOC_A, id=1), _uso("u-fis", DOC_A, id=2),
                                        _uso("u-fis", DOC_A, id=3)]
    banco.tabelas["uso_janela"] = [
        _janela(1, 10, 0, "chrome.exe", "Portal A"),
        _janela(1, 12, 0, "outlook.exe", "Caixa"),   # maior record_id: dá o `sistema`
        _janela(1, 12, 1, "chrome.exe", "Antes"),    # ordem 1 não conta
        _janela(1, 11, 0, "chrome.exe", "Portal A"), # par repetido não soma
        _janela(2, 20, 0, "chrome.exe", "Portal B"),
    ]
    return banco


def test_admin_recebe_sistema_e_outras(client: TestClient, com_janelas) -> None:
    j = _get(client, ADMIN).json()
    assert j["mostra_sistema"] is True
    por_id = {l["id"]: l for l in j["linhas"]}
    assert por_id[1]["sistema"] == "outlook.exe · Caixa" and por_id[1]["outras"] == 1
    assert por_id[2]["sistema"] == "chrome.exe · Portal B" and por_id[2]["outras"] == 0


def test_linha_sem_janela_sai_vazia(client: TestClient, com_janelas) -> None:
    l3 = {l["id"]: l for l in _get(client, ADMIN).json()["linhas"]}[3]
    assert l3["sistema"] == "" and l3["outras"] == 0


def test_gestor_nao_recebe_janela_nem_id(client: TestClient, com_janelas) -> None:
    j = _get(client, GESTOR).json()
    assert j["mostra_sistema"] is False and j["linhas"]
    assert all(not ({"id", "sistema", "outras"} & set(l)) for l in j["linhas"])


def test_detalhe_so_admin(client: TestClient, com_janelas) -> None:
    assert client.get("/api/carteira/uso/1/janelas", headers=_h(*GESTOR)).status_code == 403
    assert client.get("/api/carteira/uso/1/janelas", headers=_h(*FISCAL_OP)).status_code == 403
    r = client.get("/api/carteira/uso/1/janelas", headers=_h(*ADMIN))
    assert r.status_code == 200
    usos = r.json()["usos"]
    assert [u["record_id"] for u in usos] == [10, 11, 12]
    assert [(w["ordem"], w["programa"], w["titulo"]) for w in usos[2]["janelas"]] == [
        (0, "outlook.exe", "Caixa"), (1, "chrome.exe", "Antes")]
    assert usos[0]["janelas"][0]["quando"] == HORA


def test_detalhe_inexistente_404(client: TestClient, com_janelas) -> None:
    assert client.get("/api/carteira/uso/999/janelas", headers=_h(*ADMIN)).status_code == 404


def test_detalhe_com_banco_fora_503(client: TestClient, com_janelas, monkeypatch) -> None:
    original = com_janelas.table

    def _quebra(nome, *a, **k):
        if nome == "uso_janela":  # a sessão usa o mesmo banco; só a leitura das janelas cai
            raise RuntimeError("fora")
        return original(nome, *a, **k)
    monkeypatch.setattr(com_janelas, "table", _quebra)
    r = client.get("/api/carteira/uso/1/janelas", headers=_h(*ADMIN))
    assert r.status_code == 503 and "uso" in r.json()["detail"].lower()


def test_paginas_com_a_mesma_hora_nao_repetem_nem_perdem_linhas(client: TestClient, banco) -> None:
    # hora é balde de uma hora: empate é a regra, e o desempate pelo id mantém as páginas disjuntas.
    banco.tabelas["uso_certificado"] = [_uso("u-fis", DOC_A, id=i, quantidade=i) for i in range(1, 76)]
    ids = []
    for p in (1, 2):
        j = _get(client, ADMIN, f"&pagina={p}").json()
        ids += [l["quantidade"] for l in j["linhas"]]
    assert sorted(ids) == list(range(1, 76))  # sem repetir nem perder
    assert ids[:3] == [75, 74, 73]
