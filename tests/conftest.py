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


@pytest.fixture(autouse=True)
def encryption_key_de_teste(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Chave Fernet fixa para os testes.

    O boot passou a exigir ENCRYPTION_KEY (`smtp_service.verificar_chave_
    configurada`), então sem isto a suíte dependeria do .env da máquina — e
    passaria ou falharia conforme quem a roda. Chave literal de propósito: é de
    teste, não é segredo, e ser fixa mantém o resultado reprodutível.
    """
    monkeypatch.setenv("ENCRYPTION_KEY", "hUXK9m0Qs2vZ8pYbN3rTfL6wJcE1aD4gXoV7iS5kBnM=")


@pytest.fixture(autouse=True)
def chaves_do_cofre(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Chaves do instalador: uma para o PFX, outra para a senha.

    Precisam ser DIFERENTES entre si — `cert_installer._get_password_key` recusa
    chaves iguais, porque cifrar senha e certificado com a mesma chave foi o
    defeito que tirou a senha do banco em 03/08. Literais de teste, fixas para o
    resultado não depender do .env da máquina.
    """
    monkeypatch.setattr("app.config.CERT_ENCRYPTION_KEY", "11" * 32, raising=False)
    monkeypatch.setattr("app.config.CERT_PASSWORD_ENCRYPTION_KEY", "22" * 32, raising=False)


@pytest.fixture(autouse=True)
def limpar_rate_limit() -> None:
    """A janela de rate limit em memória (fallback de `app/taxa.py`) vive no
    módulo, e o TestClient chega sempre como o mesmo IP: sem limpar entre
    testes, o teto de 20 logins/minuto derrubaria a suíte — que faz dezenas de
    logins — por ORDEM de execução, não por defeito."""
    from app import taxa

    taxa._memoria.clear()
    yield
    taxa._memoria.clear()


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
