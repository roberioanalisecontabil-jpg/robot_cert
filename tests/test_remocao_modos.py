"""As duas chaves de modo da remocao nas estacoes (Frente B, 14/11/2026)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.rotas.configuracao as cfg
from app import remocao
from tests.test_seguranca_lote1 import _Fake
from tests.test_seguranca_lote4 import ADMIN, _h
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401


@pytest.fixture
def banco(banco_base: _Fake, monkeypatch: pytest.MonkeyPatch, tmp_path) -> _Fake:
    # Arquivo local isolado: o PUT grava nele e a leitura cai nele sem linha no banco.
    monkeypatch.setattr("app.settings_state.DATA_FILE", tmp_path / "portal_settings.json")
    banco_base.tabelas["portal_settings"] = []
    return banco_base


def test_vazio_vale_relatorio(banco: _Fake) -> None:
    assert remocao.modo_carteira() == "relatorio"
    assert remocao.modo_sem_login() == "relatorio"
    s = {"remocao_carteira_modo": "", "remocao_sem_login_modo": "valor-velho"}
    banco.tabelas["portal_settings"] = [{"id": 1, **s}]
    assert remocao.modo_carteira() == "relatorio"
    assert remocao.modo_sem_login() == "relatorio"


def test_put_grava_e_get_devolve(client: TestClient, banco: _Fake) -> None:
    base = cfg.SettingsBody().model_dump()
    r = client.put("/api/settings", headers=_h(*ADMIN), json={
        **base, "remocao_carteira_modo": "ligado", "remocao_sem_login_modo": "desligado",
    })
    assert r.status_code == 200, r.text
    j = client.get("/api/settings", headers=_h(*ADMIN)).json()
    assert j["remocao_carteira_modo"] == "ligado" and j["remocao_sem_login_modo"] == "desligado"
    assert remocao.modo_carteira() == "ligado" and remocao.modo_sem_login() == "desligado"


@pytest.mark.parametrize("campo", ["remocao_carteira_modo", "remocao_sem_login_modo"])
def test_put_valor_invalido_422(client: TestClient, banco: _Fake, campo: str) -> None:
    r = client.put("/api/settings", headers=_h(*ADMIN), json={**cfg.SettingsBody().model_dump(), campo: "talvez"})
    assert r.status_code == 422


def test_put_sem_os_campos_preserva(client: TestClient, banco: _Fake) -> None:
    base = cfg.SettingsBody().model_dump()
    client.put("/api/settings", headers=_h(*ADMIN), json={
        **base, "remocao_carteira_modo": "ligado", "remocao_sem_login_modo": "desligado",
    })
    # Salvar outro formulario (sem os campos) nao zera as chaves.
    r = client.put("/api/settings", headers=_h(*ADMIN), json=base)
    assert r.status_code == 200, r.text
    assert remocao.modo_carteira() == "ligado" and remocao.modo_sem_login() == "desligado"
    # "" volta ao padrao.
    client.put("/api/settings", headers=_h(*ADMIN), json={**base, "remocao_carteira_modo": ""})
    assert remocao.modo_carteira() == "relatorio" and remocao.modo_sem_login() == "desligado"
