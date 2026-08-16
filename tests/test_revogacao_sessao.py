"""
Revogação de acesso: o token para de valer quando a conta muda.

O JWT dura 24h (`auth.ACCESS_TOKEN_EXPIRE_MINUTES`) e carrega o papel dentro de
si. Enquanto `require_auth` devolvia o token decodificado e nada mais, o papel
gravado no login valia até expirar — desativar alguém não derrubava a sessão
aberta, e **rebaixar um administrador não tirava o poder de administrador**.

Estes testes fixam a regra oposta: a permissão vem da linha em `users`, lida na
requisição. O que cada um mede está no docstring; o conjunto existe porque um
`require_auth` "simplificado" de volta ao `return token_data` passaria em toda a
suíte antiga sem sintoma nenhum.
"""

from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from app import auth


class _Res:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _Query:
    def __init__(self, linhas: List[Dict[str, Any]], banco: "_Fake") -> None:
        self._l, self._b, self._f, self._cols = linhas, banco, [], None

    def select(self, *cols: str) -> "_Query":
        self._cols = cols
        return self

    def eq(self, coluna: str, valor: Any) -> "_Query":
        self._f.append((coluna, valor))
        return self

    def limit(self, _n: int) -> "_Query":
        return self

    def execute(self) -> _Res:
        if self._b.quebrado:
            raise RuntimeError("banco fora do ar")
        return _Res([dict(r) for r in self._l
                     if all(r.get(c) == v for c, v in self._f)])


class _Fake:
    def __init__(self, users: List[Dict[str, Any]]) -> None:
        self.tabelas = {"users": users}
        self.quebrado = False

    def table(self, nome: str) -> _Query:
        return _Query(self.tabelas.setdefault(nome, []), self)


ADMIN = {"id": "u-adm", "email": "chefe@x.com", "full_name": "Chefe",
         "role": "admin", "ativo": True, "gestor_id": None}


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake([dict(ADMIN)])
    monkeypatch.setattr("app.settings_state._supabase", lambda: fake)
    return fake


def _h(email: str = "chefe@x.com", papel: str = "admin") -> dict:
    """Token legítimo: assinado, no prazo, e com o papel que a conta TINHA."""
    return {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": email, "role": papel})}


# ──────────────────────────────────────────────────────────────────────────
# 1. O caso que existia: o token continua bom enquanto a conta continua boa
# ──────────────────────────────────────────────────────────────────────────

def test_admin_ativo_segue_entrando(client: TestClient, banco: _Fake) -> None:
    """Contraprova das outras: sem ela, um 401 constante passaria por acerto."""
    assert client.get("/api/users", headers=_h()).status_code == 200


# ──────────────────────────────────────────────────────────────────────────
# 2. Desativar derruba a sessão aberta
# ──────────────────────────────────────────────────────────────────────────

def test_desativar_invalida_o_token_ja_emitido(client: TestClient, banco: _Fake) -> None:
    """
    O motivo de a etapa existir. O token do usuário desativado continua com
    assinatura válida e dentro do prazo — o que mudou foi só a linha no banco.

    401, e não 403: `static/ui-common.js` intercepta todo 401 e chama `logout()`,
    então o navegador de quem foi desativado volta para o login sozinho. Um 403
    deixaria a pessoa presa numa tela que não carrega nada, com o token morto
    ainda no `localStorage`.
    """
    h = _h()
    assert client.get("/api/users", headers=h).status_code == 200

    banco.tabelas["users"][0]["ativo"] = False

    r = client.get("/api/users", headers=h)
    assert r.status_code == 401, "sessão de conta desativada continuou de pé"


def test_role_disabled_legado_tambem_derruba(client: TestClient, banco: _Fake) -> None:
    """
    Antes de 15/08 desativar gravava `role='disabled'`. `auth.conta_ativa` ainda
    barra esse valor, e a checagem por requisição tem de herdar isso — numa base
    onde a migration não rodou, olhar só `ativo` (ausente, logo verdadeiro por
    omissão) liberaria exatamente quem foi desativado.
    """
    banco.tabelas["users"][0].pop("ativo")
    banco.tabelas["users"][0]["role"] = "disabled"
    assert client.get("/api/users", headers=_h()).status_code == 401


# ──────────────────────────────────────────────────────────────────────────
# 3. Rebaixar vale na hora — o efeito que o plano não tinha registrado
# ──────────────────────────────────────────────────────────────────────────

def test_rebaixar_admin_tira_o_poder_na_requisicao_seguinte(
    client: TestClient, banco: _Fake
) -> None:
    """
    O pior dos dois casos, e o menos visível: a conta continua ativa, então nada
    na tela sugere que algo mudou. Com o papel vindo do token, quem foi rebaixado
    seguia administrando por até 24h.

    403 e não 401 de propósito: a sessão é legítima, o que falta é privilégio.
    Devolver 401 aqui deslogaria um operador válido a cada rota de admin que a
    interface dele tentasse tocar.
    """
    h = _h()
    assert client.get("/api/users", headers=h).status_code == 200

    banco.tabelas["users"][0]["role"] = "user"

    r = client.get("/api/users", headers=h)
    assert r.status_code == 403, "token antigo manteve privilégio de admin"


def test_promover_tambem_vale_na_hora(client: TestClient, banco: _Fake) -> None:
    """
    O mesmo mecanismo no sentido inverso. Importa porque é o que evita o
    contorno: se promover só valesse no próximo login, a saída prática do
    suporte seria alongar o token — desfazendo tudo isto.
    """
    banco.tabelas["users"][0]["role"] = "user"
    h = _h(papel="user")
    assert client.get("/api/users", headers=h).status_code == 403

    banco.tabelas["users"][0]["role"] = "admin"
    assert client.get("/api/users", headers=h).status_code == 200


def test_papel_do_token_nao_promove_ninguem(client: TestClient, banco: _Fake) -> None:
    """
    Quem tiver a `JWT_SECRET_KEY` pode assinar um token dizendo `role: admin`.
    Antes isso bastava. Agora o papel do token é ignorado: vale o do banco.
    """
    banco.tabelas["users"][0]["role"] = "user"
    assert client.get("/api/users", headers=_h(papel="admin")).status_code == 403


# ──────────────────────────────────────────────────────────────────────────
# 4. Conta que sumiu
# ──────────────────────────────────────────────────────────────────────────

def test_conta_excluida_encerra_a_sessao(client: TestClient, banco: _Fake) -> None:
    assert client.get("/api/users", headers=_h("fantasma@x.com")).status_code == 401


def test_troca_de_email_encerra_a_sessao(client: TestClient, banco: _Fake) -> None:
    """
    Efeito de borda que vale fixar: o `sub` do token é o e-mail. Alterado o
    endereço, o token antigo não casa com linha nenhuma e a sessão cai.

    É o comportamento desejável — trocar o e-mail de alguém é mexer na
    identidade — mas não é óbvio, e alguém poderia "consertar" isso resolvendo
    a conta por `id`. Que este teste fique vermelho se tentarem.
    """
    h = _h()
    banco.tabelas["users"][0]["email"] = "chefe.novo@x.com"
    assert client.get("/api/users", headers=h).status_code == 401


# ──────────────────────────────────────────────────────────────────────────
# 5. Falha de leitura barra, mas não desloga
# ──────────────────────────────────────────────────────────────────────────

def test_banco_fora_do_ar_barra_a_requisicao(client: TestClient, banco: _Fake) -> None:
    """
    Fail-closed, como em `CustodiaIndisponivel`: "não consegui verificar" não é
    "está tudo certo". A variante permissiva seria pior que não ter a checagem,
    porque bastaria o banco oscilar para o token velho voltar a valer.
    """
    banco.quebrado = True
    r = client.get("/api/users", headers=_h())
    assert r.status_code == 503


def test_banco_fora_do_ar_nao_desloga_o_usuario(client: TestClient, banco: _Fake) -> None:
    """
    Por que 503 e não 401: o interceptor de `fetch` desloga em qualquer 401. Se
    a indisponibilidade do banco respondesse 401, uma oscilação de rede jogaria
    todo mundo para a tela de login ao mesmo tempo — e a sessão deles nem tinha
    problema nenhum.
    """
    banco.quebrado = True
    assert client.get("/api/users", headers=_h()).status_code != 401


# ──────────────────────────────────────────────────────────────────────────
# 6. Sem diretório de usuários, nada a conferir
# ──────────────────────────────────────────────────────────────────────────

def test_sem_supabase_o_token_ainda_vale(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Dev e testes rodam sem Supabase, e aí não existe conta contra a qual
    conferir. Não é brecha em produção: sem Supabase o `/api/login` responde 503
    e ninguém chega a ter um token para apresentar.

    Sem a fixture `banco` de propósito — é o cenário em que `_supabase()` é None.
    """
    monkeypatch.setattr("app.settings_state._supabase", lambda: None)
    assert client.get("/api/users", headers=_h()).status_code == 200
