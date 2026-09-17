"""
`app/db_pg.py`: a cadeia de chamadas do portal virando SQL parametrizado.

Duas camadas:

1. **SQL gerado** (sem banco): `Query.montar()` devolve as instruções. O que
   se testa é o texto e os parâmetros — é aqui que um `eq` virando `LIKE`, ou
   um valor caindo dentro do texto do SQL em vez de virar parâmetro, apareceria.
2. **Integração** (com banco): só roda se `TEST_DATABASE_URL` estiver
   definida. Cria uma tabela temporária de nome único, exercita cada verbo e
   confere o que VOLTA — datas como texto ISO, JSONB como dict, `single()`
   falhando com 0 linhas — que é o contrato de que os outros módulos dependem.
"""
from __future__ import annotations

import os
import uuid
from typing import Any, List, Tuple

import pytest

from app import db_pg
from app.db_pg import DbError, Query, _dividir_or


class _SemBanco:
    """Cliente falso só para montar SQL; nunca conecta."""

    def _chave_primaria(self, tabela: str) -> List[str]:
        return ["id"]


def _sql(q: Query) -> List[Tuple[str, List[Any]]]:
    """Texto do SQL como o psycopg o renderizaria, sem precisar de conexão."""
    out = []
    for peca, params in q.montar():
        out.append((peca.as_string(None), params))
    return out


def _q(tabela: str = "t") -> Query:
    return Query(_SemBanco(), tabela)  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────────
# SQL gerado
# ──────────────────────────────────────────────────────────────────────────

def test_select_simples() -> None:
    (texto, params), = _sql(_q().select("*").eq("a", 1).order("b", desc=True).limit(5))
    assert texto == 'SELECT * FROM "t" WHERE "a" = %s ORDER BY "b" DESC LIMIT %s'
    assert params == [1, 5]


def test_colunas_explicitas_sao_identificadores() -> None:
    (texto, _), = _sql(_q().select("file_name, nome, documento"))
    assert texto == 'SELECT "file_name", "nome", "documento" FROM "t"'


def test_valores_nunca_entram_no_texto() -> None:
    """Injeção: o valor vai como parâmetro, e o texto do SQL não muda com ele."""
    perigoso = "x'; DROP TABLE t; --"
    (texto, params), = _sql(_q().select("*").eq("nome", perigoso))
    assert perigoso not in texto
    assert params == [perigoso]


def test_identificador_invalido_e_recusado() -> None:
    with pytest.raises(DbError):
        _sql(_q().select("*").eq('a"; drop table t; --', 1))


def test_range_vira_limit_offset() -> None:
    (texto, params), = _sql(_q().select("*").range(20, 29))
    assert texto.endswith("LIMIT %s OFFSET %s")
    assert params == [10, 20]


def test_count_exact_conta_sem_paginacao() -> None:
    instrucoes = _sql(_q().select("id", count="exact").eq("a", 1).range(0, 9))
    assert len(instrucoes) == 2
    assert instrucoes[0][0] == 'SELECT count(*) AS n FROM "t" WHERE "a" = %s'
    assert instrucoes[0][1] == [1]
    assert instrucoes[1][0].endswith("LIMIT %s OFFSET %s") is False  # offset 0 não aparece
    assert instrucoes[1][0].endswith("LIMIT %s")


def test_head_so_conta() -> None:
    instrucoes = _sql(_q().select("id", count="exact", head=True))
    assert len(instrucoes) == 1
    assert instrucoes[0][0].startswith("SELECT count(*)")


def test_filtros_de_comparacao() -> None:
    q = (_q().select("*").neq("a", 1).gt("b", 2).gte("c", 3).lt("d", 4).lte("e", 5)
         .like("f", "x%").ilike("g", "%y%"))
    (texto, params), = _sql(q)
    assert '"a" <> %s AND "b" > %s AND "c" >= %s AND "d" < %s AND "e" <= %s' in texto
    assert '"f" LIKE %s AND "g" ILIKE %s' in texto
    assert params == [1, 2, 3, 4, 5, "x%", "%y%"]


def test_is_null_e_not_null() -> None:
    (texto, params), = _sql(_q().select("*").is_("read_at", "null").is_("x", "not null"))
    assert '"read_at" IS NULL AND "x" IS NOT NULL' in texto
    assert params == []


def test_in_usa_any() -> None:
    (texto, params), = _sql(_q().select("*").in_("id", ["a", "b"]))
    assert '"id" = ANY(%s)' in texto
    assert params == [["a", "b"]]


def test_in_vazio_nao_devolve_nada() -> None:
    (texto, _), = _sql(_q().select("*").in_("id", []))
    assert "WHERE FALSE" in texto


def test_or_na_sintaxe_do_postgrest() -> None:
    (texto, params), = _sql(_q().select("*").or_("nome.ilike.%ab%,file_name.ilike.%ab%,x.is.null"))
    assert '("nome" ILIKE %s OR "file_name" ILIKE %s OR "x" IS NULL)' in texto
    assert params == ["%ab%", "%ab%"]


def test_dividir_or_respeita_virgula_no_padrao() -> None:
    assert _dividir_or("a.eq.1,b.ilike.%x%") == ["a.eq.1", "b.ilike.%x%"]


def test_insert_devolve_linhas() -> None:
    (texto, params), = _sql(_q().insert({"a": 1, "b": "x"}))
    assert texto == 'INSERT INTO "t" ("a", "b") VALUES (%s, %s) RETURNING *'
    assert params == [1, "x"]


def test_insert_em_lote_com_colunas_diferentes_usa_default() -> None:
    (texto, params), = _sql(_q().insert([{"a": 1}, {"a": 2, "b": "y"}]))
    assert 'VALUES (%s, DEFAULT), (%s, %s)' in texto
    assert params == [1, 2, "y"]


def test_dict_vira_jsonb() -> None:
    (_, params), = _sql(_q().insert({"items": [{"x": 1}]}))
    assert type(params[0]).__name__ == "Jsonb"


def test_upsert_com_on_conflict() -> None:
    (texto, _), = _sql(_q().upsert({"id": 1, "v": 2}, on_conflict="id"))
    assert 'ON CONFLICT ("id") DO UPDATE SET "v" = EXCLUDED."v"' in texto
    assert texto.endswith("RETURNING *")


def test_upsert_sem_on_conflict_usa_a_chave_primaria() -> None:
    (texto, _), = _sql(_q().upsert({"id": 1, "v": 2}))
    assert 'ON CONFLICT ("id")' in texto


def test_upsert_so_com_chaves_nao_atualiza_nada() -> None:
    (texto, _), = _sql(_q().upsert({"id": 1}, on_conflict="id"))
    assert "DO NOTHING" in texto


def test_update_com_filtro() -> None:
    (texto, params), = _sql(_q().update({"v": 9}).eq("id", 1))
    assert texto == 'UPDATE "t" SET "v" = %s WHERE "id" = %s RETURNING *'
    assert params == [9, 1]


def test_delete_com_filtro() -> None:
    (texto, params), = _sql(_q().delete().lt("created_at", "2026-01-01"))
    assert texto == 'DELETE FROM "t" WHERE "created_at" < %s RETURNING *'
    assert params == ["2026-01-01"]


def test_recurso_embutido_e_recusado() -> None:
    with pytest.raises(DbError):
        _sql(_q().select("*, outra(*)"))


def test_normalizacao_do_que_sai() -> None:
    import datetime as dt
    import decimal

    linha = db_pg.normalizar_linha({
        "quando": dt.datetime(2026, 9, 4, 21, 0, 0, tzinfo=dt.timezone.utc),
        "dia": dt.date(2026, 9, 4),
        "id": uuid.UUID("12345678-1234-5678-1234-567812345678"),
        "n": decimal.Decimal("3"),
        "f": decimal.Decimal("3.5"),
        "b": b"\x01\x02",
        "j": {"a": 1},
        "s": "texto",
        "nulo": None,
    })
    assert linha["quando"] == "2026-09-04T21:00:00+00:00"
    assert linha["dia"] == "2026-09-04"
    assert linha["id"] == "12345678-1234-5678-1234-567812345678"
    assert linha["n"] == 3 and isinstance(linha["n"], int)
    assert linha["f"] == 3.5
    assert linha["b"] == "\\x0102"
    assert linha["j"] == {"a": 1}
    assert linha["s"] == "texto" and linha["nulo"] is None


def test_erros_reconheciveis() -> None:
    assert db_pg.tabela_ausente(DbError("x", "42P01"))
    assert db_pg.coluna_ausente(DbError("x", "42703"))
    assert not db_pg.tabela_ausente(DbError("x", "42703"))
    assert not db_pg.tabela_ausente(RuntimeError("42P01"))


# ──────────────────────────────────────────────────────────────────────────
# Integração — só com TEST_DATABASE_URL
# ──────────────────────────────────────────────────────────────────────────

_DSN = os.getenv("TEST_DATABASE_URL", "").strip()
integracao = pytest.mark.skipif(not _DSN, reason="TEST_DATABASE_URL não definida")


@pytest.fixture
def banco():
    cliente = db_pg.Client(_DSN, min_size=1, max_size=2)
    nome = "t_" + uuid.uuid4().hex[:12]
    with cliente.conexao() as conn, conn.cursor() as cur:
        cur.execute(f"""
            CREATE TABLE {nome} (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                chave text UNIQUE,
                n integer,
                quando timestamptz DEFAULT now(),
                dados jsonb,
                lido_em timestamptz,
                ids uuid[]
            )
        """)
    try:
        yield cliente, nome
    finally:
        with cliente.conexao() as conn, conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {nome}")
        cliente.fechar()


@integracao
def test_insert_devolve_a_linha_com_tipos_de_texto(banco) -> None:
    c, t = banco
    r = c.table(t).insert({"chave": "a", "n": 1, "dados": {"x": [1, 2]}}).execute()
    assert len(r.data) == 1
    linha = r.data[0]
    assert isinstance(linha["id"], str) and len(linha["id"]) == 36
    assert isinstance(linha["quando"], str) and "T" in linha["quando"]
    assert linha["dados"] == {"x": [1, 2]}
    assert linha["lido_em"] is None


@integracao
def test_select_filtros_ordem_e_range(banco) -> None:
    c, t = banco
    c.table(t).insert([{"chave": f"k{i}", "n": i} for i in range(10)]).execute()
    r = c.table(t).select("chave, n", count="exact").gte("n", 3).order("n", desc=True).range(0, 2).execute()
    assert r.count == 7
    assert [x["n"] for x in r.data] == [9, 8, 7]
    assert set(r.data[0]) == {"chave", "n"}


@integracao
def test_is_null_e_update_e_delete(banco) -> None:
    c, t = banco
    c.table(t).insert([{"chave": "a", "n": 1}, {"chave": "b", "n": 2}]).execute()
    assert len(c.table(t).select("*").is_("lido_em", "null").execute().data) == 2
    up = c.table(t).update({"lido_em": "2026-09-04T00:00:00+00:00"}).eq("chave", "a").execute()
    assert len(up.data) == 1 and up.data[0]["lido_em"].startswith("2026-09-04")
    assert len(c.table(t).select("*").is_("lido_em", "null").execute().data) == 1
    de = c.table(t).delete().eq("chave", "b").execute()
    assert [x["chave"] for x in de.data] == ["b"]
    assert c.table(t).select("id", count="exact", head=True).execute().count == 1


@integracao
def test_upsert_atualiza_pela_coluna_unica(banco) -> None:
    c, t = banco
    c.table(t).upsert({"chave": "a", "n": 1}, on_conflict="chave").execute()
    r = c.table(t).upsert({"chave": "a", "n": 5}, on_conflict="chave").execute()
    assert r.data[0]["n"] == 5
    assert c.table(t).select("id", count="exact", head=True).execute().count == 1


@integracao
def test_single_e_maybe_single(banco) -> None:
    c, t = banco
    assert c.table(t).select("*").eq("chave", "nada").maybe_single().execute().data is None
    with pytest.raises(DbError) as e:
        c.table(t).select("*").eq("chave", "nada").single().execute()
    assert e.value.code == "PGRST116"
    c.table(t).insert({"chave": "a", "n": 1}).execute()
    assert c.table(t).select("*").eq("chave", "a").single().execute().data["n"] == 1


@integracao
def test_tabela_ausente_e_reconhecivel(banco) -> None:
    c, _ = banco
    with pytest.raises(DbError) as e:
        c.table("tabela_que_nao_existe_" + uuid.uuid4().hex[:6]).select("*").execute()
    assert db_pg.tabela_ausente(e.value)


@integracao
def test_in_e_or(banco) -> None:
    c, t = banco
    c.table(t).insert([{"chave": "abc", "n": 1}, {"chave": "xyz", "n": 2}, {"chave": "q", "n": 3}]).execute()
    assert len(c.table(t).select("*").in_("chave", ["abc", "q"]).execute().data) == 2
    r = c.table(t).select("*").or_("chave.ilike.%AB%,chave.eq.q").order("n").execute()
    assert [x["chave"] for x in r.data] == ["abc", "q"]


@integracao
def test_rpc_escalar(banco) -> None:
    c, _ = banco
    nome = "f_" + uuid.uuid4().hex[:8]
    with c.conexao() as conn, conn.cursor() as cur:
        cur.execute(f"CREATE FUNCTION {nome}(a integer, b integer) RETURNS integer LANGUAGE sql AS $$ SELECT a + b $$")
    try:
        assert c.rpc(nome, {"a": 2, "b": 3}).execute().data == 5
    finally:
        with c.conexao() as conn, conn.cursor() as cur:
            cur.execute(f"DROP FUNCTION {nome}(integer, integer)")


# ──────────────────────────────────────────────────────────────────────────
# Colunas array (install_token.certificate_ids é uuid[])
# ──────────────────────────────────────────────────────────────────────────

class _ComArray(_SemBanco):
    """Cliente falso que declara `ids` como coluna uuid[] da tabela."""

    def _colunas_array(self, tabela: str):
        return {"ids": "uuid"}


def test_lista_em_coluna_array_vai_com_cast_e_nao_como_jsonb() -> None:
    q = Query(_ComArray(), "t").insert({"ids": ["a", "b"], "dados": [1, 2]})  # type: ignore[arg-type]
    (texto, params), = _sql(q)
    assert '"ids", "dados"' in texto
    assert "%s::uuid[], %s" in texto
    assert params[0] == ["a", "b"]                # array de texto, o Postgres converte
    assert type(params[1]).__name__ == "Jsonb"    # lista em coluna comum segue JSONB


def test_update_de_coluna_array_tambem_usa_cast() -> None:
    q = Query(_ComArray(), "t").update({"ids": ["a"]}).eq("id", "x")  # type: ignore[arg-type]
    (texto, params), = _sql(q)
    assert '"ids" = %s::uuid[]' in texto
    assert params[0] == ["a"]


def test_sem_lista_nenhuma_nao_consulta_o_catalogo() -> None:
    class _Explode(_SemBanco):
        def _colunas_array(self, tabela: str):
            raise AssertionError("não devia consultar o catálogo")

    (texto, _), = _sql(Query(_Explode(), "t").insert({"n": 1}))  # type: ignore[arg-type]
    assert "INSERT" in texto


@integracao
def test_coluna_uuid_array_entra_como_lista_e_volta_como_lista_de_texto(banco) -> None:
    c, t = banco
    ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    r = c.table(t).insert({"chave": "arr", "ids": ids}).execute()
    assert r.data[0]["ids"] == ids
    lido = c.table(t).select("ids").eq("chave", "arr").single().execute()
    assert lido.data["ids"] == ids and all(isinstance(x, str) for x in ids)
    u = c.table(t).update({"ids": ids[:1]}).eq("chave", "arr").execute()
    assert u.data[0]["ids"] == ids[:1]
