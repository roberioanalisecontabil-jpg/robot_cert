"""
Rotas da sincronização com o Acessórias (ADR 0005). Só Administrador.

A busca automática roda no `lifespan` (app/main.py); aqui ficam a situação,
o Buscar agora e a decisão sobre a busca que aguarda confirmação.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi import Path as PathParam

from app import acessorias, auth, config
from app.sessao import _limitar, require_admin

logger = logging.getLogger(__name__)

router = APIRouter()

BUSCA_ID = PathParam(..., ge=1)


def _buscar_em_segundo_plano(por_email: str) -> None:
    try:
        r = acessorias.buscar("botao", por_email)
        logger.info("Busca do Acessórias pelo botão (%s): %s", por_email, r.get("estado"))
    except Exception:  # noqa: BLE001
        logger.exception("Falha na busca do Acessórias pelo botão")


@router.get("/api/acessorias/situacao")
def acessorias_situacao(_: auth.TokenData = Depends(require_admin)) -> dict:
    try:
        return acessorias.situacao()
    except acessorias.ErroAcessorias as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/api/acessorias/buscar", status_code=202,
             dependencies=[Depends(_limitar("acessorias-buscar", 12, 3600))])
def acessorias_buscar(background: BackgroundTasks, token: auth.TokenData = Depends(require_admin)) -> dict:
    # Leva cerca de um minuto (30 chamadas por minuto): a tela acompanha pela
    # situação. Se já houver uma rodando, a de segundo plano volta "ocupada".
    if not config.ACESSORIAS_API_TOKEN:
        raise HTTPException(status_code=400, detail="O token do Acessórias não está configurado no servidor.")
    background.add_task(_buscar_em_segundo_plano, token.email)
    return {"ok": True, "message": "Busca iniciada. Leva cerca de um minuto."}


@router.post("/api/acessorias/buscas/{busca_id}/confirmar",
             dependencies=[Depends(_limitar("acessorias-decidir", 30, 3600))])
def acessorias_confirmar(busca_id: int = BUSCA_ID, token: auth.TokenData = Depends(require_admin)) -> dict:
    try:
        r = acessorias.confirmar(busca_id, token.email)
    except acessorias.ErroAcessorias as e:
        raise HTTPException(status_code=409, detail=str(e))
    res = r["resumo"]
    return {**r, "message": f"Aplicada: {res['entradas']} entradas e {res['saidas']} saídas."}


@router.post("/api/acessorias/buscas/{busca_id}/descartar",
             dependencies=[Depends(_limitar("acessorias-decidir", 30, 3600))])
def acessorias_descartar(busca_id: int = BUSCA_ID, token: auth.TokenData = Depends(require_admin)) -> dict:
    try:
        acessorias.descartar(busca_id, token.email)
    except acessorias.ErroAcessorias as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"ok": True, "message": "Busca descartada. Nada mudou nas carteiras."}
