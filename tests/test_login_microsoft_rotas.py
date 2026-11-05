"""Entrar com a Microsoft pelo navegador: início (/entrar/microsoft) e retorno.
Sem rede: `trocar_codigo` é trocado por um duplo. Cada teste guarda uma regra
cuja quebra deixaria entrar quem não devia, ou prenderia quem devia."""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app import microsoft_entra as me
from app.rotas import microsoft as rm
from tests.test_recuperacao_de_senha import _Fake

DOM = "analisegroup.cnt.br"
EMAIL = f"ana@{DOM}"
STATE = "state-certo"


@pytest.fixture(autouse=True)
def ligado(monkeypatch: pytest.MonkeyPatch) -> None:
    for nome, valor in (
        ("MICROSOFT_TENANT_ID", "t-1"), ("MICROSOFT_CLIENT_ID", "c-1"),
        ("MICROSOFT_CLIENT_SECRET", "s-1"), ("MICROSOFT_DOMINIOS", frozenset({DOM})),
        ("PORTAL_BASE_URL", "https://certificado.analisegroup.cnt.br"),
    ):
        monkeypatch.setattr(f"app.config.{nome}", valor, raising=False)


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake({
        "users": [{"id": "u-ana", "email": EMAIL, "full_name": "Ana", "role": "user",
                   "ativo": True, "sessao_versao": 0}],
        "user_activity": [],
    })
    monkeypatch.setattr("app.settings_state._banco", lambda: fake)
    return fake


def _ident(**kw: Any) -> me.Identidade:
    base = dict(oid="oid-1", tid="t-1", upn=EMAIL, email=EMAIL, nome="Ana Souza", convidado=False)
    base.update(kw)
    return me.Identidade(**base)


@pytest.fixture
def troca(monkeypatch: pytest.MonkeyPatch) -> List[tuple]:
    chamadas: List[tuple] = []

    def _fake(codigo: str, verificador: str, nonce: str, cliente: Any = None):
        chamadas.append((codigo, verificador, nonce))
        return _ident(), "rt"

    monkeypatch.setattr(me, "trocar_codigo", _fake)
    return chamadas


def _cookie(client: TestClient, state: str = STATE, exp_min: int = 10, typ: Optional[str] = "cg_ms") -> None:
    from app import auth

    token = jwt.encode(
        {**({"typ": typ} if typ else {}), "state": state, "nonce": "n-1", "verificador": "v-1",
         "exp": datetime.now(timezone.utc) + timedelta(minutes=exp_min)},
        auth._get_secret_key(), algorithm="HS256",
    )
    client.cookies.set("cg_ms", token)


def _retorno(client: TestClient, **q: str):
    return client.get("/entrar/microsoft/retorno", params=q, follow_redirects=False)


def _entra_direto(r: Any) -> None:
    """Sucesso é 200 com meta refresh (não 302): ver `_volta` em rotas/microsoft.py."""
    assert r.status_code == 200 and "location" not in r.headers
    assert '<meta http-equiv="refresh" content="0;url=/">' in r.text and 'href="/"' in r.text
    # Papel e e-mail vão para o localStorage, como no login por senha: sem eles
    # o menu trata o admin como operador (05/11/2026).
    assert '<script src="/static/entrou-microsoft.js" data-role="' in r.text
    assert r.text.index("entrou-microsoft.js") < r.text.index('http-equiv="refresh"')
    assert r.headers.get("cache-control") == "no-store", "a página que grava cg_sessao não vai para cache"
    cabs = " ".join(r.headers.get_list("set-cookie"))
    assert "cg_sessao=" in cabs and "cg_csrf=" in cabs and "cg_ms=" in cabs


def _atividades(banco: _Fake) -> List[Dict[str, Any]]:
    return banco.tabelas["user_activity"]


def test_desligado_404_e_sem_botao(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.config.MICROSOFT_CLIENT_SECRET", "", raising=False)
    assert client.get("/entrar/microsoft", follow_redirects=False).status_code == 404
    assert client.get("/entrar/microsoft/retorno", follow_redirects=False).status_code == 404
    assert "Entrar com a Microsoft" not in client.get("/login").text


def test_inicio_grava_cookie_e_redireciona(client: TestClient) -> None:
    from app import auth

    r = client.get("/entrar/microsoft", follow_redirects=False)
    assert r.status_code == 302
    url = urlparse(r.headers["location"])
    q = parse_qs(url.query)
    assert url.netloc == "login.microsoftonline.com" and q["code_challenge_method"] == ["S256"]
    cab = r.headers["set-cookie"].lower()
    assert "cg_ms=" in cab and "httponly" in cab and "samesite=lax" in cab and "max-age=600" in cab
    dados = jwt.decode(client.cookies.get("cg_ms"), auth._get_secret_key(), algorithms=["HS256"])
    assert dados["typ"] == "cg_ms" and dados["state"] == q["state"][0] and dados["nonce"] == q["nonce"][0]
    assert dados["verificador"] and dados["exp"]


def test_retorno_abre_sessao_e_audita_metodo_microsoft(client: TestClient, banco: _Fake, troca: list) -> None:
    _cookie(client)
    r = _retorno(client, code="abc", state=STATE)
    _entra_direto(r)
    assert troca == [("abc", "v-1", "n-1")]
    assert client.cookies.get("cg_sessao")
    assert 'cg_ms="";' in r.headers["set-cookie"] or "cg_ms=;" in r.headers["set-cookie"]
    ev = [a for a in _atividades(banco) if a["evento"] == "login"]
    assert ev and ev[0]["contexto"]["metodo"] == "microsoft"
    assert banco.tabelas["users"][0]["microsoft_oid"] == "oid-1"
    conta = banco.tabelas["users"][0]
    assert f'data-role="{conta["role"]}" data-email="{conta["email"]}"' in r.text


def test_retorno_sem_codigo_pedido_mesmo_se_LOGIN_EXIGE_CODIGO(
    client: TestClient, banco: _Fake, troca: list, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.config.LOGIN_EXIGE_CODIGO", True, raising=False)
    _cookie(client)
    r = _retorno(client, code="abc", state=STATE)
    _entra_direto(r)
    assert client.cookies.get("cg_sessao")


def test_state_diferente_falha(client: TestClient, banco: _Fake, troca: list) -> None:
    _cookie(client)
    r = _retorno(client, code="abc", state="outro")
    assert r.headers["location"] == "/login?erro_ms=falha"
    assert troca == [] and not client.cookies.get("cg_sessao")


@pytest.mark.parametrize("vencido", [False, True])
def test_cookie_ausente_ou_vencido_falha_sem_gravar(client: TestClient, banco: _Fake, troca: list, vencido: bool) -> None:
    if vencido:
        _cookie(client, exp_min=-1)
    r = _retorno(client, code="abc", state=STATE)
    assert r.headers["location"] == "/login?erro_ms=falha"
    assert troca == [] and not client.cookies.get("cg_sessao")
    assert banco.tabelas["users"][0].get("microsoft_oid") is None and _atividades(banco) == []


def test_jwt_de_sessao_nao_serve_de_pedido(client: TestClient, banco: _Fake, troca: list) -> None:
    from app import auth

    token = auth.create_access_token({"sub": EMAIL, "role": "user", "state": STATE,
                                      "nonce": "n-1", "verificador": "v-1"})
    client.cookies.set("cg_ms", token)
    r = _retorno(client, code="abc", state=STATE)
    assert r.headers["location"] == "/login?erro_ms=falha" and troca == []
    _cookie(client, typ=None)
    assert _retorno(client, code="abc", state=STATE).headers["location"] == "/login?erro_ms=falha"


def test_access_denied_cancelada(client: TestClient, banco: _Fake, troca: list) -> None:
    _cookie(client)
    r = _retorno(client, error="access_denied", error_description="x", state=STATE)
    assert r.headers["location"] == "/login?erro_ms=cancelada" and troca == []
    assert "cg_ms" in r.headers["set-cookie"]


def test_falha_da_microsoft_e_erro_de_banco_viram_falha(
    client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_a: Any, **_k: Any):
        raise me.FalhaMicrosoft("x")

    monkeypatch.setattr(me, "trocar_codigo", _boom)
    _cookie(client)
    assert _retorno(client, code="abc", state=STATE).headers["location"] == "/login?erro_ms=falha"

    from app.db_pg import DbError

    def _db(*_a: Any, **_k: Any):
        raise DbError("falhou", "XX000")

    monkeypatch.setattr(me, "trocar_codigo", lambda *a, **k: (_ident(), "rt"))
    monkeypatch.setattr("app.login_microsoft.resolver_conta", _db)
    _cookie(client)
    assert _retorno(client, code="abc", state=STATE).headers["location"] == "/login?erro_ms=falha"


def test_erro_de_banco_nao_poe_o_oid_no_log(
    client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    from app.db_pg import DbError

    def _db(*_a: Any, **_k: Any):
        raise DbError("duplicate key. Key (microsoft_oid)=(oid-secreto) already exists.", "23505")

    monkeypatch.setattr(me, "trocar_codigo", lambda *a, **k: (_ident(), "rt"))
    monkeypatch.setattr("app.login_microsoft.resolver_conta", _db)
    _cookie(client)
    with caplog.at_level("WARNING", logger="app.main"):
        assert _retorno(client, code="abc", state=STATE).headers["location"] == "/login?erro_ms=falha"
    regs = [r for r in caplog.records if "Microsoft" in r.getMessage()]
    assert regs and all(r.exc_info is None for r in regs)
    texto = " ".join(r.getMessage() for r in regs)
    assert "oid-secreto" not in texto and "DbError" in texto and "23505" in texto


def test_recusa_e_desativada_mapeadas(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(me, "trocar_codigo", lambda *a, **k: (_ident(upn="x@gmail.com", email="x@gmail.com"), "rt"))
    _cookie(client)
    assert _retorno(client, code="abc", state=STATE).headers["location"] == "/login?erro_ms=recusada"
    assert not client.cookies.get("cg_sessao")

    banco.tabelas["users"][0]["ativo"] = False
    monkeypatch.setattr(me, "trocar_codigo", lambda *a, **k: (_ident(), "rt"))
    _cookie(client)
    assert _retorno(client, code="abc", state=STATE).headers["location"] == "/login?erro_ms=desativada"
    # Conta inativa recusada aqui não é "bloqueada na Microsoft": pode ter
    # sido desativada à mão ou pelo Acessórias. desativada_microsoft é só da conferência.
    assert [a["evento"] for a in _atividades(banco)] == ["login_negado", "login_negado"]
    assert _atividades(banco)[1]["contexto"] == {"motivo": "conta_desativada", "metodo": "microsoft"}
    assert not client.cookies.get("cg_sessao")


def test_conta_criada_avisa_admins(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import alert_state, correio

    enviados: List[Dict[str, Any]] = []

    def _envio(**kw: Any) -> None:
        enviados.append(kw)
        if kw["to_email"] == "a1@x.com":
            raise RuntimeError("smtp caiu")

    monkeypatch.setattr(alert_state, "_get_admin_emails", lambda: ["a1@x.com", "a2@x.com"])
    monkeypatch.setattr(correio, "configurado", lambda _s: True)
    monkeypatch.setattr(correio, "send_smtp_email", _envio)
    monkeypatch.setattr(me, "trocar_codigo", lambda *a, **k: (
        _ident(oid="oid-2", upn=f"bia@{DOM}", email=f"bia@{DOM}", nome="<Bia>"), "rt"))
    _cookie(client)
    r = _retorno(client, code="abc", state=STATE)
    _entra_direto(r)
    assert client.cookies.get("cg_sessao")
    assert [e["to_email"] for e in enviados] == ["a1@x.com", "a2@x.com"]
    assert enviados[0]["subject"] == "Conta nova pela Microsoft: <Bia>"
    assert "&lt;Bia&gt;" in enviados[0]["html_content"]
    assert "conta_criada_microsoft" in [a["evento"] for a in _atividades(banco)]


def test_conta_existente_nao_avisa_admins(client: TestClient, banco: _Fake, troca: list, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import correio

    enviados: list = []
    monkeypatch.setattr(correio, "send_smtp_email", lambda **kw: enviados.append(kw))
    _cookie(client)
    _retorno(client, code="abc", state=STATE)
    assert enviados == []


def test_pagina_login_mostra_botao_so_configurado(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    html = client.get("/login").text
    assert "Entrar com a Microsoft" in html and 'href="/entrar/microsoft"' in html
    monkeypatch.setattr("app.config.PORTAL_BASE_URL", "", raising=False)
    assert "Entrar com a Microsoft" not in client.get("/login").text


def test_login_leva_os_dominios_e_a_reserva_so_configurado(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """E-mail dos domínios vai direto para a Microsoft; o admin tem o botão da senha (05/11/2026)."""
    html = client.get("/login").text
    assert f'data-ms-dominios="{DOM}"' in html and 'id="btn-com-senha"' in html
    monkeypatch.setattr("app.config.PORTAL_BASE_URL", "", raising=False)
    html = client.get("/login").text
    assert 'data-ms-dominios=""' in html and 'id="btn-com-senha"' not in html


@pytest.mark.parametrize("chave", sorted(rm.MENSAGENS_ERRO))
def test_erro_ms_mostra_texto_fixo(client: TestClient, chave: str) -> None:
    texto = rm.MENSAGENS_ERRO[chave]
    from html import escape

    assert escape(texto) in client.get("/login", params={"erro_ms": chave}).text


def test_mensagens_exatas() -> None:
    assert rm.MENSAGENS_ERRO == {
        "recusada": "Não foi possível entrar com essa conta da Microsoft. Procure o TI.",
        "desativada": "Sua conta está desativada. Procure o TI.",
        "falha": "Não foi possível entrar com a Microsoft agora. Tente de novo ou procure o TI.",
        "cancelada": "Entrada pela Microsoft cancelada.",
    }


def test_erro_ms_desconhecido_nao_reflete_texto(client: TestClient) -> None:
    html = client.get("/login", params={"erro_ms": "<script>alert(1)</script>Ola-injetado"}).text
    assert "Ola-injetado" not in html and "<script>alert(1)" not in html
