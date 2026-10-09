"""Computadores e bandeja da estação (ADR 0002) — Frente 3, leva 2 (09/10/2026).

Saiu de `app/main.py` sem mudar comportamento. A bandeja entra com a conta
deste portal (`agent_devices`) e se apresenta pelo cabeçalho
`X-Device-Secret`; o vínculo pessoa↔computador (principal/empréstimo,
pendente até o administrador autorizar) mora em `app/computadores.py`.
"""

from __future__ import annotations

import hmac
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import agent_devices, computadores, config, nomes
from app.sessao import _erro_sem_banco, _sb_do_login, conta_ativa, require_admin, require_auth
from app import auth

logger = logging.getLogger("app.main")
router = APIRouter()


# ──────────────────────────────────────────────────────────────────────────
# Computadores (ADR 0002, 07/10/2026) — docs/adr/0002-vinculo-pessoa-computador.md
#
# A bandeja da estação entra com a conta deste portal (agent_devices) e se
# apresenta nas chamadas abaixo pelo cabeçalho `X-Device-Secret`. O vínculo
# (principal/empréstimo, pendente até o administrador autorizar) mora em
# app/computadores.py.
# ──────────────────────────────────────────────────────────────────────────

_TEXTO_AUTORIZACAO = {
    computadores.AUTORIZADO: "Computador autorizado.",
    computadores.PENDENTE: "Aguardando o administrador autorizar este computador.",
    "sem_pedido": "Este computador não está vinculado a você.",
}


def _texto_da_situacao(s: dict) -> dict:
    return {"autorizacao": s.get("autorizacao"), "tipo": s.get("tipo"), "expira_em": s.get("expira_em"),
            "mensagem": _TEXTO_AUTORIZACAO.get(s.get("autorizacao"), "")}


def _dispositivo_da_requisicao(request: Request) -> dict:
    segredo = (request.headers.get("x-device-secret") or "").strip()
    if not segredo:
        raise HTTPException(status_code=401, detail="Bandeja sem credencial deste portal. Entre de novo.")
    try:
        disp = agent_devices.autenticar(segredo, versao=request.headers.get("x-agent-version"))
    except agent_devices.SemBanco as e:
        raise _erro_sem_banco(e)
    if not disp:
        raise HTTPException(status_code=401, detail="Sessão da bandeja encerrada. Entre de novo.")
    return disp


@router.get("/api/estacao/situacao")
def estacao_situacao(request: Request) -> dict:
    """A bandeja pergunta: posso receber instalação aqui?"""
    disp = _dispositivo_da_requisicao(request)
    try:
        s = computadores.situacao(str(disp["user_id"]), disp["machine_id"])
    except computadores.SemBanco as e:
        raise _erro_sem_banco(e)
    return {"machine_id": disp["machine_id"], **_texto_da_situacao(s)}


@router.get("/api/estacao/instalacoes")
def estacao_instalacoes(request: Request) -> dict:
    """Tokens de instalação desta máquina (uma vez cada). Só com vínculo autorizado."""
    disp = _dispositivo_da_requisicao(request)
    try:
        s = computadores.situacao(str(disp["user_id"]), disp["machine_id"])
        if s["autorizacao"] != computadores.AUTORIZADO:
            return {"tokens": [], **_texto_da_situacao(s)}
        return {"tokens": computadores.entregar(disp["machine_id"]), **_texto_da_situacao(s)}
    except computadores.SemBanco as e:
        raise _erro_sem_banco(e)


@router.post("/api/estacao/sair")
def estacao_sair(request: Request) -> dict:
    """A pessoa saiu da bandeja: a credencial desta máquina deixa de valer."""
    disp = _dispositivo_da_requisicao(request)
    agent_devices.revogar(str(disp["id"]))
    return {"ok": True}


def _nomes_das_pessoas() -> Dict[str, dict]:
    sb = _sb_do_login()
    linhas = sb.table("users").select("id, email, full_name, role").execute().data or []
    return {str(l["id"]): l for l in linhas}


@router.get("/api/computadores", dependencies=[Depends(require_admin)])
def listar_computadores() -> dict:
    """Usuários › Computadores: pendentes no topo, ativos, histórico."""
    try:
        vinculos = computadores.listar()
        dispositivos = agent_devices.listar()
    except (computadores.SemBanco, agent_devices.SemBanco) as e:
        raise _erro_sem_banco(e)
    pessoas = _nomes_das_pessoas()
    ativos_por_par = {(str(d["user_id"]), computadores.mac(d["machine_id"])): d
                      for d in dispositivos if not d.get("revogado_em")}
    for v in vinculos:
        p = pessoas.get(str(v["user_id"]), {})
        v["email"] = p.get("email", "")
        v["pessoa"] = nomes.nome_pessoa(p.get("full_name") or p.get("email"))
        d = ativos_por_par.get((str(v["user_id"]), computadores.mac(v["machine_id"])))
        v["na_bandeja"] = bool(d)
        v["vivo"] = bool(d and d.get("vivo"))
        v["versao"] = (d or {}).get("versao") or ""
    resumo = {"pendentes": sum(1 for v in vinculos if v["estado"] == computadores.PENDENTE)}
    return {"itens": vinculos, "resumo": resumo}


class DecisaoComputadorBody(BaseModel):
    tipo: str = Field(pattern=r"^(principal|emprestimo)$")
    prazo: Optional[str] = Field(default=None, pattern=r"^(fim_do_dia|3_dias|7_dias)$")


def _id_do_vinculo(vinculo_id: str) -> Any:
    v = (vinculo_id or "").strip()
    if not v or len(v) > 64:
        raise HTTPException(status_code=404, detail="Vínculo não encontrado.")
    return int(v) if v.isdigit() else v


def _decidir(fn, *args) -> dict:
    try:
        return fn(*args)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except computadores.VinculoInvalido as e:
        raise HTTPException(status_code=409, detail=str(e))
    except computadores.SemBanco as e:
        raise _erro_sem_banco(e)


@router.post("/api/computadores/{vinculo_id}/autorizar", dependencies=[Depends(require_admin)])
def autorizar_computador(vinculo_id: str, body: DecisaoComputadorBody,
                         token: auth.TokenData = Depends(require_auth)) -> dict:
    return _decidir(computadores.autorizar, _id_do_vinculo(vinculo_id), body.tipo, (token.email or "").lower(), body.prazo)


@router.post("/api/computadores/{vinculo_id}/recusar", dependencies=[Depends(require_admin)])
def recusar_computador(vinculo_id: str, token: auth.TokenData = Depends(require_auth)) -> dict:
    return _decidir(computadores.recusar, _id_do_vinculo(vinculo_id), (token.email or "").lower())


@router.post("/api/computadores/{vinculo_id}/desvincular", dependencies=[Depends(require_admin)])
def desvincular_computador(vinculo_id: str, token: auth.TokenData = Depends(require_auth)) -> dict:
    return _decidir(computadores.desvincular, _id_do_vinculo(vinculo_id), (token.email or "").lower())


@router.post("/api/computadores/importar-do-hardlyze", dependencies=[Depends(require_admin)])
def importar_computadores_do_hardlyze() -> dict:
    """Transição (ADR 0002): logins atuais do Hardlyze viram pedidos pendentes."""
    if not config.ponte_invent_configurada():
        raise HTTPException(status_code=409, detail="A ponte com o Hardlyze não está configurada (INVENT_API_URL / CERT_PORTAL_TOKEN).")
    try:
        import httpx

        r = httpx.get(f"{config.INVENT_API_URL}/api/agent/devices/todos",
                      headers={"Authorization": f"Bearer {config.CERT_PORTAL_TOKEN}"}, timeout=15.0)
    except Exception:  # noqa: BLE001
        logger.warning("Hardlyze indisponível na importação de computadores", exc_info=True)
        raise HTTPException(status_code=502, detail="O Hardlyze não respondeu. Tente de novo em instantes.")
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"O Hardlyze respondeu {r.status_code} (atualizado para a versão com a rota de importação?).")
    logins = list((r.json() or {}).get("dispositivos") or [])
    pessoas = _nomes_das_pessoas()
    sb = _sb_do_login()
    ativos = {str(u["id"]) for u in (sb.table("users").select("id, ativo").execute().data or []) if conta_ativa(u)}
    por_email = {str(p.get("email") or "").strip().lower(): uid for uid, p in pessoas.items() if uid in ativos}
    try:
        res = computadores.importar(logins, por_email)
    except computadores.SemBanco as e:
        raise _erro_sem_banco(e)
    from app import texto as _texto
    return {**res, "message": (f"{_texto.plural(res['criados'], 'pedido criado', 'pedidos criados')}; "
                               f"{_texto.plural(res['pulados'], 'já existia', 'já existiam')}; "
                               f"{_texto.plural(res['sem_conta'], 'login sem conta neste portal', 'logins sem conta neste portal')}.")}


@router.get("/api/computadores/principais")
def computadores_principais(request: Request) -> dict:
    """Para o Hardlyze (ponte servidor a servidor): máquina → dono principal."""
    esperado = (config.CERT_PORTAL_TOKEN or "").strip()
    recebido = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
    if not esperado or not hmac.compare_digest(recebido.encode("utf-8"), esperado.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Não autorizado.")
    try:
        pessoas = _nomes_das_pessoas()
        saida = []
        for pr in computadores.principais():
            p = pessoas.get(pr["user_id"], {})
            saida.append({"machine_id": pr["machine_id"], "email": p.get("email", ""),
                          "nome": nomes.nome_pessoa(p.get("full_name") or p.get("email")), "desde": pr.get("desde")})
    except computadores.SemBanco as e:
        raise _erro_sem_banco(e)
    return {"principais": saida}
