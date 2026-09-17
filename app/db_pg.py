"""
Acesso ao banco em PostgreSQL puro, com a cadeia de chamadas que o portal já usa.

Até 05/09/2026 o portal falava com o Supabase pelo cliente deles: uma API REST
(PostgREST) na frente do Postgres, mais chaves, mais um serviço de terceiros
que decidiu desligar tudo por cota. Este módulo é o que ficou no lugar: a
mesma cadeia — `table("x").select("*").eq("a", 1).order("b").execute()` — só
que gerando SQL parametrizado e falando direto com o PostgreSQL por `psycopg`.

── Por que a mesma cadeia, e não SQL escrito à mão em cada rota ─────────

Há 136 chamadas em 8 módulos, e 30 arquivos de teste que fingem o cliente
imitando exatamente esta cadeia. Trocar a cadeia inteira de uma vez seria
reescrever 272 pontos (código + testes) sem nada que provasse que o
comportamento ficou igual. Manter a forma faz os 982 testes existentes
serem a prova. Depois, com o portal no ar, cada rota tocada pode virar SQL
direto — isto aqui não impede, só destrava.

── O que é reproduzido DE PROPÓSITO (o código depende) ──────────────────

* Datas voltam como texto ISO, UUID como texto, JSONB como dict/list, bytea
  como `\\x…` — o formato em que o PostgREST entregava e que o código lê
  (`row["scanned_at"][:10]`, `datetime.fromisoformat(...)`).
* `insert`/`update`/`delete` devolvem as linhas afetadas (`returning *`).
* `single()` falha com 0 ou 2+ linhas; `maybe_single()` devolve `None` com 0.
* `count="exact"` conta o total ignorando `range`/`limit`; `head=True` só conta.
* `upsert` sem `on_conflict` usa a chave primária da tabela (consultada uma
  vez e guardada), como o PostgREST fazia.
* Tabela ou coluna ausente viram `DbError` com o SQLSTATE (`42P01`, `42703`);
  `tabela_ausente(e)`/`coluna_ausente(e)` são o que os módulos perguntam —
  antes eles procuravam "PGRST205"/"PGRST204" no texto do erro.

── O que NÃO existe aqui ────────────────────────────────────────────────

Recursos embutidos do PostgREST (`select("*, outra(*)")`), `text_search`,
`contains`: nunca foram usados neste portal. Se alguém precisar, escreve SQL.

Uma instrução por `execute()`, em autocommit — o mesmo isolamento que a API
dava. Quem precisar de transação de verdade usa `conexao()` diretamente.
"""
from __future__ import annotations

import base64
import datetime as _dt
import decimal
import logging
import re
import threading
import uuid
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DbError(Exception):
    """Erro do banco com o SQLSTATE em `code` (ou um código próprio, ex. `PGRST116`)."""

    def __init__(self, message: str, code: str = "") -> None:
        super().__init__(f"{code}: {message}" if code else message)
        self.message = message
        self.code = code


def tabela_ausente(erro: BaseException) -> bool:
    return isinstance(erro, DbError) and erro.code == "42P01"


def coluna_ausente(erro: BaseException) -> bool:
    return isinstance(erro, DbError) and erro.code == "42703"


class Result:
    __slots__ = ("data", "count")

    def __init__(self, data: Any, count: Optional[int] = None) -> None:
        self.data = data
        self.count = count

    def __repr__(self) -> str:  # pragma: no cover
        return f"Result(data={self.data!r}, count={self.count!r})"


# ── Normalização do que sai ───────────────────────────────────────────────

def _normalizar_valor(v: Any) -> Any:
    if isinstance(v, _dt.datetime):
        if v.tzinfo is None:
            return v.isoformat()
        return v.isoformat()
    if isinstance(v, _dt.date):
        return v.isoformat()
    if isinstance(v, _dt.time):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, decimal.Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return "\\x" + bytes(v).hex()
    if isinstance(v, (list, tuple)):
        # Colunas array (uuid[] etc.) voltam como lista de objetos; o PostgREST
        # entregava lista de texto, e é isso que o resto do portal espera.
        return [_normalizar_valor(x) for x in v]
    return v


def normalizar_linha(linha: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _normalizar_valor(v) for k, v in linha.items()}


def _adaptar_param(v: Any) -> Any:
    """Valores que o Postgres não aceita crus: dict/list viram JSONB."""
    if isinstance(v, (dict, list)):
        return Jsonb(v)
    return v


def _marcador_e_param(coluna: str, valor: Any, arrays: Dict[str, str]) -> Tuple[sql.Composable, Any]:
    """O marcador e o parâmetro de UMA coluna num INSERT/UPDATE.

    Lista vira JSONB por padrão. A exceção é coluna declarada como array no
    catálogo (install_token.certificate_ids é uuid[]): o PostgREST aceitava um
    array JSON e convertia; aqui a lista vai como array de texto com cast
    explícito para o tipo da coluna ("%s::uuid[]"), que é como o Postgres
    aceita text[] → uuid[].
    """
    tipo = arrays.get(coluna)
    if tipo and isinstance(valor, (list, tuple)):
        if not _IDENT.match(tipo):
            raise DbError(f"tipo de array inválido: {tipo!r}", "22023")
        return sql.SQL("%s::" + tipo + "[]"), [None if x is None else str(x) for x in valor]
    return sql.SQL("%s"), _adaptar_param(valor)


# ── Montagem de SQL ───────────────────────────────────────────────────────

def _ident(nome: str) -> sql.Composable:
    nome = nome.strip()
    if "." in nome:
        partes = nome.split(".")
        for p in partes:
            if not _IDENT.match(p):
                raise DbError(f"identificador inválido: {nome!r}", "22023")
        return sql.SQL(".").join(sql.Identifier(p) for p in partes)
    if not _IDENT.match(nome):
        raise DbError(f"identificador inválido: {nome!r}", "22023")
    return sql.Identifier(nome)


def _colunas(spec: str) -> sql.Composable:
    spec = (spec or "*").strip()
    if spec == "*":
        return sql.SQL("*")
    partes = [p.strip() for p in spec.split(",") if p.strip()]
    if not partes:
        return sql.SQL("*")
    if any("(" in p for p in partes):
        raise DbError("recurso embutido do PostgREST não é suportado; escreva SQL", "0A000")
    return sql.SQL(", ").join(_ident(p) for p in partes)


_OPS = {
    "eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=",
    "like": "LIKE", "ilike": "ILIKE",
}


class Query:
    """Uma consulta em construção. Imutável na prática: cada método devolve `self`."""

    def __init__(self, cliente: "Client", tabela: str) -> None:
        self._c = cliente
        self._tabela = tabela
        self._op = "select"
        self._cols: str = "*"
        self._count: Optional[str] = None
        self._head = False
        self._where: List[Tuple[sql.Composable, Tuple[Any, ...]]] = []
        self._order: List[sql.Composable] = []
        self._limit: Optional[int] = None
        self._offset: Optional[int] = None
        self._single: Optional[str] = None  # "single" | "maybe"
        self._rows: List[Dict[str, Any]] = []
        self._values: Dict[str, Any] = {}
        self._on_conflict: Optional[str] = None
        self._ignore_dup = False

    # ── verbos ───────────────────────────────────────────────────────────
    def select(self, cols: str = "*", count: Optional[str] = None, head: bool = False) -> "Query":
        self._op = "select"
        self._cols = cols or "*"
        self._count = count
        self._head = bool(head)
        return self

    def insert(self, linhas: Any, **_ignorado: Any) -> "Query":
        self._op = "insert"
        self._rows = [dict(r) for r in (linhas if isinstance(linhas, list) else [linhas])]
        return self

    def upsert(self, linhas: Any, on_conflict: Optional[str] = None,
               ignore_duplicates: bool = False, **_ignorado: Any) -> "Query":
        self._op = "upsert"
        self._rows = [dict(r) for r in (linhas if isinstance(linhas, list) else [linhas])]
        self._on_conflict = on_conflict
        self._ignore_dup = bool(ignore_duplicates)
        return self

    def update(self, valores: Dict[str, Any], **_ignorado: Any) -> "Query":
        self._op = "update"
        self._values = dict(valores)
        return self

    def delete(self, **_ignorado: Any) -> "Query":
        self._op = "delete"
        return self

    # ── filtros ──────────────────────────────────────────────────────────
    def _filtro(self, coluna: str, op: str, valor: Any) -> "Query":
        self._where.append((sql.SQL("{} " + _OPS[op] + " %s").format(_ident(coluna)), (valor,)))
        return self

    def eq(self, coluna: str, valor: Any) -> "Query":
        return self._filtro(coluna, "eq", valor)

    def neq(self, coluna: str, valor: Any) -> "Query":
        return self._filtro(coluna, "neq", valor)

    def gt(self, coluna: str, valor: Any) -> "Query":
        return self._filtro(coluna, "gt", valor)

    def gte(self, coluna: str, valor: Any) -> "Query":
        return self._filtro(coluna, "gte", valor)

    def lt(self, coluna: str, valor: Any) -> "Query":
        return self._filtro(coluna, "lt", valor)

    def lte(self, coluna: str, valor: Any) -> "Query":
        return self._filtro(coluna, "lte", valor)

    def like(self, coluna: str, padrao: str) -> "Query":
        return self._filtro(coluna, "like", padrao)

    def ilike(self, coluna: str, padrao: str) -> "Query":
        return self._filtro(coluna, "ilike", padrao)

    def is_(self, coluna: str, valor: Any) -> "Query":
        v = str(valor).strip().lower() if valor is not None else "null"
        if v == "null":
            self._where.append((sql.SQL("{} IS NULL").format(_ident(coluna)), ()))
        elif v in ("not null", "not.null"):
            self._where.append((sql.SQL("{} IS NOT NULL").format(_ident(coluna)), ()))
        elif v in ("true", "false"):
            self._where.append((sql.SQL("{} IS " + v.upper()).format(_ident(coluna)), ()))
        else:
            raise DbError(f"is_ não aceita {valor!r}", "22023")
        return self

    def in_(self, coluna: str, valores: Iterable[Any]) -> "Query":
        lista = list(valores)
        if not lista:
            self._where.append((sql.SQL("FALSE"), ()))
            return self
        self._where.append((sql.SQL("{} = ANY(%s)").format(_ident(coluna)), (lista,)))
        return self

    def match(self, pares: Dict[str, Any]) -> "Query":
        for k, v in pares.items():
            self.eq(k, v)
        return self

    def or_(self, filtros: str) -> "Query":
        """
        Sintaxe do PostgREST, só o que o portal usa: `col.op.valor,col.op.valor`
        com op em eq/neq/gt/gte/lt/lte/like/ilike/is.
        """
        partes: List[sql.Composable] = []
        params: List[Any] = []
        for termo in _dividir_or(filtros):
            try:
                col, op, val = termo.split(".", 2)
            except ValueError as e:
                raise DbError(f"filtro or_ inválido: {termo!r}", "22023") from e
            if op == "is":
                partes.append(sql.SQL("{} IS " + ("NULL" if val.lower() == "null" else "NOT NULL")).format(_ident(col)))
            elif op in _OPS:
                partes.append(sql.SQL("{} " + _OPS[op] + " %s").format(_ident(col)))
                params.append(val)
            else:
                raise DbError(f"operador não suportado em or_: {op!r}", "22023")
        if partes:
            self._where.append((sql.SQL("(") + sql.SQL(" OR ").join(partes) + sql.SQL(")"), tuple(params)))
        return self

    # ── forma ────────────────────────────────────────────────────────────
    def order(self, coluna: str, desc: bool = False, nullsfirst: Optional[bool] = None,
              **_ignorado: Any) -> "Query":
        peca = sql.SQL("{} " + ("DESC" if desc else "ASC")).format(_ident(coluna))
        if nullsfirst is True:
            peca = peca + sql.SQL(" NULLS FIRST")
        elif nullsfirst is False:
            peca = peca + sql.SQL(" NULLS LAST")
        self._order.append(peca)
        return self

    def limit(self, n: int, **_ignorado: Any) -> "Query":
        self._limit = int(n)
        return self

    def range(self, inicio: int, fim: int, **_ignorado: Any) -> "Query":
        self._offset = int(inicio)
        self._limit = int(fim) - int(inicio) + 1
        return self

    def single(self) -> "Query":
        self._single = "single"
        return self

    def maybe_single(self) -> "Query":
        self._single = "maybe"
        return self

    # ── SQL ──────────────────────────────────────────────────────────────
    def _where_sql(self) -> Tuple[sql.Composable, List[Any]]:
        if not self._where:
            return sql.SQL(""), []
        params: List[Any] = []
        pecas = []
        for peca, p in self._where:
            pecas.append(peca)
            params.extend(p)
        return sql.SQL(" WHERE ") + sql.SQL(" AND ").join(pecas), params

    def _tail_sql(self) -> Tuple[sql.Composable, List[Any]]:
        peca = sql.SQL("")
        params: List[Any] = []
        if self._order:
            peca = peca + sql.SQL(" ORDER BY ") + sql.SQL(", ").join(self._order)
        if self._limit is not None:
            peca = peca + sql.SQL(" LIMIT %s")
            params.append(self._limit)
        if self._offset:
            peca = peca + sql.SQL(" OFFSET %s")
            params.append(self._offset)
        return peca, params

    def _colunas_array_se_preciso(self, valores: Any) -> Dict[str, str]:
        """Consulta o catálogo só quando há lista entre os valores (raro) e só
        se o cliente souber responder — os testes montam Query com dublês."""
        if not any(isinstance(v, (list, tuple)) for v in valores):
            return {}
        consultar = getattr(self._c, "_colunas_array", None)
        return consultar(self._tabela) if consultar else {}

    def _linhas_sql(self, linhas: List[Dict[str, Any]]) -> Tuple[List[str], sql.Composable, List[Any]]:
        colunas: List[str] = []
        for r in linhas:
            for k in r:
                if k not in colunas:
                    colunas.append(k)
        params: List[Any] = []
        tuplas = []
        arrays = self._colunas_array_se_preciso(r[c] for r in linhas for c in colunas if c in r)
        for r in linhas:
            marcadores = []
            for c in colunas:
                if c in r:
                    marcador, param = _marcador_e_param(c, r[c], arrays)
                    marcadores.append(marcador)
                    params.append(param)
                else:
                    marcadores.append(sql.SQL("DEFAULT"))
            tuplas.append(sql.SQL("(") + sql.SQL(", ").join(marcadores) + sql.SQL(")"))
        return colunas, sql.SQL(", ").join(tuplas), params

    def montar(self) -> List[Tuple[sql.Composable, List[Any]]]:
        """As instruções (SQL, params) que `execute` vai rodar. Público para teste."""
        t = _ident(self._tabela)
        where, wp = self._where_sql()
        if self._op == "select":
            instrucoes: List[Tuple[sql.Composable, List[Any]]] = []
            if self._count:
                instrucoes.append((sql.SQL("SELECT count(*) AS n FROM {}").format(t) + where, list(wp)))
            if not self._head:
                tail, tp = self._tail_sql()
                q = sql.SQL("SELECT ") + _colunas(self._cols) + sql.SQL(" FROM ") + t + where + tail
                instrucoes.append((q, list(wp) + tp))
            return instrucoes
        if self._op in ("insert", "upsert"):
            if not self._rows:
                return [(sql.SQL("SELECT 1 WHERE FALSE"), [])]
            colunas, valores, params = self._linhas_sql(self._rows)
            q = (sql.SQL("INSERT INTO {} (").format(t)
                 + sql.SQL(", ").join(_ident(c) for c in colunas)
                 + sql.SQL(") VALUES ") + valores)
            if self._op == "upsert":
                alvo = self._on_conflict or ",".join(self._c._chave_primaria(self._tabela))
                alvo_sql = sql.SQL(", ").join(_ident(c) for c in alvo.split(","))
                if self._ignore_dup:
                    q = q + sql.SQL(" ON CONFLICT (") + alvo_sql + sql.SQL(") DO NOTHING")
                else:
                    chaves = {c.strip() for c in alvo.split(",")}
                    setar = [c for c in colunas if c not in chaves]
                    if setar:
                        q = (q + sql.SQL(" ON CONFLICT (") + alvo_sql + sql.SQL(") DO UPDATE SET ")
                             + sql.SQL(", ").join(
                                 sql.SQL("{0} = EXCLUDED.{0}").format(_ident(c)) for c in setar))
                    else:
                        q = q + sql.SQL(" ON CONFLICT (") + alvo_sql + sql.SQL(") DO NOTHING")
            return [(q + sql.SQL(" RETURNING *"), params)]
        if self._op == "update":
            if not self._values:
                return [(sql.SQL("SELECT * FROM {}").format(t) + where + sql.SQL(" LIMIT 0"), list(wp))]
            arrays = self._colunas_array_se_preciso(self._values.values())
            pedacos = []
            params: List[Any] = []
            for k, v in self._values.items():
                marcador, param = _marcador_e_param(k, v, arrays)
                pedacos.append(sql.SQL("{} = ").format(_ident(k)) + marcador)
                params.append(param)
            setar = sql.SQL(", ").join(pedacos)
            params = params + list(wp)
            return [(sql.SQL("UPDATE {} SET ").format(t) + setar + where + sql.SQL(" RETURNING *"), params)]
        if self._op == "delete":
            return [(sql.SQL("DELETE FROM {}").format(t) + where + sql.SQL(" RETURNING *"), list(wp))]
        raise DbError(f"operação desconhecida: {self._op}", "0A000")

    def execute(self) -> Result:
        instrucoes = self.montar()
        count: Optional[int] = None
        linhas: List[Dict[str, Any]] = []
        try:
            with self._c.conexao() as conn:
                for i, (q, params) in enumerate(instrucoes):
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(q, params)
                        if self._op == "select" and self._count and i == 0:
                            r = cur.fetchone()
                            count = int(r["n"]) if r else 0
                            continue
                        if cur.description:
                            linhas = [normalizar_linha(dict(r)) for r in cur.fetchall()]
        except psycopg.Error as e:
            raise DbError(str(e).strip(), getattr(e, "sqlstate", "") or "") from e

        if self._single == "single":
            if len(linhas) != 1:
                raise DbError(
                    "JSON object requested, multiple (or no) rows returned", "PGRST116"
                )
            return Result(linhas[0], count)
        if self._single == "maybe":
            if len(linhas) > 1:
                raise DbError("JSON object requested, multiple rows returned", "PGRST116")
            return Result(linhas[0] if linhas else None, count)
        return Result(linhas, count)


def _dividir_or(texto: str) -> List[str]:
    """Divide `a.eq.1,b.ilike.%x,y%` respeitando parênteses (não usados, mas baratos)."""
    partes: List[str] = []
    atual = []
    nivel = 0
    for ch in texto:
        if ch == "(":
            nivel += 1
        elif ch == ")":
            nivel -= 1
        if ch == "," and nivel == 0:
            partes.append("".join(atual).strip())
            atual = []
        else:
            atual.append(ch)
    if atual:
        partes.append("".join(atual).strip())
    return [p for p in partes if p]


# ── Cliente ───────────────────────────────────────────────────────────────

class _Rpc:
    def __init__(self, cliente: "Client", nome: str, params: Optional[Dict[str, Any]]) -> None:
        self._c = cliente
        self._nome = nome
        self._params = dict(params or {})

    def execute(self) -> Result:
        args = sql.SQL(", ").join(
            sql.SQL("{} := %s").format(sql.Identifier(k)) for k in self._params
        )
        q = sql.SQL("SELECT * FROM {}(").format(_ident(self._nome)) + args + sql.SQL(")")
        try:
            with self._c.conexao() as conn, conn.cursor(row_factory=dict_row) as cur:
                cur.execute(q, [_adaptar_param(v) for v in self._params.values()])
                linhas = [normalizar_linha(dict(r)) for r in cur.fetchall()] if cur.description else []
        except psycopg.Error as e:
            raise DbError(str(e).strip(), getattr(e, "sqlstate", "") or "") from e
        # Função escalar: o PostgREST devolvia o valor cru, não uma linha.
        if len(linhas) == 1 and len(linhas[0]) == 1 and self._nome in linhas[0]:
            return Result(linhas[0][self._nome])
        return Result(linhas)


class Client:
    """Um pool por processo. `table()` e `rpc()` são a cara que o portal conhece."""

    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 6,
                 timeout: float = 10.0) -> None:
        self._dsn = dsn
        # timezone=UTC na sessão: o PostgREST entregava timestamptz em UTC
        # ("...+00:00") e há código que compara/recorta esse texto. Sem isto o
        # Postgres formata no fuso do servidor (-03:00) e a mesma hora vira
        # outro texto.
        self._pool = ConnectionPool(
            conninfo=dsn, min_size=min_size, max_size=max_size, timeout=timeout,
            kwargs={"autocommit": True, "options": "-c timezone=UTC"}, open=True,
        )
        self._pk_cache: Dict[str, List[str]] = {}
        self._array_cache: Dict[str, Dict[str, str]] = {}
        self._lock = threading.Lock()

    def conexao(self):
        return self._pool.connection()

    def fechar(self) -> None:
        self._pool.close()

    def table(self, nome: str) -> Query:
        return Query(self, nome)

    def from_(self, nome: str) -> Query:  # nome alternativo do cliente antigo
        return Query(self, nome)

    def rpc(self, nome: str, params: Optional[Dict[str, Any]] = None) -> _Rpc:
        return _Rpc(self, nome, params)

    def _colunas_array(self, tabela: str) -> Dict[str, str]:
        """{coluna: tipo do elemento} das colunas array da tabela (ex.:
        {"certificate_ids": "uuid"}). Uma consulta por tabela, por processo."""
        with self._lock:
            if tabela in self._array_cache:
                return self._array_cache[tabela]
        esquema, _, nome = tabela.rpartition(".")
        esquema = esquema or "public"
        q = """
            SELECT column_name, udt_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s AND data_type = 'ARRAY'
        """
        try:
            with self.conexao() as conn, conn.cursor() as cur:
                cur.execute(q, (esquema, nome))
                cols = {r[0]: r[1].lstrip("_") for r in cur.fetchall()}
        except psycopg.Error as e:
            raise DbError(str(e).strip(), getattr(e, "sqlstate", "") or "") from e
        with self._lock:
            self._array_cache[tabela] = cols
        return cols

    def _chave_primaria(self, tabela: str) -> List[str]:
        with self._lock:
            if tabela in self._pk_cache:
                return self._pk_cache[tabela]
        esquema, _, nome = tabela.rpartition(".")
        esquema = esquema or "public"
        q = """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = %s::regclass AND i.indisprimary
            ORDER BY array_position(i.indkey, a.attnum)
        """
        try:
            with self.conexao() as conn, conn.cursor() as cur:
                cur.execute(q, (f"{esquema}.{nome}",))
                cols = [r[0] for r in cur.fetchall()]
        except psycopg.Error as e:
            raise DbError(str(e).strip(), getattr(e, "sqlstate", "") or "") from e
        if not cols:
            raise DbError(f"{tabela} não tem chave primária; informe on_conflict", "42P10")
        with self._lock:
            self._pk_cache[tabela] = cols
        return cols


def de_base64(texto: str) -> bytes:  # utilitário para quem guardava bytes em texto
    return base64.b64decode(texto)
