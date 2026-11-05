"""Entrar com a Microsoft pelo navegador: ida (/entrar/microsoft) e volta
(/entrar/microsoft/retorno). A parte de rede está em `microsoft_entra` e a de
qual conta entra, em `login_microsoft`; aqui só se costura o fluxo.

O `cg_ms` guarda state, nonce e o verificador PKCE entre a ida e a volta. É um
JWT assinado (não segredo de sessão) e dura 10 min. Qualquer desvio na volta
termina em `/login?erro_ms=<chave>`: a chave é de um conjunto fixo, e o texto
sai do template, nunca da URL.

Spec: docs/superpowers/specs/2026-11-04-login-microsoft-design.md.
"""
from __future__ import annotations

import hmac
import html
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from jose import jwt
from jose.exceptions import JOSEError

from app import alert_state, atividade, auth, correio, login_microsoft, microsoft_entra, sessao_cookie
from app.rotas.usuarios import _abrir_sessao
from app.sessao import _ip_do_cliente, _sb_do_login
from app.settings_state import load_settings

logger = logging.getLogger("app.main")
router = APIRouter()

COOKIE = "cg_ms"
VALIDADE_S = 600
MENSAGENS_ERRO = {
    "recusada": "Não foi possível entrar com essa conta da Microsoft. Procure o TI.",
    "desativada": "Sua conta está desativada. Procure o TI.",
    "falha": "Não foi possível entrar com a Microsoft agora. Tente de novo ou procure o TI.",
    "cancelada": "Entrada pela Microsoft cancelada.",
}


def _ligado() -> None:
    if not microsoft_entra.configurado():
        raise HTTPException(status_code=404, detail="Not Found")


def _volta(erro: Optional[str], request: Request) -> RedirectResponse:
    if erro:
        r: Response = RedirectResponse("/login?erro_ms=" + erro, status_code=302)
    else:
        # Não é 302 de propósito: a volta da Microsoft é navegação de outro site, e
        # a cadeia de redirecionamentos dela herda isso — o "/" chegaria sem o
        # cookie de sessão (SameSite=Strict) e cairia em /login. Uma página que
        # navega por conta própria (meta refresh) começa uma navegação do mesmo
        # site, e o cookie vai. A CSP não restringe meta refresh.
        r = HTMLResponse(
            '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
            '<meta http-equiv="refresh" content="0;url=/"><title>Entrando</title></head>'
            '<body><p><a href="/">Continuar</a></p></body></html>'
        )
    r.delete_cookie(COOKIE, path="/", secure=sessao_cookie._https(request), httponly=True, samesite="lax")
    return r


@router.get("/entrar/microsoft")
def entrar_com_a_microsoft(request: Request) -> Response:
    _ligado()
    state, nonce, verificador = (secrets.token_urlsafe(32) for _ in range(3))
    r = RedirectResponse(microsoft_entra.url_de_autorizacao(state, nonce, verificador), status_code=302)
    token = jwt.encode(
        {"typ": "cg_ms", "state": state, "nonce": nonce, "verificador": verificador,
         "exp": datetime.now(timezone.utc) + timedelta(seconds=VALIDADE_S)},
        auth._get_secret_key(), algorithm=auth.ALGORITHM,
    )
    # Lax, e não Strict: a volta da Microsoft é uma navegação de outro site.
    r.set_cookie(COOKIE, token, max_age=VALIDADE_S, httponly=True, secure=sessao_cookie._https(request),
                 samesite="lax", path="/")
    return r


def _pedido(request: Request) -> Optional[dict]:
    try:
        dados = jwt.decode(request.cookies.get(COOKIE) or "", auth._get_secret_key(), algorithms=[auth.ALGORITHM])
    except JOSEError:
        return None
    # Mesma chave assina o JWT de sessão: sem o `typ`, ele serviria de pedido.
    return dados if dados.get("typ") == "cg_ms" else None


def _avisar_admins(nome: str, email: str) -> None:
    """Conta nova sem aprovação humana: os administradores ficam sabendo. Um
    e-mail por admin; a falha de um não impede os outros nem o login."""
    try:
        s = load_settings()
        if not correio.configurado(s):
            raise RuntimeError("Envio de e-mail não configurado")
        admins = alert_state._get_admin_emails()
    except Exception:  # noqa: BLE001
        logger.exception("Conta criada pela Microsoft e os administradores NÃO foram avisados.")
        return
    corpo = (
        f"<p>Uma conta nova entrou no CertGuard Análise pela Microsoft:</p>"
        f"<p><strong>{html.escape(nome)}</strong> ({html.escape(email)})</p>"
        "<p>Ela nasceu como operador, sem departamento. Ajuste o acesso em Usuários, se for o caso.</p>"
    )
    for para in admins:
        try:
            correio.send_smtp_email(
                host=s.smtp_host, port=s.smtp_port, user=s.smtp_user, password_enc=s.smtp_password_encrypted,
                use_tls=s.smtp_use_tls, use_ssl=s.smtp_use_ssl, from_email=s.smtp_from_email,
                to_email=para, settings=s, subject=f"Conta nova pela Microsoft: {nome}", html_content=corpo,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Aviso de conta nova pela Microsoft não enviado a %s", para)


@router.get("/entrar/microsoft/retorno")
def retorno_da_microsoft(request: Request, background: BackgroundTasks) -> Response:
    _ligado()
    q = request.query_params
    if q.get("error") == "access_denied":
        return _volta("cancelada", request)
    pedido = _pedido(request)
    state = q.get("state") or ""
    codigo = q.get("code") or ""
    if (
        not pedido or not codigo or q.get("error")
        or not hmac.compare_digest(state.encode(), str(pedido.get("state") or "").encode())
    ):
        return _volta("falha", request)

    try:
        ident, refresh = microsoft_entra.trocar_codigo(codigo, pedido["verificador"], pedido["nonce"])
        resultado: Any = login_microsoft.resolver_conta(_sb_do_login(), ident, refresh)
    except Exception as e:  # noqa: BLE001 — FalhaMicrosoft, DbError, banco ausente: tudo é "falha", nunca 500
        # FalhaMicrosoft é esperada; o resto (banco, bug) precisa de traço.
        logger.warning("Entrada pela Microsoft falhou: %s", e,
                       exc_info=not isinstance(e, microsoft_entra.FalhaMicrosoft))
        return _volta("falha", request)

    ip = _ip_do_cliente(request)
    if isinstance(resultado, login_microsoft.Recusa):
        desativada = resultado.motivo == "desativada"
        atividade.registrar(
            atividade.EVENTO_DESATIVADA_MICROSOFT if desativada else atividade.EVENTO_LOGIN_NEGADO,
            user_id=None, user_email=ident.upn or ident.email, client_ip=ip,
            contexto={"motivo": f"microsoft_{resultado.motivo}"},
        )
        return _volta("desativada" if desativada else "recusada", request)

    user, criada = resultado
    r = _volta(None, request)
    _abrir_sessao(user, request, r, ip, "microsoft")
    if criada:
        atividade.registrar(
            atividade.EVENTO_CONTA_CRIADA_MICROSOFT,
            user_id=str(user.get("id") or "") or None, user_email=user["email"], client_ip=ip,
        )
        background.add_task(_avisar_admins, str(user.get("full_name") or user["email"]), user["email"])
    return r
