"""Sessão do navegador em cookie (Leva D, 09/10/2026).

O JWT sai do localStorage e vai para um cookie HttpOnly + SameSite=Strict
(+ Secure por HTTPS); alteração autenticada pelo cookie repete o cookie
anti-CSRF no cabeçalho; as páginas são guardadas no servidor. O cabeçalho
Bearer continua aceito na transição.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import auth, sessao_cookie
from tests.test_seguranca_lote1 import _Fake
from tests.test_seguranca_lote4 import ADMIN, FISCAL_OP, _h  # noqa: F401
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401

SENHA = "senha-boa-123"


@pytest.fixture
def banco(banco_base: _Fake) -> _Fake:
    for u in banco_base.tabelas["users"]:
        u["password_hash"] = auth.get_password_hash(SENHA)
        u["deve_trocar_senha"] = False
    return banco_base


def _entrar(client: TestClient, email: str = FISCAL_OP[0], **headers: str):
    r = client.post("/api/login", json={"email": email, "password": SENHA}, headers=headers)
    assert r.status_code == 200, r.text
    return r


def _set_cookies(r) -> list:
    return [v for k, v in r.headers.multi_items() if k.lower() == "set-cookie"]


def test_login_grava_sessao_httponly_strict_e_o_par_anti_csrf(client: TestClient, banco: _Fake) -> None:
    r = _entrar(client, **{"X-Forwarded-Proto": "https"})
    sessao = next(c for c in _set_cookies(r) if c.startswith("cg_sessao="))
    csrf = next(c for c in _set_cookies(r) if c.startswith("cg_csrf="))
    assert "HttpOnly" in sessao and "SameSite=strict" in sessao and "Secure" in sessao
    assert "HttpOnly" not in csrf and "SameSite=strict" in csrf, "o par anti-CSRF tem de ser legível pelo JS"


def test_sem_https_o_cookie_nao_e_secure(client: TestClient, banco: _Fake) -> None:
    """Na cópia local por http o navegador descartaria um cookie Secure."""
    sessao = next(c for c in _set_cookies(_entrar(client)) if c.startswith("cg_sessao="))
    assert "Secure" not in sessao


def test_leitura_pelo_cookie_e_alteracao_so_com_o_par(client: TestClient, banco: _Fake) -> None:
    _entrar(client)
    assert client.get("/api/colaborador/notificacoes").status_code == 200
    r = client.post("/api/logout")
    assert r.status_code == 403 and "origem" in r.json()["detail"]
    r = client.post("/api/logout", headers={"X-CSRF-Token": "outro-valor"})
    assert r.status_code == 403
    r = client.post("/api/logout", headers={"X-CSRF-Token": client.cookies.get("cg_csrf")})
    assert r.status_code == 200, r.text
    assert any(c.startswith("cg_sessao=") and "Max-Age=0" in c for c in _set_cookies(r)), "sair apaga o cookie"


def test_cabecalho_bearer_continua_valendo_sem_o_par(client: TestClient, banco: _Fake) -> None:
    """Transição: Bearer não é mandado sozinho pelo navegador, então não
    precisa do par anti-CSRF."""
    r = client.post("/api/logout", headers=_h(*FISCAL_OP))
    assert r.status_code == 200, r.text


def test_paginas_exigem_sessao_no_servidor(client_com_chave: TestClient, banco: _Fake) -> None:
    c = client_com_chave
    r = c.get("/historico?x=1", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login?next=%2Fhistorico%3Fx%3D1"
    assert "Content-Security-Policy" in r.headers, "o redirecionamento sai com os cabeçalhos de segurança"
    assert c.get("/login").status_code == 200
    _entrar(c)
    assert c.get("/historico", follow_redirects=False).status_code == 200


def test_sessao_revogada_volta_ao_login_e_apaga_o_cookie(client_com_chave: TestClient, banco: _Fake) -> None:
    c = client_com_chave
    _entrar(c)
    for u in banco.tabelas["users"]:
        if u["email"] == FISCAL_OP[0]:
            u["sessao_versao"] = int(u.get("sessao_versao") or 0) + 5
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert any(x.startswith("cg_sessao=") and "Max-Age=0" in x for x in _set_cookies(r))


def test_paginas_guardadas_sao_as_do_menu() -> None:
    from app.main import app

    html = {getattr(r, "path", "") for r in app.routes
            if "GET" in getattr(r, "methods", set())
            and getattr(getattr(r, "response_class", None), "__name__", "") == "HTMLResponse"}
    assert html - {"/login"} == set(sessao_cookie.PAGINAS), "página nova sem a cerca do servidor (ou cerca sobrando)"
