"""Aba Certificados da Carteira: um documento, muitas pessoas (13/11/2026)."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from tests.test_pagina_carteiras import ADMIN, DOC_A, DOC_B, GESTOR, _Fake, _h, banco, banco_base  # noqa: F401
from tests.test_seguranca_lote4 import DOC_C


def _pessoas(client, quem, doc):
    r = client.get(f"/api/carteira/certificados/{doc}", headers=_h(*quem))
    assert r.status_code == 200, r.text
    return r.json()


def test_rota_certificados_nao_e_capturada_por_user_id(client: TestClient, banco: _Fake) -> None:
    r = client.get("/api/carteira/certificados", headers=_h(*ADMIN))
    assert r.status_code == 200 and "certificados" in r.json()


def test_lista_do_gestor_e_o_alcance_dele(client: TestClient, banco: _Fake) -> None:
    # Fora do alcance do gestor: DOC_B some da lista dele, nao da do admin.
    client.delete(f"/api/carteira/u-lf/{DOC_B}", headers=_h(*ADMIN))
    docs = lambda quem: {c["documento"] for c in client.get("/api/carteira/certificados", headers=_h(*quem)).json()["certificados"]}  # noqa: E731
    assert DOC_B not in docs(GESTOR) and DOC_B in docs(ADMIN)
    c = {c["documento"]: c for c in client.get("/api/carteira/certificados", headers=_h(*ADMIN)).json()["certificados"]}[DOC_A]
    assert c["tipo"] == "e-CNPJ" and c["pessoas"] == 1 and c["documento_formatado"] != DOC_A
    r = client.get("/api/carteira/certificados?q=alfa", headers=_h(*ADMIN)).json()
    assert [x["documento"] for x in r["certificados"]] == [DOC_A]


def test_detalhe_mostra_so_quem_ele_gere(client: TestClient, banco: _Fake) -> None:
    banco.tabelas["carteira"].append({"user_id": "u-sol", "documento": DOC_A})  # sem departamento
    assert {p["user_id"] for p in _pessoas(client, GESTOR, DOC_A)["pessoas"]} == {"u-fis"}
    assert {p["user_id"] for p in _pessoas(client, ADMIN, DOC_A)["pessoas"]} == {"u-fis", "u-sol"}


def test_detalhe_de_documento_fora_do_alcance_e_403(client: TestClient, banco: _Fake) -> None:
    client.delete(f"/api/carteira/u-lf/{DOC_B}", headers=_h(*ADMIN))
    assert client.get(f"/api/carteira/certificados/{DOC_B}", headers=_h(*GESTOR)).status_code == 403


def test_detalhe_traz_prazo_e_inicio_futuro(client: TestClient, banco: _Fake) -> None:
    futuro = (date.today() + timedelta(days=5)).isoformat()
    banco.tabelas["carteira"][0].update(valido_desde=futuro, valido_ate=None)
    p = _pessoas(client, ADMIN, DOC_A)["pessoas"][0]
    assert p["valido_desde"] == futuro and p["vigente"] is False
    assert client.get("/api/carteira/certificados", headers=_h(*ADMIN)).json()["certificados"][0]["pessoas"] == 0


def test_incluir_lote_com_prazo(client: TestClient, banco: _Fake) -> None:
    ate = (date.today() + timedelta(days=30)).isoformat()
    r = client.post(f"/api/carteira/certificados/{DOC_C}/pessoas", json={"user_ids": ["u-fis", "u-con"], "valido_ate": ate}, headers=_h(*ADMIN))
    assert r.status_code == 200 and r.json()["gravados"] == 2, r.text
    novas = [l for l in banco.tabelas["carteira"] if l["documento"] == DOC_C]
    assert {l["user_id"] for l in novas} == {"u-fis", "u-con"} and all(l["valido_ate"] == ate for l in novas)
    assert len([h for h in banco.tabelas["carteira_historico"] if h["documento"] == DOC_C]) == 2


def test_lote_com_pessoa_fora_do_alcance_nao_grava_nada(client: TestClient, banco: _Fake) -> None:
    antes = [dict(l) for l in banco.tabelas["carteira"]]
    # u-fis e do Fiscal (gestor alcanca); u-con e do Contabil (nao alcanca).
    r = client.post(f"/api/carteira/certificados/{DOC_C}/pessoas", json={"user_ids": ["u-fis", "u-con"]}, headers=_h(*GESTOR))
    assert r.status_code == 403, r.text
    assert banco.tabelas["carteira"] == antes
    assert not banco.tabelas.get("carteira_historico")


def test_prazo_de_701_dias_e_400(client: TestClient, banco: _Fake) -> None:
    ate = (date.today() + timedelta(days=701)).isoformat()
    r = client.post(f"/api/carteira/certificados/{DOC_C}/pessoas", json={"user_ids": ["u-fis"], "valido_ate": ate}, headers=_h(*ADMIN))
    assert r.status_code == 400, r.text
    assert not [l for l in banco.tabelas["carteira"] if l["documento"] == DOC_C]




def test_vencimentos_por_documento_pega_o_maior(banco: _Fake) -> None:
    from app import cert_installer as ci

    banco.tabelas["cert_pfx_store"] += [
        {"id": "x1", "documento": DOC_A, "not_after": "2027-01-01T00:00:00+00:00"},
        {"id": "x2", "documento": DOC_A, "not_after": "2026-06-01T00:00:00+00:00"},
    ]
    assert ci.vencimentos_por_documento()[DOC_A] == "2027-01-01T00:00:00+00:00"


def test_lote_com_id_inexistente_nao_grava_nada(client: TestClient, banco: _Fake) -> None:
    antes = [dict(l) for l in banco.tabelas["carteira"]]
    r = client.post(f"/api/carteira/certificados/{DOC_C}/pessoas", json={"user_ids": ["u-fis", "nao-existe"]}, headers=_h(*ADMIN))
    assert r.status_code == 404, r.text
    assert banco.tabelas["carteira"] == antes
    assert not banco.tabelas.get("carteira_historico")


def test_lote_acima_de_200_ids_e_422(client: TestClient, banco: _Fake) -> None:
    r = client.post(f"/api/carteira/certificados/{DOC_C}/pessoas", json={"user_ids": [f"u{i}" for i in range(201)]}, headers=_h(*ADMIN))
    assert r.status_code == 422, r.text


def test_inicio_no_futuro_queima_tokens_pendentes(client: TestClient, banco: _Fake, monkeypatch) -> None:
    from app import cert_installer
    chamadas: list = []
    monkeypatch.setattr(cert_installer, "revogar_tokens_pendentes", lambda uid: chamadas.append(uid) or 0)
    futuro = (date.today() + timedelta(days=5)).isoformat()
    r = client.post(f"/api/carteira/certificados/{DOC_C}/pessoas", json={"user_ids": ["u-fis"], "valido_desde": futuro}, headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert chamadas == ["u-fis"]
    chamadas.clear()
    r = client.post(f"/api/carteira/certificados/{DOC_C}/pessoas", json={"user_ids": ["u-fis"]}, headers=_h(*ADMIN))
    assert r.status_code == 200 and chamadas == []
