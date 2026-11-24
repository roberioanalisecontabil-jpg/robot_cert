"""Chaves de API de leitura do administrador (24/11/2026). Regra em `app/api_chaves.py`.

Criar pede a senha atual, como o app autenticador: com a sessão aberta e a
máquina destravada, quem sentasse na cadeira levaria uma chave de admin.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import api_chaves, auth, taxa
from app.rotas.autenticador import _exigir_senha, _minha_conta
from app.sessao import require_admin

logger = logging.getLogger("app.main")
router = APIRouter()


class CriarBody(BaseModel):
    nome: str = Field(max_length=80)
    dias: int = Field(ge=1, le=api_chaves.DIAS_MAXIMO)
    senha_atual: str = Field(max_length=1024)


@router.get("/api/api-chaves")
def listar(token: auth.TokenData = Depends(require_admin)) -> dict:
    try:
        chaves = api_chaves.listar()
    except api_chaves.SemBanco as e:
        raise HTTPException(status_code=503, detail=str(e))
    from app.settings_state import _banco

    ids = sorted({c["user_id"] for c in chaves if c.get("user_id")})
    donos = {}
    if ids:
        donos = {str(u["id"]): u.get("email") for u in
                 (_banco().table("users").select("id, email").in_("id", ids).execute().data or [])}
    return {"chaves": [{**c, "dono": donos.get(str(c.get("user_id")), "")} for c in chaves]}


@router.post("/api/api-chaves")
def criar(body: CriarBody, token: auth.TokenData = Depends(require_admin)) -> dict:
    sb, user = _minha_conta(token)
    if not taxa.permitir(f"api-chave-senha:{user['id']}", 10, 900):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde alguns minutos.")
    _exigir_senha(user, body.senha_atual)
    try:
        return api_chaves.criar(str(user["id"]), body.nome, body.dias)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/api-chaves/{chave_id}/revogar")
def revogar(chave_id: str, token: auth.TokenData = Depends(require_admin)) -> dict:
    if not api_chaves.revogar(chave_id):
        raise HTTPException(status_code=404, detail="Chave não encontrada ou já revogada.")
    logger.info("Chave de API %s revogada por %s.", chave_id, token.email)
    return {"ok": True}
