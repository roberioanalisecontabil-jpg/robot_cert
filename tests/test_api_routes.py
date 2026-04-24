"""Testes de integração HTTP (FastAPI TestClient)."""

import pytest
from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    j = r.json()
    assert j.get("ok") is True
    assert "supabase" in j
    assert "api_key_required" in j


def test_pagina_painel_200(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "Certificados" in r.text
    assert "configuracao" in r.text


def test_pagina_config_200(client: TestClient) -> None:
    r = client.get("/configuracao")
    assert r.status_code == 200
    assert "Chave API" in r.text
    assert "Origem (.pfx)" in r.text


def test_pagina_historico_200(client: TestClient) -> None:
    r = client.get("/historico")
    assert r.status_code == 200
    assert "Histórico de Certificados" in r.text


def test_pagina_vencidos_200(client: TestClient) -> None:
    r = client.get("/vencidos")
    assert r.status_code == 200
    assert "Certificados Vencidos" in r.text


def test_api_settings_sem_chave_200(client: TestClient) -> None:
    """Sem API_KEY no servidor, /api/settings deve ser acessível."""
    r = client.get("/api/settings")
    assert r.status_code == 200
    j = r.json()
    assert "source_folder" in j
    assert "effective_source" in j


def test_api_settings_401_se_chave_errada(
    client_com_chave: TestClient, api_key: str
) -> None:
    r = client_com_chave.get("/api/settings", headers={"X-API-Key": "chave-errada"})
    assert r.status_code == 401


def test_api_settings_200_com_chave_correta(
    client_com_chave: TestClient, api_key: str
) -> None:
    r = client_com_chave.get(
        "/api/settings", headers={"X-API-Key": api_key}
    )
    assert r.status_code == 200


def test_certificados_local_200(
    client_com_chave: TestClient, api_key: str
) -> None:
    h = {"X-API-Key": api_key}
    r = client_com_chave.get(
        "/api/certificados?fonte=local", headers=h
    )
    assert r.status_code == 200
    j = r.json()
    assert "itens" in j
    assert isinstance(j["itens"], list)
    assert j.get("data_source") in ("local", "remoto")


def test_historico_certificados_200(
    client_com_chave: TestClient, api_key: str
) -> None:
    h = {"X-API-Key": api_key}
    r = client_com_chave.get("/api/certificados/historico", headers=h)
    assert r.status_code == 200
    j = r.json()
    assert "itens" in j
    assert "total" in j
    assert "snapshots_lidos" in j


def test_vencidos_certificados_200(
    client_com_chave: TestClient, api_key: str
) -> None:
    h = {"X-API-Key": api_key}
    r = client_com_chave.get("/api/certificados/vencidos", headers=h)
    assert r.status_code == 200
    j = r.json()
    assert "itens" in j
    assert "total" in j
    assert "snapshots_lidos" in j


def test_fila_comando_ping(
    client_com_chave: TestClient, api_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Enfileirar, consumir e esvaziar a fila (só ficheiro, sem Supabase)."""
    from app import command_queue

    import tempfile
    from pathlib import Path

    monkeypatch.setattr(command_queue, "_supabase", lambda: None)

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "queue.json"
        monkeypatch.setattr(command_queue, "QUEUE_FILE", p)

        h = {"X-API-Key": api_key}
        en = client_com_chave.post(
            "/api/agent/commands",
            json={"machine_id": "default", "command": "ping"},
            headers=h,
        )
        assert en.status_code == 200
        assert en.json().get("ok") is True

        n1 = client_com_chave.get(
            "/api/agent/next?machine_id=default", headers=h
        )
        assert n1.status_code == 200
        assert n1.json().get("command") == "ping"

        n2 = client_com_chave.get(
            "/api/agent/next?machine_id=default", headers=h
        )
        assert n2.status_code == 200
        assert n2.json().get("command") is None
