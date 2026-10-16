"""Migration da carteira sugerida pelo Acessórias (ADR 0004 e adendo, 16/10/2026).

O banco de produção só é alcançado pelo `atualizar-portal.ps1`, que aplica as
migrations conectado como o dono das tabelas. Estes testes guardam o que já
quebrou antes nesse caminho: tabela nova sem dono/permissão para o usuário do
portal (sieg_inclusao, 07/10) e migration que não pode rodar duas vezes.
"""
from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "supabase" / "migrations" / "20261016100000_carteira_sugerida_pelo_acessorias.sql"
ADR = RAIZ / "docs" / "adr" / "0004-carteira-sugerida-pelo-acessorias.md"

TABELAS = (
    "acessorias_departamento",
    "acessorias_empresa",
    "acessorias_responsavel",
    "acessorias_busca",
    "acessorias_recusa",
    "carteira_historico",
)


def _sql() -> str:
    return SQL.read_text(encoding="utf-8")


def test_toda_tabela_nova_e_idempotente():
    sql = _sql()
    for t in TABELAS:
        assert f"CREATE TABLE IF NOT EXISTS public.{t} (" in sql, t
    assert not re.search(r"CREATE (UNIQUE )?INDEX (?!IF NOT EXISTS)", sql)
    assert "ADD COLUMN IF NOT EXISTS origem" in sql


def test_sem_begin_commit():
    # O aplicar_schema.py já abre uma transação por arquivo.
    assert not re.search(r"^\s*(BEGIN|COMMIT)\s*;", _sql(), re.M)


def test_dono_e_permissao_de_cada_tabela_nova():
    sql = _sql()
    bloco = sql[sql.index("-- 8. Dono e permissoes"):]
    for t in TABELAS:
        assert f"ALTER TABLE public.{t} OWNER TO" in bloco, t
        assert f"public.{t}" in bloco.split("GRANT SELECT, INSERT, UPDATE, DELETE")[1], t
    for seq in ("acessorias_busca_id_seq", "acessorias_recusa_id_seq", "carteira_historico_id_seq"):
        assert seq in bloco, seq


def test_departamentos_iniciais_nao_desfazem_a_tela():
    sql = _sql()
    for linha in ("(1, 'Contábil', true)", "(2, 'Fiscal',   true)", "(3, 'Pessoal',  true)"):
        assert linha in sql
    assert "ON CONFLICT (id) DO NOTHING" in sql


def test_origem_da_carteira_tem_os_tres_valores():
    assert "CHECK (origem IN ('manual', 'planilha', 'acessorias'))" in _sql()


def test_uma_busca_por_vez():
    assert "acessorias_busca_uma_rodando" in _sql()
    assert "WHERE estado = 'rodando'" in _sql()


def test_adendo_dos_departamentos_no_adr():
    adr = ADR.read_text(encoding="utf-8")
    assert "## Adendo (16/10/2026): departamentos espelhados do Acessórias" in adr
    assert "A liderança continua só manual" in adr
    assert "A mudança manual vence" in adr
