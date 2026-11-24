"""Migration da tabela uso_listagem: assinatura sem certificado identificado."""
from __future__ import annotations

import re
from pathlib import Path

PASTA = Path(__file__).resolve().parent.parent / "supabase" / "migrations"
SQL = PASTA / "20261124100000_uso_listagem.sql"


def test_migration_uso_listagem():
    bruto = SQL.read_text(encoding="utf-8")
    s = re.sub(r"\s+", " ", "\n".join(l for l in bruto.splitlines() if not l.lstrip().startswith("--")))
    assert "CREATE TABLE IF NOT EXISTS public.uso_listagem" in s
    assert "UNIQUE (machine_id, sid, primeiro_record)" in s  # reenvio do lote não duplica
    assert "user_id uuid NULL REFERENCES public.users(id) ON DELETE SET NULL" in s
    assert "certificados int NOT NULL" in s
    assert "NAO rode a mao" in bruto and bruto.isascii()
    assert not re.search(r"^\s*(BEGIN|COMMIT)\s*;", bruto, re.M)
    assert SQL.name > "20261118100000_uso_janela.sql"
