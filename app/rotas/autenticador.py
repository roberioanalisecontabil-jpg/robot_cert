"""App autenticador da própria conta (10/10/2026).

É a saída do login em dois passos quando o e-mail não chega: quem cadastra o
app (Microsoft Authenticator, Google Authenticator e afins) pode entrar com o
código dele no lugar do código por e-mail. Ver `app/login_codigo.py`.

* `iniciar` gera o segredo e o devolve UMA vez (texto para digitar e o link
  `otpauth://`); fica guardado cifrado, ainda inativo.
* `confirmar` ativa: só um código certo do app prova que ele foi cadastrado.
* `remover` desliga.

Ativar e remover pedem a senha atual: com a sessão aberta e a máquina
destravada, quem sentasse na cadeira cadastraria o próprio celular e teria
uma porta de volta para a conta. Quem perdeu o celular pede ao administrador,
que remove pela tela de Usuários.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import auth, login_codigo, taxa, totp
from app.sessao import SESSAO_ENCERRADA, _sb_do_login, _user_id_da_sessao, require_admin, require_auth

logger = logging.getLogger("app.main")
router = APIRouter()

SENHA_NAO_CONFERE = "A senha atual não confere."


class SenhaBody(BaseModel):
    senha_atual: str = Field(max_length=1024)


class CodigoBody(BaseModel):
    codigo: str = Field(max_length=12)


def _minha_conta(token: auth.TokenData):
    uid = _user_id_da_sessao(token)
    if not uid:
        raise HTTPException(status_code=401, detail=SESSAO_ENCERRADA)
    sb = _sb_do_login()
    linhas = sb.table("users").select("*").eq("id", uid).limit(1).execute().data or []
    if not linhas:
        raise HTTPException(status_code=401, detail=SESSAO_ENCERRADA)
    return sb, linhas[0]


def _exigir_senha(user, senha: str) -> None:
    if not auth.verify_password(senha or "", user.get("password_hash") or ""):
        raise HTTPException(status_code=400, detail=SENHA_NAO_CONFERE)


def _limpar(sb, uid: str) -> None:
    sb.table("users").update(
        {"totp_cifrado": None, "totp_ativado_em": None, "totp_ultimo_passo": None}
    ).eq("id", uid).execute()


@router.get("/api/users/me/app-autenticador")
def situacao(token: auth.TokenData = Depends(require_auth)) -> dict:
    _, user = _minha_conta(token)
    return {"ativo": bool(user.get("totp_ativado_em")), "ativado_em": user.get("totp_ativado_em")}


@router.post("/api/users/me/app-autenticador/iniciar")
def iniciar(body: SenhaBody, request: Request, token: auth.TokenData = Depends(require_auth)) -> dict:
    sb, user = _minha_conta(token)
    if not taxa.permitir(f"totp-senha:{user['id']}", 10, 900):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde alguns minutos.")
    _exigir_senha(user, body.senha_atual)
    if user.get("totp_ativado_em"):
        raise HTTPException(status_code=409, detail="O app autenticador já está ativo. Remova-o antes de cadastrar outro.")
    from app.smtp_service import encrypt_password

    segredo = totp.novo_segredo()
    sb.table("users").update(
        {"totp_cifrado": encrypt_password(segredo), "totp_ativado_em": None, "totp_ultimo_passo": None}
    ).eq("id", user["id"]).execute()
    uri = totp.uri(segredo, user.get("email") or "")
    return {"segredo": totp.agrupado(segredo), "uri": uri, "qr": totp.qr_data_uri(uri)}


@router.post("/api/users/me/app-autenticador/confirmar")
def confirmar(body: CodigoBody, token: auth.TokenData = Depends(require_auth)) -> dict:
    sb, user = _minha_conta(token)
    if user.get("totp_ativado_em"):
        return {"ativo": True}
    if not user.get("totp_cifrado"):
        raise HTTPException(status_code=400, detail="Comece pelo cadastro do app.")
    if not taxa.permitir(f"totp-confirmar:{user['id']}", 10, 900):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde alguns minutos.")
    if not login_codigo.conferir_totp(sb, user, body.codigo, so_ativo=False):
        raise HTTPException(status_code=400, detail="Código não confere. Confira a hora do celular e tente o próximo.")
    agora = datetime.now(timezone.utc).isoformat()
    # Só ativa o segredo que foi conferido: se outro `iniciar` trocou o
    # segredo no meio, este update não casa e nada é ativado.
    feito = (sb.table("users").update({"totp_ativado_em": agora})
             .eq("id", user["id"]).eq("totp_cifrado", user["totp_cifrado"]).execute().data or [])
    if not feito:
        raise HTTPException(status_code=409, detail="O cadastro mudou no meio. Comece de novo.")
    logger.info("App autenticador ativado na conta %s", user["id"])
    return {"ativo": True}


@router.post("/api/users/me/app-autenticador/remover")
def remover(body: SenhaBody, token: auth.TokenData = Depends(require_auth)) -> dict:
    sb, user = _minha_conta(token)
    if not taxa.permitir(f"totp-senha:{user['id']}", 10, 900):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde alguns minutos.")
    _exigir_senha(user, body.senha_atual)
    _limpar(sb, str(user["id"]))
    logger.info("App autenticador removido pela própria conta %s", user["id"])
    return {"ativo": False}


@router.post("/api/users/{user_id}/app-autenticador/remover")
def remover_pelo_admin(user_id: str, token: auth.TokenData = Depends(require_admin)) -> dict:
    """A pessoa perdeu o celular: o administrador desliga, ela volta ao código
    por e-mail e cadastra o app de novo quando quiser."""
    sb = _sb_do_login()
    if not (sb.table("users").select("id").eq("id", user_id).limit(1).execute().data or []):
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    _limpar(sb, user_id)
    logger.info("App autenticador da conta %s removido pelo administrador %s", user_id, token.email)
    return {"ativo": False}
