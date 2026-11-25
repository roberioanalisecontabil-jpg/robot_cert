"""Meu perfil (25/11/2026): a própria pessoa troca nome, telefone e foto.

* O nome vale no portal e o login pela Microsoft não sobrescreve: ele só é
  gravado na criação da conta (`app/login_microsoft.py`). Grava em
  maiúsculas, como todo nome de pessoa desde 30/09/2026 (`app/nomes.py`).
* O telefone guarda só dígitos (DDD + número).
* A foto chega do navegador já cortada e reduzida; o servidor reabre com o
  Pillow e regrava em JPEG de no máximo 256px. Arquivo que não abre como
  imagem é recusado, e os metadados (EXIF com GPS, por exemplo) não passam.
  Só a própria pessoa lê a própria foto.
* A senha continua em `POST /api/senha/trocar` (app/rotas/usuarios.py).
"""

from __future__ import annotations

import base64
import io
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

from app import auth
from app.comum import _ler_upload_limitado
from app.sessao import SESSAO_ENCERRADA, _limitar, _sb_do_login, _user_id_da_sessao, require_auth

logger = logging.getLogger("app.main")
router = APIRouter()

FOTO_LADO = 256
NAO_GRAVOU = "Não foi possível gravar agora. Tente de novo em instantes."


def _uid(token: auth.TokenData) -> str:
    uid = _user_id_da_sessao(token)
    if not uid:
        raise HTTPException(status_code=401, detail=SESSAO_ENCERRADA)
    return str(uid)


def normalizar_nome(bruto: str) -> str:
    nome = re.sub(r"\s+", " ", bruto or "").strip()
    if any(ord(c) < 32 for c in nome):
        raise HTTPException(status_code=422, detail="O nome tem caracteres inválidos.")
    if not 2 <= len(nome) <= 120:
        raise HTTPException(status_code=422, detail="O nome precisa ter de 2 a 120 caracteres.")
    return nome.upper()


def normalizar_telefone(bruto: Optional[str]) -> Optional[str]:
    digitos = re.sub(r"\D", "", bruto or "")
    if digitos.startswith("55") and len(digitos) in (12, 13):
        digitos = digitos[2:]
    if not digitos:
        return None
    if len(digitos) not in (10, 11) or digitos[0] == "0":
        raise HTTPException(status_code=422, detail="Telefone com DDD: 10 ou 11 dígitos, como (82) 99999-9999.")
    return digitos


def reduzir_foto(dados: bytes) -> bytes:
    """Reabre a imagem e devolve um JPEG quadrado de até 256px, sem metadados."""
    from PIL import Image, ImageOps

    try:
        with Image.open(io.BytesIO(dados)) as img:
            img.load()
            img = ImageOps.exif_transpose(img)
            lado = min(img.size)
            esq, topo = (img.width - lado) // 2, (img.height - lado) // 2
            img = img.crop((esq, topo, esq + lado, topo + lado)).convert("RGB")
            img.thumbnail((FOTO_LADO, FOTO_LADO))
            saida = io.BytesIO()
            img.save(saida, "JPEG", quality=85, optimize=True)
            return saida.getvalue()
    except Exception:  # noqa: BLE001 — qualquer falha do Pillow é "não é imagem"
        raise HTTPException(status_code=422, detail="O arquivo não é uma imagem válida.") from None


class PerfilBody(BaseModel):
    nome: str = Field(max_length=200)
    telefone: Optional[str] = Field(default=None, max_length=40)


@router.get("/api/perfil")
def ler_perfil(token: auth.TokenData = Depends(require_auth)) -> dict:
    uid = _uid(token)
    sb = _sb_do_login()
    try:
        linhas = sb.table("users").select("email, full_name, telefone, role, origem").eq("id", uid).limit(1).execute().data or []
        foto = sb.table("usuario_foto").select("atualizada_em").eq("user_id", uid).limit(1).execute().data or []
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao ler o perfil")
        raise HTTPException(status_code=503, detail="Não foi possível ler o perfil agora.")
    if not linhas:
        raise HTTPException(status_code=401, detail=SESSAO_ENCERRADA)
    u = linhas[0]
    return {
        "email": u.get("email") or "",
        "nome": u.get("full_name") or "",
        "telefone": u.get("telefone") or "",
        "papel": u.get("role") or "",
        # Conta Microsoft não tem senha do portal: a senha é a da Microsoft.
        "microsoft": u.get("origem") == "microsoft",
        "foto_versao": str(foto[0]["atualizada_em"]) if foto else None,
    }


@router.put("/api/perfil", dependencies=[Depends(_limitar("perfil-salvar", 30, 3600))])
def salvar_perfil(body: PerfilBody, token: auth.TokenData = Depends(require_auth)) -> dict:
    uid = _uid(token)
    dados = {"full_name": normalizar_nome(body.nome), "telefone": normalizar_telefone(body.telefone)}
    try:
        _sb_do_login().table("users").update(dados).eq("id", uid).execute()
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao gravar o perfil")
        raise HTTPException(status_code=503, detail=NAO_GRAVOU)
    return {"ok": True, "nome": dados["full_name"], "telefone": dados["telefone"] or ""}


@router.put("/api/perfil/foto", dependencies=[Depends(_limitar("perfil-foto", 20, 3600))])
async def salvar_foto(request: Request, arquivo: UploadFile = File(...), token: auth.TokenData = Depends(require_auth)) -> dict:
    uid = _uid(token)
    jpeg = reduzir_foto(await _ler_upload_limitado(request, arquivo))
    agora = datetime.now(timezone.utc).isoformat()
    try:
        _sb_do_login().table("usuario_foto").upsert(
            {"user_id": uid, "jpeg_b64": base64.b64encode(jpeg).decode("ascii"), "atualizada_em": agora},
            on_conflict="user_id",
        ).execute()
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao gravar a foto")
        raise HTTPException(status_code=503, detail=NAO_GRAVOU)
    return {"ok": True, "foto_versao": agora}


@router.delete("/api/perfil/foto")
def remover_foto(token: auth.TokenData = Depends(require_auth)) -> dict:
    uid = _uid(token)
    try:
        _sb_do_login().table("usuario_foto").delete().eq("user_id", uid).execute()
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao remover a foto")
        raise HTTPException(status_code=503, detail=NAO_GRAVOU)
    return {"ok": True}


@router.get("/api/perfil/foto")
def ler_foto(token: auth.TokenData = Depends(require_auth)) -> Response:
    uid = _uid(token)
    try:
        linhas = _sb_do_login().table("usuario_foto").select("jpeg_b64").eq("user_id", uid).limit(1).execute().data or []
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao ler a foto")
        raise HTTPException(status_code=503, detail="Não foi possível ler a foto agora.")
    if not linhas:
        raise HTTPException(status_code=404, detail="Sem foto.")
    # private: a foto é da pessoa logada; o ?v= da página troca a cada envio.
    return Response(base64.b64decode(linhas[0]["jpeg_b64"]), media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=86400"})
