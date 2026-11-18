"""Migration da tabela uso_janela: programa/titulo em primeiro plano no uso do certificado."""
from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / "supabase" / "migrations"
SQL = PASTA / "20261118100000_uso_janela.sql"


def _sql() -> str:
    return SQL.read_text(encoding="utf-8")


def _sem_comentarios() -> str:
    return "\n".join(l for l in _sql().splitlines() if not l.lstrip().startswith("--"))


def test_migration_uso_janela():
    s = re.sub(r"\s+", " ", _sem_comentarios())
    assert "CREATE TABLE IF NOT EXISTS public.uso_janela" in s
    assert "uso_id bigint NOT NULL REFERENCES public.uso_certificado(id) ON DELETE CASCADE" in s
    assert "UNIQUE (machine_id, record_id, ordem)" in s
    assert "ordem smallint NOT NULL CHECK (ordem BETWEEN 0 AND 2)" in s
    assert "CREATE INDEX IF NOT EXISTS" in s and "(uso_id, record_id)" in s
    assert "NAO rode a mao" in _sql()


def test_sem_begin_commit_e_so_ascii():
    assert not re.search(r"^\s*(BEGIN|COMMIT)\s*;", _sql(), re.M)
    assert _sql().isascii()


def test_guarda_apaga_as_janelas_junto():
    # O _Fake nao faz FK: o cascade vive na migration, e a guarda de 5 anos apaga so o uso.
    assert "ON DELETE CASCADE" in _sql()


def test_nome_segue_a_ordem():
    assert SQL.name > "20261115100000_uso_certificado.sql"
    assert (PASTA / "20261115100000_uso_certificado.sql").exists()
