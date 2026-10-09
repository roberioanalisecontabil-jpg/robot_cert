"""Sessão do navegador em cookie (Leva D, 09/10/2026).

Até aqui o JWT ia para o `localStorage` e voltava no cabeçalho
`Authorization`. Qualquer script que rodasse na página lia o token e o levava
embora; e o servidor não tinha como guardar as rotas HTML, porque o token não
chegava nelas — a cerca era um `if` no JavaScript.

Agora o login grava o JWT num cookie `HttpOnly` (o JavaScript não lê),
`SameSite=Strict` (outro site não faz o navegador mandá-lo) e `Secure` quando
a requisição veio por HTTPS. Junto vai um segundo cookie, legível, com um
valor aleatório: toda requisição que altera algo e se autentica pelo cookie
tem de repetir esse valor no cabeçalho `X-CSRF-Token` (double submit). Outro
site não lê o cookie do portal, então não sabe o valor.

Transição: o cabeçalho `Authorization: Bearer` continua aceito (abas abertas
antes do deploy, scripts). Agentes e bandeja seguem com as credenciais deles.
"""

from __future__ import annotations

import hmac
import secrets
from typing import Optional

from fastapi import Request
from fastapi.responses import Response

from app import auth

COOKIE_SESSAO = "cg_sessao"
COOKIE_CSRF = "cg_csrf"
CABECALHO_CSRF = "X-CSRF-Token"
METODOS_SEGUROS = frozenset({"GET", "HEAD", "OPTIONS"})

# As páginas que o servidor guarda. /login fica de fora, e /static também.
PAGINAS = frozenset({
    "/", "/configuracao", "/usuarios", "/historico", "/vencidos", "/duplicidades",
    "/acompanhamento", "/carteiras", "/dashboard", "/instalador",
})


def _https(request: Request) -> bool:
    # Atrás do Caddy a conexão com o uvicorn é HTTP; o proxy diz a original.
    return request.url.scheme == "https" or (request.headers.get("x-forwarded-proto") or "").lower() == "https"


def gravar(response: Response, request: Request, token: str) -> None:
    """Põe a sessão e o par anti-CSRF na resposta do login."""
    duracao = int(auth.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    seguro = _https(request)
    response.set_cookie(COOKIE_SESSAO, token, max_age=duracao, httponly=True, secure=seguro,
                        samesite="strict", path="/")
    response.set_cookie(COOKIE_CSRF, secrets.token_urlsafe(32), max_age=duracao, httponly=False,
                        secure=seguro, samesite="strict", path="/")


def apagar(response: Response, request: Request) -> None:
    seguro = _https(request)
    for nome in (COOKIE_SESSAO, COOKIE_CSRF):
        response.delete_cookie(nome, path="/", secure=seguro, httponly=nome == COOKIE_SESSAO, samesite="strict")


def token_do_cookie(request: Request) -> Optional[str]:
    return (request.cookies.get(COOKIE_SESSAO) or "").strip() or None


def csrf_confere(request: Request) -> bool:
    """Requisição que altera algo, autenticada pelo cookie, repete o valor
    do cookie anti-CSRF no cabeçalho. Leitura não precisa."""
    if request.method.upper() in METODOS_SEGUROS:
        return True
    esperado = (request.cookies.get(COOKIE_CSRF) or "").strip()
    recebido = (request.headers.get(CABECALHO_CSRF) or "").strip()
    return bool(esperado) and hmac.compare_digest(esperado.encode("utf-8"), recebido.encode("utf-8"))
