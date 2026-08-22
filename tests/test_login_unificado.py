"""
Login unificado: este portal passa a aceitar contas do Supabase Auth.

O que está guardado aqui, e por que cada um importa:

  * **entrar não é poder mexer.** Alguém cadastrado só para o inventário
    autentica na lista comum de pessoas e NÃO ganha acesso a este portal. É a
    regressão mais provável da unificação, e a mais silenciosa: `/api/certificados`
    fica fora da matriz de permissões de propósito ("aberto a quem está
    autenticado"), então bastaria a autenticação passar para a listagem de
    certificados abrir.

  * **os dois tipos de token não se confundem.** O daqui traz `iss`/`aud`
    próprios; o do Supabase é validado contra o servidor deles. Se um passasse
    pelo caminho do outro, a validação seria a errada.

  * **o papel continua vindo do banco.** O token só prova o e-mail. Se algum dia
    ele passar a mandar no papel, rebaixar alguém deixa de ter efeito até o
    token expirar — que é o defeito que `_sessao_do_token` existe para não ter.

  * **a queda para o login local sobrevive à transição.** Recusar quem ainda não
    migrou trancaria gente para fora sem aviso.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from app import auth, auth_supabase

EMAIL = "ana@x.com"
SENHA_LOCAL = "senha-local-123"
SENHA_AUTH = "senha-do-auth-456"
TOKEN_EXTERNO = "aaa.bbb.ccc-token-do-supabase-auth-com-tamanho-suficiente"


class _Res:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _Query:
    def __init__(self, linhas: List[Dict[str, Any]]) -> None:
        self._l = linhas
        self._f: List = []

    def select(self, *_c: str) -> "_Query":
        return self

    def eq(self, c: str, v: Any) -> "_Query":
        self._f.append((c, v))
        return self

    def limit(self, _n: int) -> "_Query":
        return self

    def order(self, *_a: Any, **_k: Any) -> "_Query":
        return self

    def gte(self, *_a: Any) -> "_Query":
        return self

    def lt(self, *_a: Any) -> "_Query":
        return self

    def execute(self) -> _Res:
        return _Res([dict(r) for r in self._l if all(r.get(c) == v for c, v in self._f)])


class _Fake:
    def __init__(self, users: List[Dict[str, Any]]) -> None:
        self.tabelas = {"users": users, "user_activity": []}

    def table(self, nome: str) -> _Query:
        return _Query(self.tabelas.setdefault(nome, []))


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake([
        {"id": "u-ana", "email": EMAIL, "full_name": "Ana", "role": "user",
         "ativo": True, "deve_trocar_senha": False, "senha_alterada_em": None,
         "password_hash": auth.get_password_hash(SENHA_LOCAL)},
        {"id": "u-off", "email": "off@x.com", "full_name": "Desativada",
         "role": "user", "ativo": False, "deve_trocar_senha": False,
         "senha_alterada_em": None,
         "password_hash": auth.get_password_hash(SENHA_LOCAL)},
    ])
    monkeypatch.setattr("app.settings_state._supabase", lambda: fake)
    return fake


@pytest.fixture
def auth_externo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Supabase Auth ligado, conhecendo EMAIL e um e-mail só do INVENT."""
    contas = {
        EMAIL: SENHA_AUTH,
        "so-inventario@x.com": SENHA_AUTH,
        "off@x.com": SENHA_AUTH,
    }
    tokens = {f"{e}.token.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": e for e in contas}

    monkeypatch.setattr(auth_supabase, "configurado", lambda: True)
    monkeypatch.setattr(
        auth_supabase, "entrar",
        lambda email, senha: next(
            (t for t, e in tokens.items()
             if e == (email or "").strip().lower() and contas.get(e) == senha),
            None,
        ),
    )
    monkeypatch.setattr(
        auth_supabase, "email_do_token", lambda t: tokens.get(t)
    )
    return None


def _login(client: TestClient, email: str, senha: str):
    return client.post("/api/login", json={"email": email, "password": senha})


def _token_de(email: str) -> str:
    return f"{email}.token.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


# ──────────────────────────────────────────────────────────────────────────
# 1. Entrar não é poder mexer
# ──────────────────────────────────────────────────────────────────────────

def test_conta_so_do_outro_portal_nao_entra_aqui(
    client: TestClient, banco: _Fake, auth_externo: None
) -> None:
    """
    A regressão mais provável da unificação. Se passasse, quem foi cadastrado
    só para o inventário ganharia a listagem de certificados — que fica fora da
    matriz de permissões de propósito.
    """
    r = _login(client, "so-inventario@x.com", SENHA_AUTH)
    assert r.status_code == 403
    assert "acesso a este portal" in r.json()["detail"].lower()


def test_token_de_quem_nao_tem_conta_aqui_nao_abre_rota(
    client_com_chave: TestClient, banco: _Fake, auth_externo: None
) -> None:
    """
    Mesma barreira, pelo outro lado: mesmo com um token válido do Supabase, sem
    linha em `users` a sessão não existe. Guarda contra alguém obter o token
    direto no outro portal e apresentá-lo aqui.
    """
    r = client_com_chave.get(
        "/api/certificados",
        headers={"Authorization": f"Bearer {_token_de('so-inventario@x.com')}"},
    )
    assert r.status_code == 401


def test_conta_desativada_aqui_nao_entra_mesmo_com_auth_valido(
    client: TestClient, banco: _Fake, auth_externo: None
) -> None:
    """
    Desativar alguém NESTE portal continua cortando, mesmo que a conta siga
    válida na lista comum. É o que mantém a revogação local funcionando depois
    da unificação.
    """
    r = _login(client, "off@x.com", SENHA_AUTH)
    assert r.status_code == 403
    assert "desativado" in r.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────────
# 2. O caminho feliz, e o papel vindo do banco
# ──────────────────────────────────────────────────────────────────────────

def test_quem_tem_conta_nos_dois_entra_pelo_auth(
    client: TestClient, banco: _Fake, auth_externo: None
) -> None:
    r = _login(client, EMAIL, SENHA_AUTH)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["access_token"] == _token_de(EMAIL)
    assert corpo["role"] == "user"


def test_o_token_externo_abre_as_rotas(
    client_com_chave: TestClient, banco: _Fake, auth_externo: None
) -> None:
    r = client_com_chave.get(
        "/api/certificados", headers={"Authorization": f"Bearer {_token_de(EMAIL)}"}
    )
    assert r.status_code == 200, r.text


def test_o_papel_vem_do_banco_e_nao_do_token(
    client_com_chave: TestClient, banco: _Fake, auth_externo: None
) -> None:
    """
    Promover no banco vale na requisição seguinte, sem novo login. Se o papel
    passasse a vir do token, rebaixar alguém não teria efeito até ele expirar —
    o defeito que `_sessao_do_token` existe para não ter.
    """
    h = {"Authorization": f"Bearer {_token_de(EMAIL)}"}
    assert client_com_chave.get("/api/users", headers=h).status_code == 403

    for u in banco.tabelas["users"]:
        if u["email"] == EMAIL:
            u["role"] = "admin"

    assert client_com_chave.get("/api/users", headers=h).status_code == 200


# ──────────────────────────────────────────────────────────────────────────
# 3. Os dois tipos de token não se confundem
# ──────────────────────────────────────────────────────────────────────────

def test_token_deste_portal_nao_passa_pelo_caminho_do_outro(
    client_com_chave: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Se o token local caísse na validação do Supabase, ele seria conferido pelo
    servidor errado — e passaria a depender de um serviço que não o emitiu.
    """
    chamou = {"externo": False}

    def _espia(_t: str) -> Optional[str]:
        chamou["externo"] = True
        return None

    monkeypatch.setattr(auth_supabase, "configurado", lambda: True)
    monkeypatch.setattr(auth_supabase, "email_do_token", _espia)

    local = _login(client_com_chave, EMAIL, SENHA_LOCAL).json()["access_token"]
    r = client_com_chave.get(
        "/api/certificados", headers={"Authorization": f"Bearer {local}"}
    )

    assert r.status_code == 200
    assert not chamou["externo"], "o token deste portal foi parar na validação do outro"


def test_lixo_no_cabecalho_continua_401(
    client_com_chave: TestClient, banco: _Fake, auth_externo: None
) -> None:
    """
    Com API_KEY configurada — a forma de produção. Sem ela o `require_auth`
    devolve identidade ANÔNIMA de propósito (ambiente aberto), e este teste
    passaria a medir outra coisa.
    """
    r = client_com_chave.get(
        "/api/certificados", headers={"Authorization": "Bearer nao-e-token"}
    )
    assert r.status_code == 401


# ──────────────────────────────────────────────────────────────────────────
# 4. A transição
# ──────────────────────────────────────────────────────────────────────────

def test_quem_ainda_nao_migrou_entra_pelo_login_local(
    client: TestClient, banco: _Fake, auth_externo: None
) -> None:
    """
    A queda que impede o deploy de trancar gente para fora. A conta existe aqui,
    ainda não no Auth — e a senha local continua valendo.
    """
    r = _login(client, EMAIL, SENHA_LOCAL)
    assert r.status_code == 200
    # Token DESTE portal, não do outro.
    assert r.json()["access_token"] != _token_de(EMAIL)
    assert auth.decode_access_token(r.json()["access_token"]) is not None


def test_o_login_local_deixa_rastro_para_a_transicao_acabar(
    client: TestClient, banco: _Fake, auth_externo: None, caplog
) -> None:
    """
    Sem registro, "já dá para desligar o login local?" vira adivinhação.
    """
    import logging

    with caplog.at_level(logging.WARNING):
        _login(client, EMAIL, SENHA_LOCAL)
    assert any("nao migrada" in r.message.lower() for r in caplog.records)


def test_sem_auth_configurado_nada_muda(client: TestClient, banco: _Fake) -> None:
    """
    Antes de existir projeto de contas, o portal tem de funcionar exatamente
    como funcionava. É o estado em que o deploy desta fase entra em produção.
    """
    assert auth_supabase.configurado() is False
    r = _login(client, EMAIL, SENHA_LOCAL)
    assert r.status_code == 200
    assert auth.decode_access_token(r.json()["access_token"]) is not None


def test_senha_errada_continua_401(
    client: TestClient, banco: _Fake, auth_externo: None
) -> None:
    assert _login(client, EMAIL, "nem-uma-nem-outra").status_code == 401
