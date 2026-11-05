"""Migration das tabelas da bandeja pela Microsoft (plano 05/11/2026, Tarefa 1)."""
from __future__ import annotations

from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "supabase" / "migrations" / "20261106100000_bandeja_pela_microsoft.sql"
ANTERIOR = "20261105100000_login_microsoft.sql"


def _sem_comentarios() -> str:
    texto = SQL.read_text(encoding="utf-8")
    return "\n".join(l for l in texto.splitlines() if not l.lstrip().startswith("--"))


def test_migration_bandeja_idempotente_e_completa():
    sql = _sem_comentarios()
    assert "CREATE TABLE IF NOT EXISTS public.bandeja_codigo" in sql
    assert "CREATE TABLE IF NOT EXISTS public.bandeja_virada" in sql
    assert "CHECK (id = 1)" in sql
    assert "ON DELETE CASCADE" in sql
    assert "DROP TABLE" not in sql.upper()
    assert ("GRANT SELECT, INSERT, UPDATE, DELETE ON public.bandeja_codigo, "
            "public.bandeja_virada TO") in sql


def test_migration_bandeja_vem_depois_da_do_login():
    assert SQL.name > ANTERIOR
    assert (RAIZ / "supabase" / "migrations" / ANTERIOR).exists()
