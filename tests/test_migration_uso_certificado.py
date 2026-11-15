"""Migration das tabelas do registro de uso dos certificados (Frente C, 15/11/2026)."""
from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / "supabase" / "migrations"
SQL = PASTA / "20261115100000_uso_certificado.sql"


def _sql() -> str:
    return SQL.read_text(encoding="utf-8")


def _sem_comentarios() -> str:
    return "\n".join(l for l in _sql().splitlines() if not l.lstrip().startswith("--"))


def test_tabelas_e_restricoes():
    s = _sem_comentarios()
    for t in ("uso_conteiner", "uso_certificado", "uso_coleta"):
        assert f"CREATE TABLE IF NOT EXISTS public.{t}" in s
    assert "UNIQUE (machine_id, sid, conteiner, hora)" in s
    assert "UNIQUE (machine_id, sid, conteiner)" in s
    assert "machine_id text PRIMARY KEY" in re.sub(r"\s+", " ", s)
    assert "CHECK (auditoria IN ('ligada', 'desligada', 'desconhecida'))" in s
    assert "REFERENCES public.users(id)" in s
    assert not re.search(r"REFERENCES\s+users\(", s)
    assert "NAO rode a mao" in _sql()


def test_indices_idempotentes():
    s = _sem_comentarios()
    for i in re.findall(r"CREATE\s+INDEX\b[^;]*", s):
        assert "CREATE INDEX IF NOT EXISTS" in i
    for col in ("(hora DESC)", "(user_id, hora DESC)", "(documento, hora DESC)"):
        assert col in s


def test_sem_begin_commit_e_so_ascii():
    assert not re.search(r"^\s*(BEGIN|COMMIT)\s*;", _sql(), re.M)
    _sql().encode("ascii")


def test_nome_segue_a_ordem():
    assert SQL.name > "20261114110000_remocao_modos.sql"
    assert (PASTA / "20261114110000_remocao_modos.sql").exists()
