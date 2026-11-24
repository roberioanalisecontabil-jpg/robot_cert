"""Chave de API de leitura do administrador (24/11/2026)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_seguranca_lote1 import SENHA
from tests.test_seguranca_lote4 import ADMIN, FISCAL_OP, _h, banco  # noqa: F401


def _criar(client, banco, dias=30) -> str:
    r = client.post("/api/api-chaves", json={"nome": "Power BI", "dias": dias, "senha_atual": SENHA}, headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    return r.json()["segredo"]


def _k(segredo: str) -> dict:
    return {"Authorization": "Bearer " + segredo}


def test_cria_e_guarda_so_o_hash(client: TestClient, banco) -> None:
    segredo = _criar(client, banco)
    assert segredo.startswith("cg_ro_")
    linha = banco.tabelas["api_chaves"][0]
    assert linha["user_id"] == "u-adm" and segredo not in str(linha)
    lista = client.get("/api/api-chaves", headers=_h(*ADMIN)).json()["chaves"]
    assert lista[0]["dono"] == "admin@x.com" and "segredo_hash" not in lista[0]


def test_criar_pede_senha_e_admin(client: TestClient, banco) -> None:
    corpo = {"nome": "x", "dias": 30, "senha_atual": "errada"}
    assert client.post("/api/api-chaves", json=corpo, headers=_h(*ADMIN)).status_code == 400
    corpo["senha_atual"] = SENHA
    assert client.post("/api/api-chaves", json=corpo, headers=_h(*FISCAL_OP)).status_code == 403
    assert client.post("/api/api-chaves", json={**corpo, "dias": 400}, headers=_h(*ADMIN)).status_code == 422


def test_le_como_admin(client: TestClient, banco) -> None:
    k = _k(_criar(client, banco))
    assert client.get("/api/api-chaves", headers=k).status_code == 200
    assert client.get("/api/carteira/uso/resumo?desde=2026-11-14&ate=2026-11-16", headers=k).status_code == 200
    assert banco.tabelas["api_chaves"][0]["ultimo_uso_em"]


def test_nao_escreve_nem_alcanca_o_cofre(client: TestClient, banco) -> None:
    k = _k(_criar(client, banco))
    r = client.post("/api/api-chaves", json={"nome": "y", "dias": 1, "senha_atual": SENHA}, headers=k)
    assert r.status_code == 403 and "só lê" in r.json()["detail"]
    assert client.put("/api/settings", json={}, headers=k).status_code == 403
    # Rotas da máquina (cofre, fila do agente) recusam a chave mesmo em GET.
    assert client.get("/api/cert-installer/vault-optin", headers=k).status_code == 403
    assert client.get("/api/agent/next?machine_id=srv", headers=k).status_code == 403


def test_revogada_vencida_ou_falsa_recusa(client: TestClient, banco) -> None:
    segredo = _criar(client, banco)
    linha = banco.tabelas["api_chaves"][0]
    assert client.get("/api/api-chaves", headers=_k(segredo + "x")).status_code == 401
    linha["expira_em"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    assert client.get("/api/api-chaves", headers=_k(segredo)).status_code == 401
    linha["expira_em"] = None
    assert client.post(f"/api/api-chaves/{linha['id']}/revogar", headers=_h(*ADMIN)).status_code == 200
    assert client.get("/api/api-chaves", headers=_k(segredo)).status_code == 401


def test_dono_rebaixado_ou_desativado_derruba_a_chave(client: TestClient, banco) -> None:
    k = _k(_criar(client, banco))
    adm = next(u for u in banco.tabelas["users"] if u["id"] == "u-adm")
    adm["role"] = "user"
    assert client.get("/api/api-chaves", headers=k).status_code == 401
    adm.update(role="admin", ativo=False)
    assert client.get("/api/api-chaves", headers=k).status_code == 401


def test_migration_api_chaves() -> None:
    sql = Path(__file__).resolve().parent.parent / "supabase" / "migrations" / "20261124150000_api_chaves.sql"
    bruto = sql.read_text(encoding="utf-8")
    s = re.sub(r"\s+", " ", "\n".join(l for l in bruto.splitlines() if not l.lstrip().startswith("--")))
    assert "CREATE TABLE IF NOT EXISTS public.api_chaves" in s
    assert "segredo_hash text NOT NULL UNIQUE" in s
    assert "user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE" in s
    assert "NAO rode a mao" in bruto and bruto.isascii()
    assert not re.search(r"^\s*(BEGIN|COMMIT)\s*;", bruto, re.M)


def test_aba_chaves_de_api_na_configuracao() -> None:
    raiz = Path(__file__).resolve().parent.parent
    html = (raiz / "templates" / "configuracao.html").read_text(encoding="utf-8")
    assert 'id="tab-api"' in html and 'id="sec-api"' in html and 'api: "sec-api"' in html
    assert "/static/configuracao-api.js?v=" in html
    js = (raiz / "static" / "configuracao-api.js").read_text(encoding="utf-8")
    # A tabela mostra dados do banco: só textContent, nunca HTML em texto.
    assert "innerHTML" not in js and "window.carregarApiChaves" in js
