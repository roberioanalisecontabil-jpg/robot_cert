"""Entrar com a Microsoft pela bandeja: a ida guarda porta e desafio no cg_ms, e a
volta emite um código de uso único para o ouvinte local, sem abrir sessão do site."""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app import microsoft_entra as me
from app.rotas import microsoft as rm
from tests.test_login_microsoft_rotas import (  # noqa: F401 — fixtures
    STATE, _atividades, _entra_direto, _cookie, _ident, _retorno, banco, ligado, troca,
)

D = "A" * 43
PORTA = 50123


@pytest.fixture
def banco_b(banco: Any) -> Any:
    banco.tabelas["bandeja_codigo"] = []
    return banco


def _cookie_bandeja(client: TestClient, porta: int = PORTA, desafio: str = D) -> None:
    from app import auth

    client.cookies.set("cg_ms", jwt.encode(
        {"typ": "cg_ms", "state": STATE, "nonce": "n-1", "verificador": "v-1",
         "bandeja": {"porta": porta, "desafio": desafio},
         "exp": datetime.now(timezone.utc) + timedelta(minutes=10)},
        auth._get_secret_key(), algorithm="HS256"))


def test_ida_da_bandeja_guarda_porta_e_desafio(client: TestClient) -> None:
    from app import auth

    r = client.get(f"/entrar/microsoft/bandeja?porta={PORTA}&desafio={D}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("https://login.microsoftonline.com/")
    dados = jwt.decode(client.cookies.get("cg_ms"), auth._get_secret_key(), algorithms=["HS256"])
    assert dados["typ"] == "cg_ms" and dados["bandeja"] == {"porta": PORTA, "desafio": D}


@pytest.mark.parametrize("q", ["porta=80&desafio=" + D, "porta=70000&desafio=" + D, f"porta={PORTA}&desafio=curto"])
def test_ida_da_bandeja_recusa_porta_e_desafio_ruins(client: TestClient, q: str) -> None:
    assert client.get("/entrar/microsoft/bandeja?" + q, follow_redirects=False).status_code == 400


def test_ida_da_bandeja_desligada_404(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.config.MICROSOFT_CLIENT_SECRET", "", raising=False)
    r = client.get(f"/entrar/microsoft/bandeja?porta={PORTA}&desafio={D}", follow_redirects=False)
    assert r.status_code == 404


def test_retorno_da_bandeja_emite_codigo_sem_sessao(client: TestClient, banco_b: Any, troca: list) -> None:
    _cookie_bandeja(client)
    r = _retorno(client, code="abc", state=STATE)
    assert r.status_code == 200 and r.headers.get("cache-control") == "no-store"
    alvo = f"http://127.0.0.1:{PORTA}/?codigo="
    assert f'content="0;url={alvo}' in r.text and f'href="{alvo}' in r.text
    assert "<script" not in r.text and "Pronto, pode voltar para a bandeja." in r.text
    cabs = " ".join(r.headers.get_list("set-cookie"))
    assert "cg_sessao=" not in cabs and "cg_ms=" in cabs
    linhas = banco_b.tabelas["bandeja_codigo"]
    assert len(linhas) == 1 and linhas[0]["desafio"] == D and linhas[0]["user_id"] == "u-ana"
    ev = [a for a in _atividades(banco_b) if a["evento"] == "login"]
    assert ev and ev[0]["contexto"]["metodo"] == "microsoft_bandeja"


def test_retorno_da_bandeja_cancelado_volta_ao_loopback(client: TestClient, banco_b: Any, troca: list) -> None:
    _cookie_bandeja(client)
    r = _retorno(client, error="access_denied")
    assert r.status_code == 200 and f"http://127.0.0.1:{PORTA}/?erro=cancelada" in r.text
    assert banco_b.tabelas["bandeja_codigo"] == []


def test_retorno_da_bandeja_recusada_volta_ao_loopback(
    client: TestClient, banco_b: Any, troca: list, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import login_microsoft

    monkeypatch.setattr(login_microsoft, "resolver_conta", lambda *a, **k: login_microsoft.Recusa("convidado"))
    _cookie_bandeja(client)
    r = _retorno(client, code="abc", state=STATE)
    assert f"http://127.0.0.1:{PORTA}/?erro=recusada" in r.text
    assert banco_b.tabelas["bandeja_codigo"] == []
    neg = [a for a in _atividades(banco_b) if a["evento"] == "login_negado"]
    assert neg and neg[0]["contexto"]["metodo"] == "microsoft_bandeja"


def test_retorno_da_bandeja_falha_ao_emitir(
    client: TestClient, banco_b: Any, troca: list, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _quebra(*a: Any, **k: Any) -> str:
        raise RuntimeError("sem banco")

    monkeypatch.setattr("app.bandeja_codigo.emitir", _quebra)
    _cookie_bandeja(client)
    r = _retorno(client, code="abc", state=STATE)
    assert f"http://127.0.0.1:{PORTA}/?erro=falha" in r.text and "cg_sessao=" not in " ".join(r.headers.get_list("set-cookie"))


def test_retorno_do_site_continua_abrindo_sessao(client: TestClient, banco_b: Any, troca: list) -> None:
    _cookie(client)
    r = _retorno(client, code="abc", state=STATE)
    _entra_direto(r)
    assert banco_b.tabelas["bandeja_codigo"] == []
