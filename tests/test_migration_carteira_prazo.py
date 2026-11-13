"""Migration do prazo da liberacao manual na carteira (aba Certificados, 13/11/2026)."""
from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "supabase" / "migrations" / "20261113100000_carteira_prazo.sql"


def _sql() -> str:
    return SQL.read_text(encoding="utf-8")


def _sem_comentarios() -> str:
    return "\n".join(l for l in _sql().splitlines() if not l.lstrip().startswith("--"))


def test_colunas_idempotentes():
    s = _sql()
    assert "ADD COLUMN IF NOT EXISTS valido_desde date NOT NULL DEFAULT current_date" in s
    assert "ADD COLUMN IF NOT EXISTS valido_ate date" in s
    assert not re.search(r"ADD COLUMN (?!IF NOT EXISTS)", s)


def test_teto_de_700_dias():
    assert "valido_ate - valido_desde <= 700" in _sem_comentarios()


def test_historico_aceita_prazo_sem_perder_os_antigos():
    s = _sem_comentarios()
    for o in ("manual", "planilha", "acessorias", "papel", "desativacao", "bloqueio", "prazo"):
        assert f"'{o}'" in s
    # constraint achada pela definicao, como em 20261020100000
    assert "pg_get_constraintdef" in s


def test_sem_begin_commit_e_so_ascii():
    assert not re.search(r"^\s*(BEGIN|COMMIT)\s*;", _sql(), re.M)
    _sql().encode("ascii")
