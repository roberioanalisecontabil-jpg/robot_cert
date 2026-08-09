"""Disparo agendado dos alertas — GET /api/cron/alerts.

A rota existe porque o laço do `lifespan` não roda em serverless: no Vercel
cada requisição instancia a função e a encerra, então o `asyncio.create_task`
morre antes dos 60s do primeiro disparo. No Render, com processo vivo, o laço
bastava. Foi por isso que os alertas ficaram configurados e sem enviar nada até
alguém clicar em "Disparar Alertas Agora".

O que faz esta rota merecer teste caprichado é o que ela dispara: varredura
completa e envio de e-mail para todos os destinatários. Uma falha de
autenticação aqui não é "acesso indevido a dados" — é qualquer um na internet
conseguindo disparar e-mail em massa em nome do portal, quantas vezes quiser.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

SEGREDO = "segredo-de-teste-do-cron"


@pytest.fixture
def com_segredo(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("CRON_SECRET", SEGREDO)
    return SEGREDO


def test_dispara_com_o_segredo_correto(client: TestClient, com_segredo: str) -> None:
    with patch("app.main.trigger_all_alerts", lambda: {"enviados": 3}) as _:
        r = client.get(
            "/api/cron/alerts",
            headers={"Authorization": f"Bearer {com_segredo}"},
        )

    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert r.json()["stats"] == {"enviados": 3}


def test_sem_authorization_recusa(client: TestClient, com_segredo: str) -> None:
    chamou = []
    with patch("app.main.trigger_all_alerts", lambda: chamou.append(1)):
        r = client.get("/api/cron/alerts")

    assert r.status_code == 401
    assert not chamou, "não pode disparar envio sem credencial"


def test_segredo_errado_recusa(client: TestClient, com_segredo: str) -> None:
    chamou = []
    with patch("app.main.trigger_all_alerts", lambda: chamou.append(1)):
        r = client.get(
            "/api/cron/alerts",
            headers={"Authorization": "Bearer segredo-errado"},
        )

    assert r.status_code == 401
    assert not chamou


def test_sem_prefixo_bearer_recusa(client: TestClient, com_segredo: str) -> None:
    """O segredo cru, sem "Bearer ", não pode passar."""
    chamou = []
    with patch("app.main.trigger_all_alerts", lambda: chamou.append(1)):
        r = client.get("/api/cron/alerts", headers={"Authorization": com_segredo})

    assert r.status_code == 401
    assert not chamou


def test_sem_cron_secret_configurada_falha_fechada(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    O ponto mais importante do arquivo.

    Se a variável não estiver definida, a tentação é tratar como "sem
    autenticação exigida" e deixar passar. Isso deixaria a rota aberta a quem
    descobrisse a URL — e ela dispara e-mail em massa. Tem de recusar.
    """
    monkeypatch.delenv("CRON_SECRET", raising=False)

    chamou = []
    with patch("app.main.trigger_all_alerts", lambda: chamou.append(1)):
        r = client.get("/api/cron/alerts", headers={"Authorization": "Bearer qualquer"})

    assert r.status_code == 503
    assert not chamou, "sem segredo configurado, nada pode ser disparado"


def test_cron_secret_vazia_tambem_falha_fechada(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Variável definida como string vazia é o mesmo que ausente."""
    monkeypatch.setenv("CRON_SECRET", "   ")

    chamou = []
    with patch("app.main.trigger_all_alerts", lambda: chamou.append(1)):
        r = client.get("/api/cron/alerts", headers={"Authorization": "Bearer    "})

    assert r.status_code == 503
    assert not chamou


def test_erro_na_varredura_vira_500(client: TestClient, com_segredo: str) -> None:
    def explode():
        raise RuntimeError("falha ao varrer certificados")

    with patch("app.main.trigger_all_alerts", explode):
        r = client.get(
            "/api/cron/alerts",
            headers={"Authorization": f"Bearer {com_segredo}"},
        )

    assert r.status_code == 500
    assert "falha ao varrer" in r.json()["detail"]


def test_rota_declarada_no_vercel_json_existe_no_app() -> None:
    """
    O agendamento e a rota moram em arquivos diferentes: renomear uma sem a
    outra faz o cron chamar 404 todo dia, em silêncio — o Vercel não avisa.
    """
    import json
    from pathlib import Path

    from app.main import app

    vercel = json.loads(
        (Path(__file__).resolve().parent.parent / "vercel.json").read_text(encoding="utf-8")
    )
    crons = vercel.get("crons") or []
    assert crons, "vercel.json sem entrada de cron — os alertas não disparam sozinhos"

    rotas = {r.path for r in app.routes if hasattr(r, "path")}
    for c in crons:
        assert c["path"] in rotas, f"cron aponta para {c['path']}, que não existe no app"
