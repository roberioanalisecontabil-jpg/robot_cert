"""Fixtures partilhados para pytest."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def sem_supabase_real(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Nenhum teste fala com o Supabase de verdade. Autouse, sem opt-in.

    Isto não é higiene teórica: `test_upload_aceita_certificado_autorizado`
    fazia patch de `listar_optin_fingerprints` mas não de `upsert_pfx`, então
    passava da barreira do opt-in e **gravava em cert_pfx_store de produção** a
    cada `pytest` — uma linha com fingerprint "bbbb…" e machine_id "m1", chaves
    de teste no cofre real. O `.env` da máquina de desenvolvimento aponta para
    produção, e nada no conftest anterior desligava isso.

    Zerar as credenciais em `app.config` basta: `settings_state._supabase()`
    devolve None antes de tocar no singleton do cliente, e
    `cert_installer._supabase()` delega para ele. Testes que precisam de banco
    injetam um fake explícito (ver `test_cert_installer_optin_e2e.py`).
    """
    monkeypatch.setattr("app.config.SUPABASE_URL", "", raising=False)
    monkeypatch.setattr("app.config.SUPABASE_SERVICE_KEY", "", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)


@pytest.fixture
def no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """API sem exigir X-API-Key (reproduz ambiente dev sem API_KEY)."""
    monkeypatch.setattr("app.config.API_KEY", "", raising=False)
    monkeypatch.setenv("JWT_SECRET_KEY", "jwt-secret-apenas-testes")


@pytest.fixture
def api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Exige a mesma chave em todos os /api/..."""
    key = "chave-somente-para-testes"
    monkeypatch.setattr("app.config.API_KEY", key, raising=False)
    monkeypatch.setenv("JWT_SECRET_KEY", "jwt-secret-apenas-testes")
    return key


@pytest.fixture
def client(no_api_key: None) -> TestClient:  # noqa: ARG001
    from app.main import app

    return TestClient(app)


@pytest.fixture
def client_com_chave(api_key: str) -> TestClient:  # noqa: ARG001
    from app.main import app

    return TestClient(app)
