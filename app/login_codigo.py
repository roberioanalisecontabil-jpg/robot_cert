"""Login em dois passos: senha e depois um código (decisão do usuário, 10/10/2026,
pré-requisito para publicar o portal na internet).

* Passo 1 (`/api/login`): e-mail e senha. Se este navegador já passou pelo
  código nos últimos 7 dias, entra direto. Senão, o portal manda um código de
  6 dígitos por e-mail e devolve um DESAFIO — sem sessão.
* Passo 2 (`/api/login/codigo`): o desafio e o código do e-mail, ou o do app
  autenticador (TOTP). Só aí sai a sessão; com "lembrar", também a confiança do
  navegador por 7 dias.

O código é o mesmo mecanismo da recuperação de senha (`app/senha_reset.py`:
15 minutos, 3 erros e queima, tetos por conta e endereço), com propósito
próprio — um código de login nunca redefine senha.

A confiança do navegador é um cookie HttpOnly assinado, preso à conta e à
versão da sessão. Cai com "Sair" (que sobe `sessao_versao`), com troca de
senha (`senha_alterada_em` depois de emitida) e com a conta desativada.

Emergência: `LOGIN_EXIGE_CODIGO=0` no ambiente do servidor desliga o passo 2
(o e-mail caiu e ninguém tem o app cadastrado). Só quem tem acesso ao
servidor muda isso.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import Request, Response

from app import auth, config, totp

logger = logging.getLogger(__name__)

COOKIE_CONFIA = "cg_confia"
VALIDADE_DESAFIO = timedelta(minutes=15)
VALIDADE_CONFIANCA = timedelta(days=7)


def exige_codigo() -> bool:
    return bool(getattr(config, "LOGIN_EXIGE_CODIGO", True))


def _seguro(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"


def _versao(user: Dict[str, Any]) -> int:
    return int(user.get("sessao_versao") or 0)


def _quando(v: Any) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _vale_para(claims: Optional[dict], user: Dict[str, Any]) -> bool:
    """As claims ainda valem para esta conta: mesma conta, mesma versão de
    sessão, emitidas depois da última troca de senha, conta ativa."""
    if not claims or str(claims.get("sub")) != str(user.get("id")):
        return False
    if int(claims.get("sv") or 0) != _versao(user):
        return False
    if not auth.conta_ativa(user):
        return False
    trocada = _quando(user.get("senha_alterada_em"))
    emitido = datetime.fromtimestamp(int(claims.get("iat") or 0), tz=timezone.utc)
    return not (trocada and emitido < trocada - timedelta(seconds=1))


# ── Desafio entre os passos ─────────────────────────────────────────────

def criar_desafio(user: Dict[str, Any]) -> str:
    return auth.criar_token_de(auth.AUD_DESAFIO_DE_LOGIN, str(user["id"]), VALIDADE_DESAFIO, sv=_versao(user))


def user_id_do_desafio(desafio: Optional[str]) -> Optional[str]:
    claims = auth.ler_token_de(auth.AUD_DESAFIO_DE_LOGIN, desafio)
    return str(claims["sub"]) if claims and claims.get("sub") else None


def desafio_vale_para(desafio: Optional[str], user: Dict[str, Any]) -> bool:
    return _vale_para(auth.ler_token_de(auth.AUD_DESAFIO_DE_LOGIN, desafio), user)


# ── Navegador lembrado por 7 dias ──────────────────────────────────────

def navegador_confiavel(request: Request, user: Dict[str, Any]) -> bool:
    token = (request.cookies.get(COOKIE_CONFIA) or "").strip() or None
    return _vale_para(auth.ler_token_de(auth.AUD_NAVEGADOR_CONFIAVEL, token), user)


def gravar_confianca(response: Response, request: Request, user: Dict[str, Any]) -> None:
    token = auth.criar_token_de(auth.AUD_NAVEGADOR_CONFIAVEL, str(user["id"]), VALIDADE_CONFIANCA, sv=_versao(user))
    response.set_cookie(COOKIE_CONFIA, token, max_age=int(VALIDADE_CONFIANCA.total_seconds()), httponly=True,
                        secure=_seguro(request), samesite="strict", path="/")


def apagar_confianca(response: Response, request: Request) -> None:
    response.delete_cookie(COOKIE_CONFIA, path="/", secure=_seguro(request), httponly=True, samesite="strict")


# ── App autenticador ───────────────────────────────────────────────────

def segredo_totp(user: Dict[str, Any], *, so_ativo: bool = True) -> Optional[str]:
    """O segredo do app autenticador da conta (decifrado), ou None."""
    from app.smtp_service import decrypt_password

    if so_ativo and not user.get("totp_ativado_em"):
        return None
    cifrado = user.get("totp_cifrado")
    return (decrypt_password(cifrado) or None) if cifrado else None


def conferir_totp(sb, user: Dict[str, Any], codigo: str, *, so_ativo: bool = True) -> bool:
    """O código do app bate e ainda não foi usado. O passo que bateu é gravado
    por compare-and-swap: o mesmo código não entra duas vezes (replay)."""
    segredo = segredo_totp(user, so_ativo=so_ativo)
    if not segredo:
        return False
    passo = totp.verificar(segredo, codigo)
    if passo is None:
        return False
    ultimo = user.get("totp_ultimo_passo")
    if ultimo is not None and passo <= int(ultimo):
        return False
    q = sb.table("users").update({"totp_ultimo_passo": passo}).eq("id", user["id"])
    q = q.is_("totp_ultimo_passo", "null") if ultimo is None else q.eq("totp_ultimo_passo", ultimo)
    return bool(q.execute().data or [])


def mascarar_email(email: str) -> str:
    nome, _, dominio = (email or "").partition("@")
    if not dominio:
        return "seu e-mail"
    visivel = nome[:2] if len(nome) > 3 else nome[:1]
    return f"{visivel}{'•' * max(1, len(nome) - len(visivel))}@{dominio}"
