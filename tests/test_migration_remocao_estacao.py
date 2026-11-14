"""Migration da tabela remocao_estacao (Frente B, remocao de certificados nas estacoes, 14/11/2026)."""
from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "supabase" / "migrations" / "20261114100000_remocao_estacao.sql"


def _sql() -> str:
    return SQL.read_text(encoding="utf-8")


def _sem_comentarios() -> str:
    return "\n".join(l for l in _sql().splitlines() if not l.lstrip().startswith("--"))


def test_tabela_idempotente():
    assert "CREATE TABLE IF NOT EXISTS public.remocao_estacao" in _sql()


def test_checks_de_regra_e_estado():
    s = _sem_comentarios()
    for r in ("carteira", "desativada", "vinculo", "emprestimo", "sem_login"):
        assert f"'{r}'" in s
    for e in ("removeria", "aviso", "remover", "removido", "falhou"):
        assert f"'{e}'" in s


def test_unica_por_maquina_usuario_certificado():
    assert "UNIQUE (machine_id, usuario_windows, fingerprint)" in _sem_comentarios()


def test_indices_idempotentes():
    s = _sem_comentarios()
    indices = re.findall(r"CREATE\s+INDEX\b[^;]*", s)
    assert len(indices) == 2
    for i in indices:
        assert "CREATE INDEX IF NOT EXISTS" in i
    assert "(estado, atualizado_em DESC)" in s
    assert "(user_id)" in s


def test_fk_user_id_qualificada_com_public():
    s = _sem_comentarios()
    assert "REFERENCES public.users(id)" in s
    assert not re.search(r"REFERENCES\s+users\(", s)


def test_sem_begin_commit_e_so_ascii():
    assert not re.search(r"^\s*(BEGIN|COMMIT)\s*;", _sql(), re.M)
    _sql().encode("ascii")
