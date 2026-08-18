"""
Senha definida por outra pessoa precisa ser trocada no primeiro acesso.

Cadastrar alguém e redefinir a senha de alguém têm em comum o fato de o admin
**conhecer a senha** que digitou. Até 18/08/2026 ela valia indefinidamente: a
pessoa entrava e continuava usando a senha que o chefe escolheu, e o chefe
continuava capaz de entrar como ela.

**A barreira é no servidor.** `require_auth` recusa toda rota que não seja a da
troca enquanto `deve_trocar_senha` for true. Um modal pode ser fechado pelo Esc,
pelo devtools, ou simplesmente ignorado por quem chama a API direto — e é
justamente quem quer contornar que tem motivo para tentar.
"""

from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from app import auth

SENHA_PROVISORIA = "provisoria-123"
SENHA_ESCOLHIDA = "escolhida-pela-pessoa-9"


class _Res:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _Query:
    def __init__(self, linhas: List[Dict[str, Any]]) -> None:
        self._l, self._f = linhas, []
        self._op, self._p = "select", None

    def select(self, *_c: str) -> "_Query":
        return self

    def insert(self, p: Dict[str, Any]) -> "_Query":
        self._op, self._p = "insert", p
        return self

    def update(self, p: Dict[str, Any]) -> "_Query":
        self._op, self._p = "update", p
        return self

    def eq(self, c: str, v: Any) -> "_Query":
        self._f.append((c, "eq", v))
        return self

    def is_(self, c: str, v: Any) -> "_Query":
        self._f.append((c, "is", v))
        return self

    def gt(self, c: str, v: Any) -> "_Query":
        self._f.append((c, "gt", v))
        return self

    def limit(self, _n: int) -> "_Query":
        return self

    def _casa(self, r: Dict[str, Any]) -> bool:
        for c, op, v in self._f:
            a = r.get(c)
            if op == "eq" and a != v:
                return False
            if op == "is" and not (v == "null" and a is None):
                return False
            if op == "gt" and not (a is not None and str(a) > str(v)):
                return False
        return True

    def execute(self) -> _Res:
        if self._op == "insert":
            linha = dict(self._p)
            linha.setdefault("id", f"u-{len(self._l) + 1}")
            linha.setdefault("tentativas", 0)
            linha.setdefault("consumed_at", None)
            self._l.append(linha)
            return _Res([dict(linha)])
        if self._op == "update":
            alt = []
            for r in self._l:
                if self._casa(r):
                    r.update(self._p)
                    alt.append(dict(r))
            return _Res(alt)
        return _Res([dict(r) for r in self._l if self._casa(r)])


class _Fake:
    def __init__(self, tabelas: Dict[str, List[Dict[str, Any]]]) -> None:
        self.tabelas = tabelas

    def table(self, nome: str) -> _Query:
        return _Query(self.tabelas.setdefault(nome, []))


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake({
        "users": [
            {"id": "u-novo", "email": "novo@x.com", "full_name": "Novo",
             "role": "user", "ativo": True, "deve_trocar_senha": True,
             "password_hash": auth.get_password_hash(SENHA_PROVISORIA)},
            {"id": "u-adm", "email": "chefe@x.com", "full_name": "Chefe",
             "role": "admin", "ativo": True, "deve_trocar_senha": False,
             "password_hash": auth.get_password_hash("senha-do-chefe-1")},
        ],
        "user_activity": [],
        "colaborador_cert_selecoes": [],
    })
    monkeypatch.setattr("app.settings_state._supabase", lambda: fake)
    return fake


def _h(email: str) -> dict:
    return {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": email, "role": "user"})}


# ──────────────────────────────────────────────────────────────────────────
# 1. A barreira
# ──────────────────────────────────────────────────────────────────────────

def test_senha_provisoria_bloqueia_o_resto_do_portal(
    client: TestClient, banco: _Fake
) -> None:
    r = client.get("/api/settings", headers=_h("novo@x.com"))
    assert r.status_code == 403


def test_a_recusa_e_reconhecivel_por_cabecalho(
    client: TestClient, banco: _Fake
) -> None:
    """
    O front precisa distinguir este 403 de qualquer outro para abrir o modal
    certo. Por cabeçalho, e não pelo texto: casar por string quebraria assim
    que alguém reescrevesse a frase, e o modal pararia de aparecer — sem erro,
    com a pessoa vendo um portal que não responde a nada.
    """
    r = client.get("/api/settings", headers=_h("novo@x.com"))
    assert r.headers.get("X-Senha-Provisoria") == "1"


def test_a_rota_de_troca_continua_acessivel(client: TestClient, banco: _Fake) -> None:
    """
    Se ela também fosse bloqueada, a pessoa ficaria presa: sem portal e sem
    caminho para sair da situação.
    """
    r = client.post("/api/senha/trocar", headers=_h("novo@x.com"),
                    json={"senha_atual": SENHA_PROVISORIA, "nova_senha": SENHA_ESCOLHIDA})
    assert r.status_code == 200, r.text


def test_quem_ja_tem_senha_propria_nao_e_incomodado(
    client: TestClient, banco: _Fake
) -> None:
    """
    Contraprova. As contas que já existiam escolheram a senha delas em algum
    momento — forçar todo mundo a trocar no deploy seria uma surpresa sem ganho.
    """
    assert client.get("/api/settings", headers=_h("chefe@x.com")).status_code == 200


# ──────────────────────────────────────────────────────────────────────────
# 2. A troca em si
# ──────────────────────────────────────────────────────────────────────────

def test_troca_desliga_a_flag_e_carimba(client: TestClient, banco: _Fake) -> None:
    client.post("/api/senha/trocar", headers=_h("novo@x.com"),
                json={"senha_atual": SENHA_PROVISORIA, "nova_senha": SENHA_ESCOLHIDA})
    linha = banco.tabelas["users"][0]
    assert linha["deve_trocar_senha"] is False
    assert linha.get("senha_alterada_em"), "não carimbou a troca"
    assert auth.verify_password(SENHA_ESCOLHIDA, linha["password_hash"])


def test_exige_a_senha_atual(client: TestClient, banco: _Fake) -> None:
    """
    Parece redundante com a sessão aberta, e não é: com a máquina destravada,
    quem sentar na cadeira definiria a senha nova sem saber a antiga, e a
    pessoa perderia a conta para quem passou por ali.
    """
    r = client.post("/api/senha/trocar", headers=_h("novo@x.com"),
                    json={"senha_atual": "chute", "nova_senha": SENHA_ESCOLHIDA})
    assert r.status_code == 400
    assert banco.tabelas["users"][0]["deve_trocar_senha"] is True


def test_repetir_a_provisoria_nao_conta_como_troca(
    client: TestClient, banco: _Fake
) -> None:
    """
    Sem esta recusa, "trocar a senha" seria satisfeito digitando a mesma —
    e a senha que outra pessoa conhece continuaria valendo, agora com a flag
    desligada e ninguém mais cobrando nada.
    """
    r = client.post("/api/senha/trocar", headers=_h("novo@x.com"),
                    json={"senha_atual": SENHA_PROVISORIA, "nova_senha": SENHA_PROVISORIA})
    assert r.status_code == 422
    assert banco.tabelas["users"][0]["deve_trocar_senha"] is True


def test_senha_curta_recusada(client: TestClient, banco: _Fake) -> None:
    r = client.post("/api/senha/trocar", headers=_h("novo@x.com"),
                    json={"senha_atual": SENHA_PROVISORIA, "nova_senha": "123"})
    assert r.status_code == 422


# ──────────────────────────────────────────────────────────────────────────
# 3. Quem liga a flag
# ──────────────────────────────────────────────────────────────────────────

def test_cadastro_pelo_admin_marca_para_trocar(
    client: TestClient, banco: _Fake
) -> None:
    h = {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": "chefe@x.com", "role": "admin"})}
    r = client.post("/api/users", headers=h, json={
        "email": "recem@x.com", "password": "definida-pelo-chefe",
        "full_name": "Recém", "role": "user",
    })
    assert r.status_code == 200, r.text
    novo = [u for u in banco.tabelas["users"] if u["email"] == "recem@x.com"][0]
    assert novo["deve_trocar_senha"] is True


def test_redefinicao_pelo_admin_marca_para_trocar(
    client: TestClient, banco: _Fake
) -> None:
    """
    Decisão de 18/08: o admin fica sabendo a senha que redefine, então ela é
    provisória pela mesma razão que a do cadastro.
    """
    banco.tabelas["users"][0]["deve_trocar_senha"] = False
    h = {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": "chefe@x.com", "role": "admin"})}
    r = client.post("/api/users/u-novo/reset-password", headers=h,
                    json={"password": "outra-senha-do-chefe"})
    assert r.status_code == 200, r.text
    assert banco.tabelas["users"][0]["deve_trocar_senha"] is True


def test_recuperacao_por_codigo_nao_marca(client: TestClient, banco: _Fake) -> None:
    """
    Aqui foi a própria pessoa quem escolheu, com um código que só ela recebeu.
    Cobrar outra troca em seguida seria pedir duas senhas novas para o mesmo
    esquecimento.
    """
    import app.senha_reset as sr
    import app.main as m

    banco.tabelas["users"][0]["deve_trocar_senha"] = False
    enviados = []
    m._enviar_codigo_por_email = lambda conta, codigo: enviados.append(codigo)

    client.post("/api/senha/codigo", json={"email": "novo@x.com"})
    r = client.post("/api/senha/redefinir", json={
        "email": "novo@x.com", "codigo": enviados[-1], "password": SENHA_ESCOLHIDA,
    })
    assert r.status_code == 200, r.text
    assert banco.tabelas["users"][0]["deve_trocar_senha"] is False
