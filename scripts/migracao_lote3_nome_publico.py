"""
Migração do lote 3 da auditoria (SECURITY_AUDIT #2): a senha sai do banco.

O que muda:
  * `cert_history`: a chave primária deixa de ser `file_name` (o nome do
    arquivo, que carrega a senha do PFX) e passa a ser `arquivo_chave`
    (sha256 de nome público + fingerprint). Ganha `nome_publico`; perde
    `file_name`.
  * `cert_snapshots.items[]`: cada item perde `file_name` e `path` e ganha
    `nome_publico`, `pasta` e `arquivo_chave`.

Como usar (SEMPRE numa cópia antes; nunca direto em produção sem o ensaio):

    python scripts/migracao_lote3_nome_publico.py --dsn postgresql://... --dry-run
    python scripts/migracao_lote3_nome_publico.py --dsn postgresql://... --ida
    python scripts/migracao_lote3_nome_publico.py --dsn postgresql://... --volta

`--ida` guarda cópias integrais (`cert_history_bkp_lote3`,
`cert_snapshots_bkp_lote3`) ANTES de tocar em qualquer linha, imprime as
contagens antes e depois, e é idempotente: se a tabela já está no formato
novo, não faz nada. `--volta` restaura as duas tabelas a partir das cópias e
recria a chave antiga. `--dry-run` só conta e mostra o que faria.

Colisão: dois nomes de arquivo viram a MESMA chave quando são o mesmo
certificado (fingerprint) sob o mesmo nome público — o caso real é o arquivo
renomeado com senha nova. Fica a linha com `ultima_data_registrada` mais
recente; a contagem é impressa. O fingerprint de cada `file_name` vem do
snapshot mais recente que o contém; nome que não aparece em snapshot nenhum
(arquivo removido há muito) recebe chave sem fingerprint e vira histórico
puro.

Ordem de implantação: rodar a migração e SÓ DEPOIS subir o código do lote 3.
O código novo grava por `arquivo_chave`; o antigo grava por `file_name`. Entre
os dois, o ingest falha o upsert do histórico (com log) e segue — o snapshot
continua sendo gravado.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.nome_publico import (  # noqa: E402  — a MESMA regra que o servidor usa
    chave_de_arquivo,
    nome_publico_de_arquivo,
    sanitizar_item,
)

BKP_HISTORY = "cert_history_bkp_lote3"
BKP_SNAPSHOTS = "cert_snapshots_bkp_lote3"

# Fora da função para o teste poder apontar: é isto que o critério de aceite
# do lote confere depois da migração.
SQL_CONTA_SENHA_HISTORY = "SELECT count(*) FROM cert_history WHERE file_name ILIKE '%senh%'"
SQL_CONTA_SENHA_SNAPSHOTS = (
    "SELECT count(*) FROM cert_snapshots s, jsonb_array_elements(s.items) i "
    "WHERE i->>'file_name' ILIKE '%senh%' OR i->>'path' ILIKE '%senh%'"
)
# Depois da migração o que se procura é o TOKEN de senha ("senha 123",
# "SENHA123", "_senha"), não a substring: "SENHOR" e "Senhora" são razão
# social e subject legítimos. Mesma regra de `app/nome_publico._RE_SENHA`,
# em sintaxe do Postgres. `error_message` fica de fora: é o texto fixo do
# scanner ("Senha incorreta"), não um nome de arquivo.
_TOKEN_SENHA_PG = r"(?<![a-z])senh(a|as)?(\s|[0-9:=_#@!*-]|$)"
SQL_CONTA_SENHA_HISTORY_NOVO = (
    f"SELECT count(*) FROM cert_history WHERE nome_publico ~* '{_TOKEN_SENHA_PG}' OR nome ~* '{_TOKEN_SENHA_PG}'"
)
SQL_CONTA_TOKEN_SNAPSHOTS = (
    "SELECT count(*) FROM cert_snapshots s, jsonb_array_elements(s.items) i, jsonb_each_text(i) kv(k, v) "
    f"WHERE kv.k <> 'error_message' AND kv.v ~* '{_TOKEN_SENHA_PG}'"
)


# ── Funções puras (testadas em tests/test_seguranca_lote3.py) ──────────────

def transformar_historico(
    linhas: Iterable[Dict[str, Any]], mapa_fingerprint: Dict[str, str]
) -> Tuple[List[Dict[str, Any]], int]:
    """Linhas antigas (com `file_name`) -> linhas novas (com `arquivo_chave`).

    Devolve (linhas_novas, colisoes). Em colisão fica a mais recente.
    """
    por_chave: Dict[str, Dict[str, Any]] = {}
    colisoes = 0
    for antiga in linhas:
        file_name = str(antiga.get("file_name") or "")
        nome_pub = nome_publico_de_arquivo(file_name) or str(antiga.get("nome") or "").strip() or "(sem nome)"
        fp = mapa_fingerprint.get(file_name, "")
        chave = chave_de_arquivo(nome_pub, fp)
        nova = {k: v for k, v in antiga.items() if k != "file_name"}
        nova["arquivo_chave"] = chave
        nova["nome_publico"] = nome_pub
        if nova.get("nome") and nome_publico_de_arquivo(str(nova["nome"])) != str(nova["nome"]).strip():
            # `nome` caía no file_name quando o X.509 não tinha titular.
            nova["nome"] = nome_pub
        atual = por_chave.get(chave)
        if atual is None:
            por_chave[chave] = nova
            continue
        colisoes += 1
        if str(nova.get("ultima_data_registrada") or "") > str(atual.get("ultima_data_registrada") or ""):
            por_chave[chave] = nova
    return list(por_chave.values()), colisoes


def sanitizar_itens(itens: Iterable[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """Itens de um snapshot -> itens públicos. Devolve (itens, quantos tinham nome bruto)."""
    saida = []
    brutos = 0
    for it in itens or []:
        if isinstance(it, dict) and (it.get("file_name") or it.get("path")):
            brutos += 1
        saida.append(sanitizar_item(it) if isinstance(it, dict) else it)
    return saida, brutos


# ── Banco ──────────────────────────────────────────────────────────────────

def _um(cur, sql: str) -> Any:
    cur.execute(sql)
    return cur.fetchone()[0]


def _formato_novo(cur) -> bool:
    cur.execute(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_name='cert_history' AND column_name='arquivo_chave'"
    )
    return cur.fetchone()[0] == 1


def _mapa_fingerprint(cur) -> Dict[str, str]:
    """file_name -> fingerprint, do snapshot mais recente que o traz."""
    mapa: Dict[str, str] = {}
    cur.execute("SELECT items FROM cert_snapshots ORDER BY scanned_at DESC")
    for (items,) in cur:
        for it in items or []:
            if not isinstance(it, dict):
                continue
            fn = str(it.get("file_name") or "")
            fp = str(it.get("fingerprint_sha256") or it.get("cert_sha256") or "").strip()
            if fn and fp and fn not in mapa:
                mapa[fn] = fp
    return mapa


def ida(conn, dry_run: bool) -> int:
    with conn.cursor() as cur:
        if _formato_novo(cur):
            print("cert_history já está no formato novo (arquivo_chave). Nada a fazer.")
            return 0

        total_h = _um(cur, "SELECT count(*) FROM cert_history")
        senh_h = _um(cur, SQL_CONTA_SENHA_HISTORY)
        total_s = _um(cur, "SELECT count(*) FROM cert_snapshots")
        senh_s = _um(cur, SQL_CONTA_SENHA_SNAPSHOTS)
        print(f"ANTES  cert_history: {total_h} linhas, {senh_h} com 'senh' no file_name")
        print(f"ANTES  cert_snapshots: {total_s} snapshots, {senh_s} itens com 'senh' em file_name/path")

        mapa = _mapa_fingerprint(cur)
        cur.execute("SELECT * FROM cert_history")
        colunas = [d[0] for d in cur.description]
        antigas = [dict(zip(colunas, r)) for r in cur.fetchall()]
        novas, colisoes = transformar_historico(antigas, mapa)
        print(f"PLANO  cert_history: {len(antigas)} -> {len(novas)} linhas ({colisoes} colisoes resolvidas pela mais recente); "
              f"{sum(1 for a in antigas if a['file_name'] in mapa)} com fingerprint conhecido")

        if dry_run:
            print("dry-run: nada gravado.")
            return 0

        # 1. Cópias integrais, antes de qualquer alteração.
        cur.execute(f"CREATE TABLE IF NOT EXISTS {BKP_HISTORY} AS SELECT * FROM cert_history")
        cur.execute(f"CREATE TABLE IF NOT EXISTS {BKP_SNAPSHOTS} AS SELECT * FROM cert_snapshots")
        print(f"backup: {BKP_HISTORY} ({_um(cur, f'SELECT count(*) FROM {BKP_HISTORY}')}), "
              f"{BKP_SNAPSHOTS} ({_um(cur, f'SELECT count(*) FROM {BKP_SNAPSHOTS}')})")

        # 2. cert_history: esquema novo e linhas novas. A coluna antiga sai
        #    ANTES do insert — ela era a chave primária, não nula, e as linhas
        #    novas não a têm. Tudo na mesma transação: qualquer falha reverte
        #    até o backup, e o banco fica como estava.
        cur.execute("ALTER TABLE cert_history ADD COLUMN arquivo_chave char(64), ADD COLUMN nome_publico text")
        cur.execute("DELETE FROM cert_history")
        cur.execute("ALTER TABLE cert_history DROP CONSTRAINT cert_history_pkey")
        cur.execute("ALTER TABLE cert_history DROP COLUMN file_name")
        cols = [c for c in colunas if c != "file_name"] + ["arquivo_chave", "nome_publico"]
        marcadores = ", ".join(["%s"] * len(cols))
        sql = f"INSERT INTO cert_history ({', '.join(cols)}) VALUES ({marcadores})"
        cur.executemany(sql, [tuple(n.get(c) for c in cols) for n in novas])
        cur.execute("ALTER TABLE cert_history ALTER COLUMN arquivo_chave SET NOT NULL, "
                    "ALTER COLUMN nome_publico SET NOT NULL")
        cur.execute("ALTER TABLE cert_history ADD PRIMARY KEY (arquivo_chave)")
        cur.execute("CREATE INDEX IF NOT EXISTS cert_history_nome_publico_idx ON cert_history (nome_publico)")

        # 3. cert_snapshots: itens sanitizados, snapshot a snapshot.
        cur.execute("SELECT id, items FROM cert_snapshots")
        linhas = cur.fetchall()
        alterados = 0
        for sid, items in linhas:
            novos, brutos = sanitizar_itens(items or [])
            if brutos:
                cur.execute("UPDATE cert_snapshots SET items = %s WHERE id = %s", (json.dumps(novos, ensure_ascii=False), sid))
                alterados += 1

        depois_h = _um(cur, SQL_CONTA_SENHA_HISTORY_NOVO)
        depois_s = _um(cur, SQL_CONTA_SENHA_SNAPSHOTS)
        depois_tok = _um(cur, SQL_CONTA_TOKEN_SNAPSHOTS)
        print(f"DEPOIS cert_history: {_um(cur, 'SELECT count(*) FROM cert_history')} linhas, "
              f"{depois_h} com token de senha em nome_publico/nome")
        print(f"DEPOIS cert_snapshots: {alterados} snapshots reescritos, {depois_s} itens com file_name/path, "
              f"{depois_tok} campos com token de senha (fora error_message)")
        if depois_s or depois_h or depois_tok:
            print("ATENCAO: ainda ha token de senha no banco. Confira as linhas antes de subir o codigo.")
            return 2
    conn.commit()
    print("commit feito.")
    return 0


def volta(conn) -> int:
    with conn.cursor() as cur:
        for bkp in (BKP_HISTORY, BKP_SNAPSHOTS):
            cur.execute("SELECT to_regclass(%s)", (bkp,))
            if cur.fetchone()[0] is None:
                print(f"sem {bkp}: não há de onde voltar.")
                return 1
        cur.execute("DROP TABLE cert_history")
        cur.execute(f"CREATE TABLE cert_history AS SELECT * FROM {BKP_HISTORY}")
        cur.execute("ALTER TABLE cert_history ADD PRIMARY KEY (file_name)")
        cur.execute("ALTER TABLE cert_history ALTER COLUMN machine_id SET NOT NULL, "
                    "ALTER COLUMN ultima_data_registrada SET NOT NULL, ALTER COLUMN updated_at SET NOT NULL")
        cur.execute("CREATE INDEX IF NOT EXISTS cert_history_status_idx ON cert_history (status_ultimo)")
        cur.execute("CREATE INDEX IF NOT EXISTS cert_history_vencimento_idx ON cert_history (vencimento_certificado)")
        cur.execute("CREATE INDEX IF NOT EXISTS cert_history_ultima_data_idx ON cert_history (ultima_data_registrada DESC)")
        cur.execute(f"UPDATE cert_snapshots s SET items = b.items FROM {BKP_SNAPSHOTS} b WHERE b.id = s.id")
        restaurados = cur.rowcount
        cur.execute(f"DROP TABLE {BKP_HISTORY}")
        cur.execute(f"DROP TABLE {BKP_SNAPSHOTS}")
        print(f"volta: cert_history restaurada ({_um(cur, 'SELECT count(*) FROM cert_history')} linhas, "
              f"{_um(cur, SQL_CONTA_SENHA_HISTORY)} com 'senh'); {restaurados} snapshots restaurados; backups removidos.")
    conn.commit()
    return 0


def main() -> int:
    # Console do Windows e cp1252: sem isto um acento na saida derruba o script.
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dsn", required=True, help="postgresql://usuario:senha@host:porta/banco (use uma CÓPIA primeiro)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--ida", action="store_true")
    g.add_argument("--volta", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    import psycopg

    with psycopg.connect(args.dsn) as conn:
        if args.volta:
            return volta(conn)
        return ida(conn, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
