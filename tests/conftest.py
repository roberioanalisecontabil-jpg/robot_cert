"""Fixtures partilhados para pytest."""

import pytest
from fastapi.testclient import TestClient


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
