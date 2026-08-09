"""Guarda-corpo: a suíte não pode alcançar o Supabase de produção.

Em 08/08 descobriu-se que `pytest` gravava em `cert_pfx_store` de produção a
cada execução — `test_upload_aceita_certificado_autorizado` fazia patch da
barreira de opt-in mas não de `upsert_pfx`, e o `.env` da máquina de
desenvolvimento aponta para o banco real. Ficou uma linha com fingerprint
"bbbb…" e machine_id "m1" no cofre de produção.

O que torna o defeito perigoso é ser invisível: os testes passam igual, e a
escrita só aparece se alguém for olhar o banco. Estes testes falham alto se o
isolamento do conftest for removido ou contornado.
"""

import os

import app.cert_installer as ci
import app.settings_state as ss
from app import config


def test_credenciais_de_supabase_zeradas_no_config() -> None:
    assert config.SUPABASE_URL == ""
    assert config.SUPABASE_SERVICE_KEY == ""


def test_credenciais_de_supabase_fora_do_ambiente() -> None:
    """Código que lê direto de os.getenv também não pode encontrar nada."""
    assert not os.getenv("SUPABASE_URL")
    assert not os.getenv("SUPABASE_SERVICE_KEY")


def test_cliente_supabase_nao_e_criado() -> None:
    """As duas portas de entrada — settings_state e cert_installer."""
    assert ss._supabase() is None
    assert ci._supabase() is None


def test_escrita_no_cofre_nao_alcanca_banco_nenhum() -> None:
    """
    Sem cliente, `autorizar_no_cofre` levanta em vez de gravar em algum lugar.

    É o caminho exato que escapou: chamar a função real de escrita num teste
    que não fez patch dela.
    """
    import pytest

    with pytest.raises(RuntimeError):
        ci.autorizar_no_cofre(fingerprint="c" * 64, enabled_by="teste")
