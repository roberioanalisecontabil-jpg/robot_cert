"""/api/certificados enxuta para chave de API, com filtros de documento e vencimento (25/11/2026)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.rotas import certificados as cert
from tests.test_api_chaves import _criar, _k
from tests.test_seguranca_lote4 import ADMIN, _h, banco  # noqa: F401

AGORA = datetime.now(timezone.utc)


def _item(nome, doc, tipo, dias, status="ok"):
    return {
        "nome": nome, "documento_numero": doc, "documento_tipo": tipo, "status": status,
        "not_before": (AGORA - timedelta(days=300)).isoformat(),
        "not_after": (AGORA + timedelta(days=dias, hours=12)).isoformat(),
        "fingerprint_sha256": doc.ljust(64, "0"), "issuer": "CN=AC TESTE", "emissor": "AC TESTE",
        "tipo_icp": "A1", "subject": "CN=" + nome,
    }


@pytest.fixture()
def snap(monkeypatch):
    itens = [
        _item("ALFA LTDA", "11222333000181", "cnpj", 10),
        _item("BETA LTDA", "44555666000199", "cnpj", 50),
        _item("CARLOS", "12345678909", "cpf", 200),
        _item("DELTA LTDA", "77888999000100", "cnpj", -5),
    ]
    monkeypatch.setattr(cert, "get_latest_snapshot", lambda *a, **k: {"items": itens, "scanned_at": AGORA.isoformat()})


def test_chave_de_api_recebe_o_enxuto(client: TestClient, banco, snap) -> None:
    r = client.get("/api/certificados", headers=_k(_criar(client, banco)))
    assert r.status_code == 200, r.text
    j = r.json()
    assert set(j["itens"][0]) == set(cert.CAMPOS_ENXUTOS)
    alfa = next(i for i in j["itens"] if i["nome"] == "ALFA LTDA")
    assert alfa["documento"] == "11222333000181" and alfa["status"] == "prestes_vencer"
    assert alfa["dias_para_vencer"] in (10, 11)
    assert next(i for i in j["itens"] if i["nome"] == "DELTA LTDA")["status"] == "vencido"
    assert "source_dir" not in j and "banco" not in j and j["paginacao"]["total_itens"] == 4


def test_tela_continua_com_o_item_completo(client: TestClient, banco, snap) -> None:
    j = client.get("/api/certificados?pagina=1&por_pagina=100", headers=_h(*ADMIN)).json()
    assert "subject" in j["itens"][0] and "_isExpiringSoon" in j["itens"][0] and "banco" in j


def test_campos_completo_e_lista(client: TestClient, banco, snap) -> None:
    k = _k(_criar(client, banco))
    assert "subject" in client.get("/api/certificados?campos=completo", headers=k).json()["itens"][0]
    it = client.get("/api/certificados?campos=nome,fingerprint_sha256,emitido_em", headers=k).json()["itens"][0]
    assert list(it) == ["nome", "fingerprint_sha256", "emitido_em"] and len(it["emitido_em"]) == 10
    r = client.get("/api/certificados?campos=nome,responsavel_cpf", headers=k)
    assert r.status_code == 422 and "responsavel_cpf" in r.json()["detail"]


@pytest.mark.parametrize("q,nomes", [
    ("documento=11.222.333/0001-81,123.456.789-09", {"ALFA LTDA", "CARLOS"}),
    ("documento_tipo=cpf", {"CARLOS"}),
    ("vence_em_dias=60", {"ALFA LTDA", "BETA LTDA"}),
    ("vence_de={d30}&vence_ate={d250}", {"BETA LTDA", "CARLOS"}),
    ("documento_tipo=cnpj&vence_em_dias=20", {"ALFA LTDA"}),
])
def test_filtros_novos(client: TestClient, banco, snap, q, nomes) -> None:
    hoje = AGORA.astimezone(timezone(timedelta(hours=-3))).date()
    q = q.format(d30=hoje + timedelta(days=30), d250=hoje + timedelta(days=250))
    j = client.get("/api/certificados?" + q, headers=_k(_criar(client, banco))).json()
    assert {i["nome"] for i in j["itens"]} == nomes
    assert j["resumo"]["total"] == len(nomes)


@pytest.mark.parametrize("q", ["documento=abc", "documento_tipo=mei", "vence_de=2027-01-02&vence_ate=2027-01-01", "vence_em_dias=-1"])
def test_filtro_invalido_e_422(client: TestClient, banco, snap, q) -> None:
    assert client.get("/api/certificados?" + q, headers=_h(*ADMIN)).status_code == 422


def test_so_pagina_tambem_filtra(client: TestClient, banco, snap) -> None:
    j = client.get("/api/certificados?pagina=1&documento_tipo=cpf", headers=_h(*ADMIN)).json()
    assert [i["nome"] for i in j["itens"]] == ["CARLOS"] and j["paginacao"]["por_pagina"] == 100
