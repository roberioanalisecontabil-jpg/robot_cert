"""Migration das colunas do login pela Microsoft (spec 04/11/2026)."""
from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "supabase" / "migrations" / "20261105100000_login_microsoft.sql"

COLUNAS = (
    "microsoft_oid",
    "microsoft_refresh_cifrado",
    "microsoft_conferido_em",
    "microsoft_sem_conferencia",
    "desativada_pela_microsoft_em",
)


def _sql() -> str:
    return SQL.read_text(encoding="utf-8")


def _sem_comentarios() -> str:
    return "\n".join(l for l in _sql().splitlines() if not l.lstrip().startswith("--"))


def test_migration_login_microsoft_idempotente_e_completa():
    sql = _sem_comentarios()
    for c in COLUNAS:
        assert f"ADD COLUMN IF NOT EXISTS {c} " in sql, c
    assert not re.search(r"ADD COLUMN (?!IF NOT EXISTS)", sql)
    assert "microsoft_sem_conferencia boolean NOT NULL DEFAULT false" in sql
    assert not re.search(r"CREATE (UNIQUE )?INDEX (?!IF NOT EXISTS)", sql)
    assert "CREATE UNIQUE INDEX IF NOT EXISTS users_microsoft_oid_unico" in sql
    assert "WHERE microsoft_oid IS NOT NULL" in sql
    drop = sql.index("DROP CONSTRAINT IF EXISTS users_origem_valida")
    add = sql.index("ADD CONSTRAINT users_origem_valida")
    assert drop < add
    assert "CHECK (origem IN ('manual', 'acessorias', 'microsoft'))" in sql
    assert not re.search(r"^\s*(BEGIN|COMMIT)\s*;", sql, re.M)


def test_cabecalho_ascii_e_conferencia_no_fim():
    texto = _sql()
    texto.encode("ascii")
    assert "COMO USAR" in texto
    ultimo = texto[texto.rindex("-- Conferencia"):]
    assert "SELECT" in ultimo
