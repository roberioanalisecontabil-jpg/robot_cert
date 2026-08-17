"""
O login compara o e-mail normalizado, e não o que veio digitado.

A coluna `users.email` guarda tudo em minúsculas — o portal grava assim, e o
índice `users_email_unico_idx` é sobre `lower(email)`. Mas a consulta do login
usava o valor cru do formulário. Quem digitasse "Ana@X.com" não casava com linha
nenhuma e recebia **401 "E-mail ou senha incorretos"**: a mensagem manda a
pessoa trocar a senha por causa de uma maiúscula.

O defeito é anterior a 16/08, mas a migration daquele dia o tornou capaz de
trancar gente para fora: o `UPDATE ... SET email = lower(trim(email))` teria
transformado uma linha "Fulano@x.com" em "fulano@x.com", e quem entrava
digitando com maiúscula deixaria de entrar. Na base real não havia divergência
de caixa, então não aconteceu — mas foi sorte medida, não desenho.
"""

from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from app import auth

SENHA = "senha-de-teste-123"


class _Res:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _Query:
    def __init__(self, linhas: List[Dict[str, Any]]) -> None:
        self._l, self._f = linhas, []

    def select(self, *_c: str) -> "_Query":
        return self

    def insert(self, _p: Any) -> "_Query":
        return self

    def eq(self, coluna: str, valor: Any) -> "_Query":
        self._f.append((coluna, valor))
        return self

    def limit(self, _n: int) -> "_Query":
        return self

    def execute(self) -> _Res:
        return _Res([dict(r) for r in self._l
                     if all(r.get(c) == v for c, v in self._f)])


class _Fake:
    def __init__(self, tabelas: Dict[str, List[Dict[str, Any]]]) -> None:
        self.tabelas = tabelas

    def table(self, nome: str) -> _Query:
        return _Query(self.tabelas.setdefault(nome, []))


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake({
        # Em minúsculas, como está em produção depois do users_email_unico.
        "users": [{
            "id": "u-ana",
            "email": "ana@x.com",
            "full_name": "Ana",
            "role": "user",
            "ativo": True,
            "password_hash": auth.get_password_hash(SENHA),
        }],
        "user_activity": [],
    })
    monkeypatch.setattr("app.settings_state._supabase", lambda: fake)
    return fake


def _login(client: TestClient, email: str, senha: str = SENHA):
    return client.post("/api/login", json={"email": email, "password": senha})


# ──────────────────────────────────────────────────────────────────────────
# 1. O caso que quebrava
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("digitado", [
    "ana@x.com",      # controle: já funcionava
    "Ana@X.com",      # o caso do defeito
    "ANA@X.COM",
    "  ana@x.com  ",  # colar de um e-mail costuma trazer espaço junto
])
def test_entra_independente_da_caixa_e_do_espaco(
    client: TestClient, banco: _Fake, digitado: str
) -> None:
    r = _login(client, digitado)
    assert r.status_code == 200, f"{digitado!r} não entrou: {r.text}"
    assert r.json()["role"] == "user"


def test_o_sub_do_token_sai_normalizado(client: TestClient, banco: _Fake) -> None:
    """
    O `sub` alimenta `_conta_da_sessao`, que consulta `.eq("email", ...)`. Se
    saísse com a caixa digitada, a sessão morreria na requisição seguinte — o
    login funcionaria e o portal se comportaria como se o token fosse inválido.
    """
    r = _login(client, "ANA@X.COM")
    dados = auth.decode_access_token(r.json()["access_token"])
    assert dados.email == "ana@x.com"


# ──────────────────────────────────────────────────────────────────────────
# 2. Normalizar não pode virar frouxidão
# ──────────────────────────────────────────────────────────────────────────

def test_senha_errada_continua_401(client: TestClient, banco: _Fake) -> None:
    assert _login(client, "Ana@X.com", "senha-errada").status_code == 401


def test_conta_inexistente_continua_401(client: TestClient, banco: _Fake) -> None:
    assert _login(client, "NINGUEM@X.COM").status_code == 401


def test_desativado_nao_entra_nem_com_a_caixa_certa(
    client: TestClient, banco: _Fake
) -> None:
    banco.tabelas["users"][0]["ativo"] = False
    assert _login(client, "Ana@X.com").status_code == 403
