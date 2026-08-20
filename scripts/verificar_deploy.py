"""Confere o que está realmente no ar depois de um deploy.

Compara o que o portal publicado responde com o que a versão atual do código
deveria responder, e diz o que falta — em vez de exigir comparação campo a
campo na mão.

Uso:
    python scripts/verificar_deploy.py
    python scripts/verificar_deploy.py https://outro-ambiente.exemplo.com
    python scripts/verificar_deploy.py --json      # saída para script/CI

Código de saída: 0 se tudo certo, 1 se houver problema. Serve em CI.

Só usa a biblioteca padrão de propósito: precisa rodar em qualquer máquina,
inclusive uma sem o venv do projeto montado.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

URL_PADRAO = "https://certificado.analisegroup.cnt.br"

# Campos que /api/health passou a devolver no commit c28f98a. A ausência deles
# não é "configuração faltando": é deploy velho, anterior a esse commit.
CAMPOS_HEALTH = {
    "ok": "portal respondendo",
    "supabase": "credenciais do Supabase presentes",
    "api_key_required": "X-API-Key exigida nas rotas de máquina",
    "cert_vault_key_configurada": "CERT_ENCRYPTION_KEY — sem ela o cofre falha no primeiro upload",
    "smtp_key_dedicada": "ENCRYPTION_KEY — sem ela o portal nem sobe (código novo)",
    "jwt_configurado": "JWT_SECRET_KEY presente",
}

# Campos cuja ausência data o deploy como anterior a c28f98a.
CAMPOS_DO_CODIGO_NOVO = [
    "cert_vault_key_configurada",
    "smtp_key_dedicada",
    "jwt_configurado",
]

ROTAS_ESPERADAS = [
    "/api/health",
    "/api/cert-installer/vault-optin",
    "/api/cert-installer/upload-pfx",
]

# Rotas que precisam estar AUSENTES. A lista existe porque a verificação só
# olhava para o que falta, e removeu-se coisa de propósito.
#
# `/api/cert-installer/prepare` saiu em 16/08/2026 por decisão de segurança:
# emitia token de instalação para um caminho que ninguém usa, e um token É a
# entrega da chave privada. Ela ficou em ROTAS_ESPERADAS depois disso, então
# todo deploy saudável era reportado como "há divergência" — e um verificador
# que acusa deploy bom treina quem o roda a ignorá-lo.
#
# Invertida, a mesma linha passa a valer alguma coisa: se a rota reaparecer num
# merge ou num revert, isto acusa.
ROTAS_PROIBIDAS = [
    "/api/cert-installer/prepare",
]

# Marcadores do painel de opt-in (commit c28f98a). Confirmam que o template
# novo subiu — o health sozinho não prova isso.
MARCADORES_PAINEL = [
    "tblOptinCerts",
    "loadOptinPanel",
    "_optinMachineId",  # veio na correção do machine_id (4a01127)
]


class Problema(Exception):
    pass


def _buscar(url: str, timeout: int = 25) -> tuple[int, str, dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "verificar-deploy/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace"), dict(e.headers)
    except Exception as e:
        raise Problema(f"não foi possível alcançar {url}: {e}") from e


def _e_pagina_de_protecao(corpo: str) -> bool:
    """
    Deployment Protection do Vercel devolve HTTP 200 com a página de login.

    Sem esta checagem o script leria "200 OK" e diria que está tudo bem, quando
    na verdade nem chegou no app — foi o que aconteceu ao testar a URL
    `*.vercel.app` de um deployment protegido.
    """
    return "Log in to Vercel" in corpo or "sso-api" in corpo


def verificar(base: str) -> dict:
    base = base.rstrip("/")
    resultado: dict = {"url": base, "erros": [], "avisos": [], "ok": True}

    # ── 1. /api/health ────────────────────────────────────────────────────
    status, corpo, headers = _buscar(f"{base}/api/health")
    resultado["http_status"] = status
    # Cabeçalhos HTTP são case-insensitive, mas o dict que vem do urllib
    # preserva a caixa do servidor ("Server", não "server").
    minusculos = {k.lower(): v for k, v in headers.items()}
    resultado["hospedagem"] = minusculos.get("server", "?")

    if _e_pagina_de_protecao(corpo):
        resultado["erros"].append(
            "a URL devolveu a página de login do Vercel (Deployment Protection). "
            "Não é o app — use o domínio de produção, não a URL do deployment."
        )
        resultado["ok"] = False
        return resultado

    if status != 200:
        resultado["erros"].append(f"/api/health devolveu HTTP {status}")
        resultado["ok"] = False
        return resultado

    try:
        health = json.loads(corpo)
    except json.JSONDecodeError:
        resultado["erros"].append("/api/health não devolveu JSON — o portal pode não ter subido")
        resultado["ok"] = False
        return resultado

    resultado["health"] = health

    ausentes = [c for c in CAMPOS_DO_CODIGO_NOVO if c not in health]
    if ausentes:
        resultado["erros"].append(
            "DEPLOY VELHO: faltam os campos "
            + ", ".join(ausentes)
            + " em /api/health. Esses campos existem desde o commit c28f98a, "
            "então o que está no ar é anterior a ele."
        )
        resultado["ok"] = False

    for campo, descricao in CAMPOS_HEALTH.items():
        if campo not in health:
            continue
        if health[campo] is False:
            gravidade = "erros" if campo in ("ok", "smtp_key_dedicada") else "avisos"
            resultado[gravidade].append(f"{campo} = false — {descricao}")
            if gravidade == "erros":
                resultado["ok"] = False

    # ── 2. rotas declaradas ───────────────────────────────────────────────
    try:
        status_o, corpo_o, _ = _buscar(f"{base}/openapi.json")
        if status_o == 200:
            spec = json.loads(corpo_o)
            resultado["versao"] = spec.get("info", {}).get("version", "?")
            caminhos = set(spec.get("paths", {}))
            faltando = [r for r in ROTAS_ESPERADAS if r not in caminhos]
            if faltando:
                resultado["erros"].append("rotas ausentes: " + ", ".join(faltando))
                resultado["ok"] = False

            ressuscitadas = [r for r in ROTAS_PROIBIDAS if r in caminhos]
            if ressuscitadas:
                resultado["erros"].append(
                    "rotas que deveriam estar removidas voltaram ao ar: "
                    + ", ".join(ressuscitadas)
                )
                resultado["ok"] = False
        else:
            resultado["avisos"].append(f"/openapi.json indisponível (HTTP {status_o})")
    except Problema as e:
        resultado["avisos"].append(str(e))

    # ── 3. painel de opt-in no template ───────────────────────────────────
    try:
        status_i, corpo_i, _ = _buscar(f"{base}/instalador")
        if status_i == 200:
            faltando = [m for m in MARCADORES_PAINEL if m not in corpo_i]
            if faltando:
                resultado["erros"].append(
                    "o template do instalador está desatualizado: sem "
                    + ", ".join(faltando)
                )
                resultado["ok"] = False
        else:
            resultado["avisos"].append(f"/instalador devolveu HTTP {status_i}")
    except Problema as e:
        resultado["avisos"].append(str(e))

    return resultado


def imprimir(r: dict) -> None:
    print("=" * 68)
    print(f"VERIFICACAO DE DEPLOY — {r['url']}")
    print("=" * 68)
    print(f"HTTP {r.get('http_status', '?')} | hospedagem: {r.get('hospedagem', '?')}"
          + (f" | versao {r['versao']}" if r.get("versao") else ""))

    if r.get("health"):
        print("\n/api/health:")
        for campo, desc in CAMPOS_HEALTH.items():
            if campo in r["health"]:
                v = r["health"][campo]
                marca = "ok " if v else "NAO"
                print(f"  [{marca}] {campo:28} = {v}")
            else:
                print(f"  [--- ] {campo:28}   AUSENTE (deploy velho)")

    if r["erros"]:
        print("\nPROBLEMAS:")
        for e in r["erros"]:
            print(f"  - {e}")
    if r["avisos"]:
        print("\nAvisos:")
        for a in r["avisos"]:
            print(f"  - {a}")

    print()
    print("=" * 68)
    if r["ok"]:
        print("RESULTADO: o deploy corresponde ao codigo atual.")
    else:
        print("RESULTADO: ha divergencia. Veja PROBLEMAS acima.")
        if any("DEPLOY VELHO" in e for e in r["erros"]):
            print()
            print("Antes de publicar a versao nova: defina ENCRYPTION_KEY no painel")
            print("do Vercel (chave Fernet de 44 chars). O codigo novo RECUSA subir")
            print("sem ela -- o portal cai se o deploy for feito antes.")
    print("=" * 68)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("url", nargs="?", default=URL_PADRAO, help=f"padrão: {URL_PADRAO}")
    p.add_argument("--json", action="store_true", help="saída em JSON, para CI")
    args = p.parse_args()

    try:
        r = verificar(args.url)
    except Problema as e:
        if args.json:
            print(json.dumps({"url": args.url, "ok": False, "erros": [str(e)]}, ensure_ascii=False))
        else:
            print(f"ERRO: {e}")
        return 1

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        imprimir(r)
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
