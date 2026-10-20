"""Migration da carteira sincronizada pelo Acessórias (ADR 0005, 18/10/2026).

Mesmas guardas da migration de 16/10 (dono, permissão, idempotência), mais as
duas desta: as restrições trocadas são achadas pela definição, não pelo nome
gerado, e `carteira_excecao` não sai antes de o código parar de lê-la.
"""
from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "supabase" / "migrations" / "20261020100000_carteira_sincronizada_pelo_acessorias.sql"

TABELAS = ("acessorias_usuario", "carteira_bloqueio")


def _sql() -> str:
    return SQL.read_text(encoding="utf-8")


def _sem_comentarios() -> str:
    return "\n".join(l for l in _sql().splitlines() if not l.lstrip().startswith("--"))


def test_toda_tabela_e_coluna_nova_e_idempotente():
    sql = _sql()
    for t in TABELAS:
        assert f"CREATE TABLE IF NOT EXISTS public.{t} (" in sql, t
    assert not re.search(r"CREATE (UNIQUE )?INDEX (?!IF NOT EXISTS)", sql)
    assert not re.search(r"ADD COLUMN (?!IF NOT EXISTS)", sql)


def test_sem_begin_commit():
    assert not re.search(r"^\s*(BEGIN|COMMIT)\s*;", _sql(), re.M)


def test_restricoes_trocadas_pela_definicao():
    # A de estado veio inline em 20261016100000, com nome gerado. Um DROP
    # CONSTRAINT IF EXISTS com nome chutado passaria calado e a nova
    # conviveria com a velha, recusando 'aguardando'.
    sql = _sem_comentarios()
    assert "DROP CONSTRAINT IF EXISTS" not in sql
    assert sql.count("pg_get_constraintdef(oid) LIKE") == 2
    assert "'aguardando'" in sql and "'descartada'" in sql
    assert "'bloqueio'" in sql


def test_carteira_excecao_continua():
    # O código de hoje ainda calcula o Gestor como "tudo menos as Exceções".
    assert "carteira_excecao" not in _sem_comentarios()


def test_dono_e_permissao_de_cada_tabela_nova():
    sql = _sql()
    bloco = sql[sql.index("-- 8. Dono e permissoes"):]
    for t in TABELAS:
        assert f"ALTER TABLE public.{t} OWNER TO" in bloco, t
        assert f"public.{t}" in bloco.split("GRANT SELECT, INSERT, UPDATE, DELETE")[1], t
