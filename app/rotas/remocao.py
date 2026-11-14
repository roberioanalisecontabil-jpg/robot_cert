"""Rotas da remoção de certificados nas estações (Frente B, 14/11/2026).

Spec: docs/superpowers/specs/2026-11-13-carteira-certificados-remocao-uso-design.md,
"Frente B". A bandeja manda o que tem no `CurrentUser\\My` e o que fez na
rodada anterior; o portal responde o que sai, o que vai sair e as liberações
que vencem logo. A decisão mora em `app/remocao.py`.

- `/api/estacao/conferencia`: a bandeja logada (`X-Device-Secret` ativo).
- `/api/estacao/conferencia/sem-conta`: perfil sem login. Com `segredo`, o
  último dono do perfil decide, mesmo revogado: aqui o segredo só serve para
  mandar remover, não autentica mais nada. Sem `segredo`, a regra do perfil
  sem login. A máquina sem chave fixada é aceita (computador nunca aprovado):
  o pior vazamento é confirmar que um certificado que a pessoa tem é da empresa.
- `/api/remocao`: o relatório para o Admin.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Annotated, Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, StringConstraints

from app import agent_devices, cert_installer as ci, computadores, nomes, remocao
from app.rotas.atualizacao import _limitar
from app.rotas.computadores import _dispositivo_da_requisicao
from app.sessao import _sb_do_login, require_admin

logger = logging.getLogger("app.main")
router = APIRouter()

PROXIMA_EM = 300
POR_PAGINA = 50
ESTADOS = ("removeria", "aviso", "remover", "removido", "falhou")
_TETO_SEM_CONTA = (30, 600)
_FORA = "Não foi possível conferir agora."

Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class Resultado(BaseModel):
    fingerprint: Fingerprint
    ok: bool
    erro: str = Field(default="", max_length=500)


class Conferencia(BaseModel):
    # Duas grafias do mesmo usuário do Windows são a mesma linha e o mesmo prazo.
    usuario_windows: Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True,
                                                      min_length=1, max_length=256)]
    certificados: List[Fingerprint] = Field(max_length=500)
    resultados: List[Resultado] = Field(default_factory=list, max_length=500)


class ConferenciaSemConta(Conferencia):
    machine_id: str = Field(min_length=1, max_length=64)
    chave: Optional[str] = Field(default=None, max_length=256)
    segredo: Optional[str] = Field(default=None, max_length=256)


def _nomes_por(coluna: str, valores: List[str]) -> Dict[str, str]:
    """`coluna` (fingerprint ou documento) -> nome_titular, numa consulta só."""
    alvo = sorted({v for v in valores if v})
    if not alvo:
        return {}
    linhas = (ci._banco().table("cert_pfx_store").select(f"{coluna}, nome_titular")
              .in_(coluna, alvo).execute().data or [])
    return {str(l.get(coluna)): l["nome_titular"] for l in linhas if l.get("nome_titular")}


def _conferir(machine_id: str, corpo: Conferencia, user: Optional[Dict[str, Any]], modo: str,
              decidir: Callable[[], list], com_vencendo: bool) -> dict:
    """Registra a rodada anterior, decide e aplica, nesta ordem. Toda leitura vem
    antes de `aplicar`: se ela falha, o 503 sai sem relógio de aviso começado.
    Qualquer falha vira 503: nunca uma resposta com listas pela metade."""
    uid = str(user["id"]) if user else None
    try:
        remocao.registrar_resultado(machine_id, corpo.usuario_windows, uid, (user or {}).get("email"),
                                    [r.model_dump() for r in corpo.resultados])
        decisoes = decidir() if modo != "desligado" else []
        por_fp = _nomes_por("fingerprint", [d.fingerprint.strip().lower() for d in decisoes])
        vence = remocao.vencendo(uid, date.today()) if com_vencendo and modo == "ligado" else []
        por_doc = _nomes_por("documento", [str(v["documento"]) for v in vence])
        saida = remocao.aplicar(machine_id, corpo.usuario_windows, uid, decisoes, modo,
                                datetime.now(timezone.utc))
    except Exception:  # noqa: BLE001
        logger.exception("Remoção: conferência de %s falhou", computadores.mac(machine_id))
        raise HTTPException(status_code=503, detail=_FORA) from None
    for i in saida["remover"] + saida["avisos"]:
        i["nome"] = por_fp.get(i["fingerprint"]) or i.get("documento") or ""
    resposta = {"remover": saida["remover"], "avisos": saida["avisos"]}
    if com_vencendo:
        resposta["vencendo"] = [{**v, "nome": por_doc.get(str(v["documento"])) or v["documento"]}
                                for v in vence]
    return {**resposta, "proxima_em": PROXIMA_EM}


def _pessoa(user_id: str) -> Optional[Dict[str, Any]]:
    linhas = (_sb_do_login().table("users").select("id, email, role, ativo")
              .eq("id", str(user_id)).limit(1).execute().data or [])
    return linhas[0] if linhas else None


@router.post("/api/estacao/conferencia")
def conferencia(corpo: Conferencia, request: Request) -> dict:
    disp = _dispositivo_da_requisicao(request)
    try:
        user = _pessoa(disp["user_id"])
        modo = remocao.modo_carteira()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=_FORA) from None
    if not user:
        raise HTTPException(status_code=403, detail="Conta sem acesso ao portal.")
    mid = disp["machine_id"]
    return _conferir(mid, corpo, user, modo,
                     lambda: remocao.decidir_pessoa(user, mid, corpo.certificados, datetime.now(timezone.utc)),
                     com_vencendo=True)


@router.post("/api/estacao/conferencia/sem-conta")
def conferencia_sem_conta(corpo: ConferenciaSemConta, request: Request) -> dict:
    _limitar(request, "conferencia", _TETO_SEM_CONTA)
    mid = corpo.machine_id
    try:
        fixada = computadores.chave_fixada(mid)
        provada = not fixada or computadores._maquina_provada(mid, computadores.hash_da_chave(corpo.chave))
        dono = agent_devices.dono_do_segredo(corpo.segredo) if corpo.segredo else None
        user = _pessoa(dono["user_id"]) if dono else None
        modo = remocao.modo_carteira() if corpo.segredo else remocao.modo_sem_login()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=_FORA) from None
    if not provada:
        raise HTTPException(status_code=403, detail="Chave da máquina não confere.")
    if not corpo.segredo:
        return _conferir(mid, corpo, None, modo, lambda: remocao.decidir_sem_login(corpo.certificados),
                         com_vencendo=False)
    # O segredo só vale na máquina em que foi emitido, e só se a pessoa ainda existe.
    if not dono or computadores.mac(dono.get("machine_id")) != computadores.mac(mid) or not user:
        raise HTTPException(status_code=403, detail="Credencial da bandeja não confere.")
    return _conferir(mid, corpo, user, modo,
                     lambda: remocao.decidir_pessoa(user, mid, corpo.certificados, datetime.now(timezone.utc)),
                     com_vencendo=False)


@router.get("/api/remocao", dependencies=[Depends(require_admin)])
def relatorio(estado: Optional[str] = Query(default=None, pattern="^(" + "|".join(ESTADOS) + ")$"),
              pagina: int = Query(default=1, ge=1)) -> dict:
    """As linhas de `remocao_estacao`, mais recentes primeiro, com a pessoa e o titular."""
    inicio = (pagina - 1) * POR_PAGINA
    try:
        q = ci._banco().table("remocao_estacao").select("*")
        if estado:
            q = q.eq("estado", estado)
        linhas = (q.order("atualizado_em", desc=True).range(inicio, inicio + POR_PAGINA - 1)
                  .execute().data or [])
        ids = sorted({str(l["user_id"]) for l in linhas if l.get("user_id")})
        pessoas = {str(p["id"]): p for p in (_sb_do_login().table("users").select("id, email, full_name")
                                             .in_("id", ids).execute().data or [])} if ids else {}
        titulares = _nomes_por("fingerprint", [l.get("fingerprint") for l in linhas])
    except Exception:  # noqa: BLE001
        logger.exception("Remoção: relatório ilegível")
        raise HTTPException(status_code=503, detail="Não foi possível ler o relatório agora.") from None
    itens = []
    for l in linhas:
        p = pessoas.get(str(l.get("user_id"))) or {}
        itens.append({**l, "pessoa": nomes.nome_pessoa(p.get("full_name")) or p.get("email") or "",
                      "titular": titulares.get(str(l.get("fingerprint"))) or l.get("documento") or ""})
    return {"itens": itens, "pagina": pagina, "por_pagina": POR_PAGINA}
