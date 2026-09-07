"""
Aplica o esquema do portal num PostgreSQL puro: prelúdio + migrations, em ordem.

    python db/aplicar_schema.py postgresql://certguard:senha@127.0.0.1:5432/certguard
    python db/aplicar_schema.py            # usa DATABASE_URL do ambiente/.env

Reexecutável: o que já foi aplicado fica em `public.schema_migrations` e é
pulado. Cada arquivo roda numa transação própria — um erro no meio deixa os
anteriores aplicados e o faltoso por aplicar, com a mensagem do Postgres.

Por que rodar as migrations do Supabase em vez de um `schema.sql` consolidado:
elas são a história do banco (34 arquivos, cada um com o porquê), e só
precisam de um esquema `auth` mínimo (ver `000_prelude_postgres.sql`) para
compilarem. O consolidado vem depois, do dump do banco real, quando a
migração de dados terminar — aí ele será a verdade, não uma transcrição.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
# `db/*.sql` roda antes: o prelúdio (esquema `auth` mínimo) e as tabelas que
# nunca tiveram migration (`users`, criada à mão no Supabase).
BASE = RAIZ / "db"
MIGRATIONS = RAIZ / "supabase" / "migrations"


def _ordem(arq: Path) -> tuple[str, str]:
    """
    Ordem cronológica, não alfabética. `20260803_cert_installer.sql` veio ANTES
    de `20260803120000_cert_installer_rls.sql` (que até checa isso), mas o
    `_` ordena depois do `1`. Preenche o carimbo curto (só data) com zeros.
    """
    nome = arq.name
    digitos = ""
    for ch in nome:
        if ch.isdigit():
            digitos += ch
        else:
            break
    return (digitos.ljust(14, "0"), nome)


def _dsn(argv: list[str]) -> str:
    if len(argv) > 1 and argv[1].strip():
        return argv[1].strip()
    try:
        from dotenv import load_dotenv

        load_dotenv(RAIZ / ".env")
    except Exception:  # noqa: BLE001
        pass
    dsn = (os.getenv("DATABASE_URL") or "").strip()
    if not dsn:
        sys.exit("Informe a DSN como argumento ou defina DATABASE_URL.")
    return dsn


def main(argv: list[str]) -> int:
    import psycopg

    dsn = _dsn(argv)
    arquivos = sorted(BASE.glob("*.sql")) + sorted(MIGRATIONS.glob("*.sql"), key=_ordem)
    aplicados = 0
    with psycopg.connect(dsn, autocommit=False) as conn:
        # O prelúdio cria a tabela de controle; até ela existir, tudo é "novo".
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.schema_migrations') IS NOT NULL")
            tem_controle = bool(cur.fetchone()[0])
        ja = set()
        if tem_controle:
            with conn.cursor() as cur:
                cur.execute("SELECT arquivo FROM public.schema_migrations")
                ja = {r[0] for r in cur.fetchall()}

        for arq in arquivos:
            nome = arq.name
            if nome in ja:
                continue
            sql = arq.read_text(encoding="utf-8")
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    cur.execute(
                        "INSERT INTO public.schema_migrations (arquivo) VALUES (%s) "
                        "ON CONFLICT DO NOTHING",
                        (nome,),
                    )
                conn.commit()
                aplicados += 1
                print(f"  ok   {nome}")
            except Exception as e:  # noqa: BLE001
                conn.rollback()
                print(f"  ERRO {nome}\n       {str(e).strip()}")
                return 1
    print(f"Pronto: {aplicados} arquivo(s) aplicado(s), {len(ja)} já estavam.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
