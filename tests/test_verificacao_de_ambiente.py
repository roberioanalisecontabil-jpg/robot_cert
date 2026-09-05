"""O ambiente é conferido de uma vez, na subida — não no primeiro uso.

Item 12 da Frente 2 (R9 do diagnóstico de 25/08/2026). Antes, cada variável
crítica falhava só na primeira utilização: chave do cofre errada no primeiro
PFX, JWT ausente no primeiro login — erro tarde, em produção, desligado da
causa. O precedente era a ENCRYPTION_KEY, que já derrubava o boot; agora a
regra vale para as demais.

A fronteira que estes testes prendem: valor MALFORMADO é fatal sempre;
ausência só é fatal em ambiente com cara de produção (banco configurado).
Recusar o boot local por falta de CRON_SECRET ensinaria a ignorar a
verificação — e verificação ignorada é pior que nenhuma.

Desde 05/09/2026 "banco configurado" é `DATABASE_URL` (PostgreSQL puro). Um
`.env` antigo, com SUPABASE_URL e sem DATABASE_URL, é fatal de propósito: é o
ambiente de antes da migração subindo sem banco nenhum.
"""

from __future__ import annotations

import pytest

from app import config


@pytest.fixture
def producao(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ambiente com cara de produção: banco configurado."""
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://u:p@127.0.0.1:5432/certguard", raising=False)
    monkeypatch.setattr(config, "API_KEY", "chave-do-agente", raising=False)
    monkeypatch.setenv("JWT_SECRET_KEY", "segredo-de-teste")
    monkeypatch.setenv("CRON_SECRET", "segredo-do-cron")


def test_dev_sem_nada_sobe_com_avisos() -> None:
    """O conftest zera o banco: é o ambiente de desenvolvimento típico."""
    fatais, avisos = config.verificar_ambiente()
    assert fatais == []
    assert avisos, "dev sem API_KEY tinha de pelo menos avisar do modo aberto"


def test_producao_completa_nao_tem_fatal(producao: None) -> None:
    fatais, _ = config.verificar_ambiente()
    assert fatais == []


def test_env_do_supabase_sem_database_url_e_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    """O .env de antes da migração não pode subir "vazio" em silêncio."""
    monkeypatch.setattr(config, "_SUPABASE_LEGADO", True, raising=False)
    monkeypatch.setattr(config, "DATABASE_URL", "", raising=False)
    fatais, _ = config.verificar_ambiente()
    assert any("DATABASE_URL" in f and "Supabase" in f for f in fatais)


def test_database_url_que_nao_e_postgres_e_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "DATABASE_URL", "mysql://u:p@h/db", raising=False)
    fatais, _ = config.verificar_ambiente()
    assert any("postgresql://" in f for f in fatais)


def test_chave_do_cofre_malformada_e_fatal_ate_em_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Presente-mas-errada nunca é intencional — e hoje só estouraria no
    primeiro upload de PFX."""
    monkeypatch.setattr(config, "CERT_ENCRYPTION_KEY", "curta", raising=False)
    fatais, _ = config.verificar_ambiente()
    assert any("CERT_ENCRYPTION_KEY" in f and "64" in f for f in fatais)


def test_chaves_do_cofre_iguais_e_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    """A separação é a garantia de 03/08: uma chave só entregava senha e
    certificado no mesmo vazamento."""
    monkeypatch.setattr(config, "CERT_ENCRYPTION_KEY", "ab" * 32, raising=False)
    monkeypatch.setattr(config, "CERT_PASSWORD_ENCRYPTION_KEY", "ab" * 32, raising=False)
    fatais, _ = config.verificar_ambiente()
    assert any("igual" in f for f in fatais)


def test_producao_sem_jwt_e_sem_api_key_e_fatal(
    producao: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.setattr(config, "API_KEY", "", raising=False)
    fatais, _ = config.verificar_ambiente()
    assert any("JWT_SECRET_KEY" in f for f in fatais)
    assert any("API_KEY" in f for f in fatais)


def test_cron_ausente_em_producao_e_aviso_nao_fatal(
    producao: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rota do cron já falha fechada (503); derrubar o boot por ela pararia
    o portal inteiro por causa de um recurso que se degrada sozinho."""
    monkeypatch.delenv("CRON_SECRET", raising=False)
    fatais, avisos = config.verificar_ambiente()
    assert fatais == []
    assert any("CRON_SECRET" in a for a in avisos)


def test_boot_recusa_quando_ha_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    """O lifespan é quem aplica a regra — mesma classe do teste da
    ENCRYPTION_KEY em test_encryption_key.py."""
    from fastapi.testclient import TestClient

    from app import main as app_main

    monkeypatch.setattr(
        app_main.config, "verificar_ambiente", lambda: (["variável de mentira"], [])
    )
    with pytest.raises(RuntimeError, match="mentira"):
        with TestClient(app_main.app):
            pass
