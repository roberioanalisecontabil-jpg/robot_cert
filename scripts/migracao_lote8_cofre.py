"""
Migração do lote 8 da auditoria (SECURITY_AUDIT #19, #42, #55): o cofre ganha
versão da chave da SENHA e versão do ENVELOPE (AAD).

O que muda no banco (ida): duas colunas em `cert_pfx_store`, com DEFAULT que
descreve o que já está gravado — `password_key_version = 1` e `aad_version = 0`.
Nenhuma linha é reescrita na ida. Quem reprocessa o material é `--recifrar`
(o mesmo código do botão "Recifrar cofre" do portal), linha a linha e só
depois de decifrar com sucesso; linha ilegível fica como está e é listada.

Como usar (SEMPRE numa cópia antes; nunca direto em produção sem o ensaio):

    python scripts/migracao_lote8_cofre.py --dsn postgresql://... --dry-run
    python scripts/migracao_lote8_cofre.py --dsn postgresql://... --ida
    python scripts/migracao_lote8_cofre.py --dsn postgresql://... --recifrar
    python scripts/migracao_lote8_cofre.py --dsn postgresql://... --volta

`--recifrar` e `--volta` precisam das chaves do cofre: rode na máquina que
tem o `.env` do portal (o script carrega `app.config`). `--ida` e `--dry-run`
não precisam de chave nenhuma.

Volta: o código anterior ao lote 8 não sabe ler AAD nem versão da senha, então
`--volta` (1) recifra cada linha com `aad_version = 1` de volta ao envelope
antigo, sob as chaves EM VIGOR, gravando `key_version = 1` — que é como o
código antigo interpreta CERT_ENCRYPTION_KEY — e (2) remove as duas colunas.
Se uma linha não decifrar, a volta PARA sem gravar nada (transação), porque
deixar meia tabela no envelope antigo é pior que não voltar.

Ordem de implantação: rodar `--ida` e SÓ DEPOIS subir o código do lote 8 (o
upsert novo grava as colunas). O código antigo ignora as colunas, então a
migration pode ir na frente sem janela.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

COLUNAS = {"password_key_version": "INTEGER NOT NULL DEFAULT 1", "aad_version": "INTEGER NOT NULL DEFAULT 0"}

SQL_CONTAGENS = (
    "SELECT count(*), "
    "count(*) FILTER (WHERE password_key_version = 1), "
    "count(*) FILTER (WHERE aad_version = 0) "
    "FROM cert_pfx_store"
)


def _um(cur, sql: str, params: Any = None) -> Any:
    cur.execute(sql, params)
    return cur.fetchone()[0]


def _colunas_presentes(cur) -> List[str]:
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'cert_pfx_store' AND column_name = ANY(%s)",
        (list(COLUNAS),),
    )
    return sorted(r[0] for r in cur.fetchall())


def _por_versao(cur) -> Dict[str, int]:
    cur.execute("SELECT key_version, count(*) FROM cert_pfx_store GROUP BY 1 ORDER BY 1")
    return {str(k): int(n) for k, n in cur.fetchall()}


def ida(conn, dry_run: bool) -> int:
    with conn.cursor() as cur:
        total = _um(cur, "SELECT count(*) FROM cert_pfx_store")
        presentes = _colunas_presentes(cur)
        print(f"ANTES  cert_pfx_store: {total} linhas; key_version: {_por_versao(cur)}; "
              f"colunas do lote 8 presentes: {presentes or 'nenhuma'}")
        faltam = [c for c in COLUNAS if c not in presentes]
        if not faltam:
            print("As duas colunas já existem. Nada a fazer.")
            return 0
        print(f"PLANO  acrescentar {faltam} (DEFAULT descreve o que já está gravado; nenhuma linha reescrita)")
        if dry_run:
            print("dry-run: nada gravado.")
            return 0
        for c in faltam:
            cur.execute(f"ALTER TABLE cert_pfx_store ADD COLUMN IF NOT EXISTS {c} {COLUNAS[c]}")
        cur.execute(SQL_CONTAGENS)
        t, senha_v1, sem_aad = cur.fetchone()
        print(f"DEPOIS cert_pfx_store: {t} linhas, {senha_v1} com senha v1, {sem_aad} sem AAD (os três têm de ser iguais)")
        if not (t == senha_v1 == sem_aad):
            print("ATENCAO: contagens divergem; revertendo.")
            conn.rollback()
            return 2
    conn.commit()
    print("commit feito.")
    return 0


def _com_app(dsn: str):
    """Aponta o portal para o DSN e devolve `app.cert_installer` (usa o .env para as chaves)."""
    os.environ["DATABASE_URL"] = dsn
    from app import cert_installer as ci  # noqa: E402

    return ci


def recifrar(conn, dsn: str) -> int:
    """O mesmo `recifrar_cofre` do portal, em lotes, até zerar."""
    ci = _com_app(dsn)
    with conn.cursor() as cur:
        total = _um(cur, "SELECT count(*) FROM cert_pfx_store")
        cur.execute(SQL_CONTAGENS)
        _, senha_v1, sem_aad = cur.fetchone()
        print(f"ANTES  {total} linhas; key_version: {_por_versao(cur)}; senha v1: {senha_v1}; sem AAD: {sem_aad}")
    conn.commit()
    recifradas = 0
    falhas: Dict[str, Dict[str, str]] = {}
    try:
        while True:
            # Cada chamada tenta as primeiras `limite` candidatas; as que falham
            # continuam candidatas, então o laço termina quando um lote inteiro
            # não avança — e a essa altura o que sobrou é o que não decifra.
            r = ci.recifrar_cofre(limite=200)
            recifradas += r["recifradas"]
            for f in r["falhas"]:
                falhas[f["fingerprint"] + "|" + str(f.get("machine_id"))] = f
            print(f"lote: {r['recifradas']} recifradas, {len(r['falhas'])} falhas, restam {r['restantes']}")
            if r["recifradas"] == 0:
                restantes = r["restantes"]
                break
    finally:
        # O cliente do portal abre um pool de conexões; sem fechar, o processo
        # fica preso nos threads do pool ao sair.
        try:
            ci._banco().fechar()
        except Exception:  # noqa: BLE001
            pass
    with conn.cursor() as cur:
        cur.execute(SQL_CONTAGENS)
        t, senha_v1, sem_aad = cur.fetchone()
        print(f"DEPOIS {t} linhas; key_version: {_por_versao(cur)}; senha v1: {senha_v1}; sem AAD: {sem_aad}; "
              f"recifradas no total: {recifradas}")
    if restantes:
        print(f"ATENCAO: {restantes} linha(s) nao decifram com as chaves do ambiente e ficaram como estavam. "
              f"Exemplos (ate 20 de {len(falhas)} vistas):")
        for f in list(falhas.values())[:20]:
            print(f"  {f['fingerprint']}... ({f.get('machine_id')}): {f['motivo']}")
        return 2
    return 0


def volta(conn, dsn: str) -> int:
    ci = _com_app(dsn)
    with conn.cursor() as cur:
        presentes = _colunas_presentes(cur)
        if not presentes:
            print("Colunas do lote 8 não existem: nada de onde voltar.")
            return 1
        cur.execute("SELECT * FROM cert_pfx_store WHERE aad_version >= 1 OR password_key_version <> 1 OR key_version <> 1")
        colunas = [d[0] for d in cur.description]
        linhas = [dict(zip(colunas, r)) for r in cur.fetchall()]
        total = _um(cur, "SELECT count(*) FROM cert_pfx_store")
        print(f"ANTES  {total} linhas; {len(linhas)} a levar de volta ao envelope antigo")
        regravadas = 0
        for row in linhas:
            try:
                pfx = ci.decifrar_pfx_da_linha(row)
                senha = ci.decifrar_senha_da_linha(row)
            except Exception as e:  # noqa: BLE001
                print(f"NAO decifra {str(row.get('fingerprint'))[:16]}...: {ci.descrever_falha_de_decifra(e)}. "
                      "Volta abortada sem gravar nada.")
                conn.rollback()
                return 2
            # Envelope antigo: sem AAD, sob as chaves EM VIGOR, rotuladas como
            # v1 — é assim que o código anterior ao lote 8 lê CERT_ENCRYPTION_KEY.
            ct, iv, tag = ci.encrypt_pfx_at_rest(pfx)
            campos = {"encrypted_pfx": ct, "pfx_iv": iv, "pfx_auth_tag": tag, "key_version": 1}
            if senha is not None:
                pct, piv, ptag = ci.encrypt_password_at_rest(senha)
                campos.update({"pfx_password_enc": pct, "pfx_password_iv": piv, "pfx_password_tag": ptag})
            sets = ", ".join(f"{k} = %s" for k in campos)
            cur.execute(f"UPDATE cert_pfx_store SET {sets} WHERE id = %s", (*campos.values(), row["id"]))
            regravadas += 1
        for c in presentes:
            cur.execute(f"ALTER TABLE cert_pfx_store DROP COLUMN IF EXISTS {c}")
        print(f"DEPOIS {_um(cur, 'SELECT count(*) FROM cert_pfx_store')} linhas; {regravadas} regravadas no envelope antigo; "
              f"key_version: {_por_versao(cur)}; colunas removidas: {presentes}")
    conn.commit()
    try:
        ci._banco().fechar()
    except Exception:  # noqa: BLE001
        pass
    print("commit feito. Lembre: o código antigo lê tudo com CERT_ENCRYPTION_KEY/CERT_PASSWORD_ENCRYPTION_KEY em vigor.")
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
    g.add_argument("--recifrar", action="store_true")
    g.add_argument("--volta", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    import psycopg

    with psycopg.connect(args.dsn) as conn:
        if args.volta:
            return volta(conn, args.dsn)
        if args.recifrar:
            return recifrar(conn, args.dsn)
        return ida(conn, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
