"""Papel e estado da conta são coisas separadas (15/08/2026).

`users.role` era texto livre com três valores em uso — 'admin', 'user' e
'disabled'. O terceiro não é um papel: é o estado da conta ocupando a mesma
coluna. `deactivate_user` fazia `update({"role": "disabled"})`, então desativar
um administrador **apagava o registro de que ele era administrador**, e reativar
virava adivinhação.

Isso bloqueava a carteira (`docs/PLANO_reorganizacao_portal.md` §3.3): desativar
um gestor apagaria o papel dele e, junto, o sentido das carteiras que criou.

Os testes daqui guardam três coisas que erram em silêncio:

1. **Desativar preserva o papel.** O defeito original não dava erro nenhum — a
   conta era desativada com sucesso, e a informação sumia junto.
2. **O valor legado continua barrando.** Base sem a migration aplicada ainda tem
   `role='disabled'` e `ativo` ausente; ler só `ativo` (undefined → verdadeiro
   por omissão) liberaria exatamente quem foi desativado.
3. **Login devolve o status certo.** O `except Exception` engolia o próprio
   `HTTPException(401)` e o reembalava como 500 — mensagem certa, status errado.
"""

from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import auth
import app.main as m


# ──────────────────────────────────────────────────────────────────────────
# Fake de Supabase — só o subconjunto usado pelas rotas de usuário
# ──────────────────────────────────────────────────────────────────────────

class _Resultado:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _Query:
    def __init__(self, tabela: List[Dict[str, Any]]) -> None:
        self._tabela = tabela
        self._filtros: List[tuple] = []
        self._op = "select"
        self._payload: Optional[Dict[str, Any]] = None

    def select(self, *_c: str) -> "_Query":
        self._op = "select"
        return self

    def insert(self, row: Dict[str, Any]) -> "_Query":
        self._op, self._payload = "insert", row
        return self

    def update(self, row: Dict[str, Any]) -> "_Query":
        self._op, self._payload = "update", row
        return self

    def eq(self, coluna: str, valor: Any) -> "_Query":
        self._filtros.append((coluna, valor))
        return self

    def limit(self, _n: int) -> "_Query":
        return self

    def _casa(self, row: Dict[str, Any]) -> bool:
        return all(row.get(c) == v for c, v in self._filtros)

    def execute(self) -> _Resultado:
        if self._op == "select":
            return _Resultado([dict(r) for r in self._tabela if self._casa(r)])
        if self._op == "insert":
            assert self._payload is not None
            self._tabela.append(dict(self._payload))
            return _Resultado([dict(self._payload)])
        if self._op == "update":
            assert self._payload is not None
            tocados = []
            for r in self._tabela:
                if self._casa(r):
                    r.update(self._payload)
                    tocados.append(dict(r))
            return _Resultado(tocados)
        raise AssertionError(self._op)


class _FakeSupabase:
    def __init__(self, users: List[Dict[str, Any]]) -> None:
        self.tabelas = {"users": users}

    def table(self, nome: str) -> _Query:
        return _Query(self.tabelas.setdefault(nome, []))


SENHA = "segredo123"


def _users() -> List[Dict[str, Any]]:
    h = auth.get_password_hash(SENHA)
    return [
        {"id": "u-admin", "email": "chefe@empresa.com", "full_name": "Chefe",
         "role": "admin", "ativo": True, "password_hash": h},
        # Segundo admin ativo de propósito: sem ele, desativar ou rebaixar o
        # primeiro esbarraria na regra do último administrador (409), e os
        # testes de "o papel é preservado" não chegariam a exercitar o que
        # querem. A regra em si é testada à parte, na seção 6.
        {"id": "u-admin2", "email": "chefe2@empresa.com", "full_name": "Chefe 2",
         "role": "admin", "ativo": True, "password_hash": h},
        {"id": "u-gestor", "email": "gestor@empresa.com", "full_name": "Gestor",
         "role": "gestor", "ativo": True, "password_hash": h},
        {"id": "u-off", "email": "saiu@empresa.com", "full_name": "Saiu",
         "role": "admin", "ativo": False, "password_hash": h},
        # Sem a coluna `ativo`: é como a base fica antes da migration rodar.
        {"id": "u-legado", "email": "legado@empresa.com", "full_name": "Legado",
         "role": "disabled", "password_hash": h},
    ]


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _FakeSupabase:
    fake = _FakeSupabase(_users())
    monkeypatch.setattr("app.settings_state._supabase", lambda: fake)
    monkeypatch.setattr(m, "load_settings", lambda *a, **k: None)
    return fake


def _linha(banco: _FakeSupabase, user_id: str) -> Dict[str, Any]:
    return next(u for u in banco.tabelas["users"] if u["id"] == user_id)


def _admin_headers() -> dict:
    return {"Authorization": f"Bearer {auth.create_access_token({'sub': 'chefe@empresa.com', 'role': 'admin'})}"}


# ──────────────────────────────────────────────────────────────────────────
# 1. A regra, isolada
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("user,esperado", [
    ({"role": "admin", "ativo": True}, True),
    ({"role": "admin", "ativo": False}, False),
    ({"role": "gestor", "ativo": True}, True),
    # Coluna ausente = base sem a migration. Conta normal continua entrando...
    ({"role": "user"}, True),
    # ...mas o desativado da forma antiga NÃO. Se este virasse True, todo
    # desativado de antes da migration voltaria a entrar e a receber e-mail.
    ({"role": "disabled"}, False),
    ({"role": "Disabled  "}, False),
])
def test_conta_ativa(user: dict, esperado: bool) -> None:
    assert auth.conta_ativa(user) is esperado


# ──────────────────────────────────────────────────────────────────────────
# 2. Login — status certo e estado respeitado
# ──────────────────────────────────────────────────────────────────────────

def test_senha_errada_devolve_401_e_nao_500(client: TestClient, banco) -> None:
    """
    O `except Exception` engolia o `HTTPException(401)` erguido logo acima e o
    devolvia como 500 com "401: E-mail ou senha incorretos." no corpo. Todo
    tratamento no front que olhasse o código via "erro do servidor" onde havia
    credencial inválida.
    """
    r = client.post("/api/login", json={"email": "chefe@empresa.com", "password": "errada"})
    assert r.status_code == 401, r.text


def test_email_inexistente_devolve_401(client: TestClient, banco) -> None:
    r = client.post("/api/login", json={"email": "ninguem@empresa.com", "password": SENHA})
    assert r.status_code == 401


def test_usuario_ativo_entra(client: TestClient, banco) -> None:
    r = client.post("/api/login", json={"email": "chefe@empresa.com", "password": SENHA})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "admin"


def test_desativado_nao_entra_mesmo_com_papel_preservado(client: TestClient, banco) -> None:
    """`u-off` continua com role='admin' — o que barra é `ativo`, não o papel."""
    r = client.post("/api/login", json={"email": "saiu@empresa.com", "password": SENHA})
    assert r.status_code == 403, r.text


def test_desativado_na_forma_antiga_nao_entra(client: TestClient, banco) -> None:
    """Sem a coluna `ativo`, `role='disabled'` ainda é o que diz que saiu."""
    r = client.post("/api/login", json={"email": "legado@empresa.com", "password": SENHA})
    assert r.status_code == 403, r.text


# ──────────────────────────────────────────────────────────────────────────
# 3. Desativar preserva o papel — o defeito que originou tudo
# ──────────────────────────────────────────────────────────────────────────

def test_desativar_preserva_o_papel(client: TestClient, banco) -> None:
    r = client.post("/api/users/u-admin/deactivate", headers=_admin_headers())
    assert r.status_code == 200, r.text

    linha = _linha(banco, "u-admin")
    assert linha["ativo"] is False
    assert linha["role"] == "admin", (
        "o papel foi sobrescrito — é exatamente o defeito de 15/08: reativar "
        "este usuário viraria adivinhação"
    )


def test_reativar_devolve_o_papel_original(client: TestClient, banco) -> None:
    r = client.post("/api/users/u-off/reactivate", headers=_admin_headers())
    assert r.status_code == 200, r.text

    linha = _linha(banco, "u-off")
    assert linha["ativo"] is True
    assert linha["role"] == "admin", "reativar tem de devolver o papel que estava lá"


def test_desativar_gestor_nao_perde_o_papel(client: TestClient, banco) -> None:
    """
    É o caso que trava a carteira: perder o papel do gestor levaria junto o
    sentido das carteiras que ele criou.
    """
    client.post("/api/users/u-gestor/deactivate", headers=_admin_headers())
    assert _linha(banco, "u-gestor")["role"] == "gestor"


# ──────────────────────────────────────────────────────────────────────────
# 4. Vocabulário de papéis e compatibilidade do cliente antigo
# ──────────────────────────────────────────────────────────────────────────

def test_update_com_role_disabled_desativa_sem_virar_papel(client: TestClient, banco) -> None:
    """
    Cliente antigo mandando `role="disabled"` sempre quis dizer "desative" —
    nunca "o papel dele agora é disabled", embora fosse isso que acontecia.
    """
    r = client.put(
        "/api/users/u-admin",
        json={"email": "chefe@empresa.com", "full_name": "Chefe", "role": "disabled"},
        headers=_admin_headers(),
    )
    assert r.status_code == 200, r.text

    linha = _linha(banco, "u-admin")
    assert linha["ativo"] is False
    assert linha["role"] == "admin"


def test_update_recusa_papel_desconhecido(client: TestClient, banco) -> None:
    r = client.put(
        "/api/users/u-admin",
        json={"email": "chefe@empresa.com", "full_name": "Chefe", "role": "superadmin"},
        headers=_admin_headers(),
    )
    assert r.status_code == 422, r.text
    assert _linha(banco, "u-admin")["role"] == "admin"


def test_criar_usuario_recusa_papel_desconhecido(client: TestClient, banco) -> None:
    """
    Não havia validação nenhuma aqui: qualquer string virava papel. Com o CHECK
    no banco isso passaria a estourar como 400 genérico do PostgREST.
    """
    r = client.post(
        "/api/users",
        json={"email": "novo@empresa.com", "password": SENHA,
              "full_name": "Novo", "role": "chefinho"},
        headers=_admin_headers(),
    )
    assert r.status_code == 422, r.text
    assert not [u for u in banco.tabelas["users"] if u["email"] == "novo@empresa.com"]


def test_criar_gestor_funciona(client: TestClient, banco) -> None:
    r = client.post(
        "/api/users",
        json={"email": "novo@empresa.com", "password": SENHA,
              "full_name": "Novo", "role": "gestor"},
        headers=_admin_headers(),
    )
    assert r.status_code == 200, r.text
    novo = next(u for u in banco.tabelas["users"] if u["email"] == "novo@empresa.com")
    assert novo["role"] == "gestor" and novo["ativo"] is True


# ──────────────────────────────────────────────────────────────────────────
# 5. Aresta gestor -> operador
# ──────────────────────────────────────────────────────────────────────────

def test_gestor_de_si_mesmo_e_recusado(client: TestClient, banco) -> None:
    """
    O banco também recusa (CHECK), mas 422 com motivo é melhor que 400 genérico
    do PostgREST — e "meus operadores" incluindo a própria pessoa é laço lógico.
    """
    r = client.put(
        "/api/users/u-gestor",
        json={"email": "gestor@empresa.com", "full_name": "Gestor",
              "role": "gestor", "gestor_id": "u-gestor"},
        headers=_admin_headers(),
    )
    assert r.status_code == 422, r.text


def test_vincular_operador_a_um_gestor(client: TestClient, banco) -> None:
    r = client.put(
        "/api/users/u-admin",
        json={"email": "chefe@empresa.com", "full_name": "Chefe",
              "role": "user", "gestor_id": "u-gestor"},
        headers=_admin_headers(),
    )
    assert r.status_code == 200, r.text
    assert _linha(banco, "u-admin")["gestor_id"] == "u-gestor"


# ──────────────────────────────────────────────────────────────────────────
# 6. A tela acompanha
# ──────────────────────────────────────────────────────────────────────────

def test_tela_oferece_reativar() -> None:
    """
    Sem contrapartida do desativar, o único caminho de volta era editar o nível
    na mão e escolher um papel de memória — que é como a informação se perdia.
    """
    from pathlib import Path
    html = (Path(__file__).resolve().parent.parent / "templates" / "usuarios.html").read_text(encoding="utf-8")
    assert "/reactivate" in html
    assert "data-action=\"reativar\"" in html
    assert "'disabled'" not in html.split("function estaAtivo")[1].split("function roleLabel")[0].replace(
        "String(u.role || '').toLowerCase() === 'disabled'", ""
    ), "o estado saiu do papel; 'disabled' só sobrevive como leitura do legado"


# ──────────────────────────────────────────────────────────────────────────
# 6. Não pode sobrar zero administrador ativo
#
# O buraco é sem fundo: a tela de Usuários é `require_admin`, então sem admin
# ativo **não há como voltar pela interface** — só SQL direto no banco. E não
# é hipótese: em produção há UM administrador ativo.
#
# A regra é "tem de sobrar um", e não "não mexa em si mesmo". A segunda parece
# equivalente e não é: com dois admins, um poderia rebaixar o outro e depois
# sair, e nenhuma das duas ações seria sobre si mesmo.
# ──────────────────────────────────────────────────────────────────────────

@pytest.fixture
def unico_admin(banco: _FakeSupabase) -> _FakeSupabase:
    """Deixa `u-admin` como o único administrador ativo."""
    for u in banco.tabelas["users"]:
        if u["id"] == "u-admin2":
            u["role"] = "user"
    return banco


def test_ultimo_admin_nao_pode_se_desativar(
    client: TestClient, unico_admin: _FakeSupabase
) -> None:
    r = client.post("/api/users/u-admin/deactivate", headers=_admin_headers())
    assert r.status_code == 409, r.text
    assert _linha(unico_admin, "u-admin")["ativo"] is True


def test_ultimo_admin_nao_pode_se_rebaixar(
    client: TestClient, unico_admin: _FakeSupabase
) -> None:
    """
    Rebaixar é o caminho menos óbvio para o mesmo buraco, e por isso o mais
    perigoso: quem faz não está pensando em perder acesso.
    """
    r = client.put(
        "/api/users/u-admin",
        json={"email": "chefe@empresa.com", "full_name": "Chefe", "role": "user"},
        headers=_admin_headers(),
    )
    assert r.status_code == 409, r.text
    assert _linha(unico_admin, "u-admin")["role"] == "admin"


def test_ultimo_admin_nao_pode_ser_apagado(
    client: TestClient, unico_admin: _FakeSupabase
) -> None:
    r = client.delete("/api/users/u-admin", headers=_admin_headers())
    assert r.status_code == 409, r.text
    assert any(u["id"] == "u-admin" for u in unico_admin.tabelas["users"])


def test_role_disabled_legado_tambem_esbarra_na_regra(
    client: TestClient, unico_admin: _FakeSupabase
) -> None:
    """
    O cliente antigo desativa mandando `role="disabled"`. Se esse caminho não
    passasse pela verificação, sobraria uma porta aberta para o mesmo buraco.
    """
    r = client.put(
        "/api/users/u-admin",
        json={"email": "chefe@empresa.com", "full_name": "Chefe", "role": "disabled"},
        headers=_admin_headers(),
    )
    assert r.status_code == 409, r.text
    assert _linha(unico_admin, "u-admin")["ativo"] is True


def test_com_dois_admins_desativar_um_e_permitido(
    client: TestClient, banco: _FakeSupabase
) -> None:
    """
    A regra não pode virar "administrador é intocável" — isso impediria a
    rotina normal de desligar alguém que saiu da empresa.
    """
    r = client.post("/api/users/u-admin/deactivate", headers=_admin_headers())
    assert r.status_code == 200, r.text
    assert _linha(banco, "u-admin")["ativo"] is False


def test_admin_inativo_nao_conta_como_administrador(
    client: TestClient, banco: _FakeSupabase
) -> None:
    """
    `u-off` tem role='admin' e está inativo. Contá-lo deixaria o portal sem
    ninguém que possa entrar — o número certo é o de admins que conseguem
    fazer login.
    """
    for u in banco.tabelas["users"]:
        if u["id"] == "u-admin2":
            u["role"] = "user"
    assert _linha(banco, "u-off")["role"] == "admin"
    assert _linha(banco, "u-off")["ativo"] is False

    r = client.post("/api/users/u-admin/deactivate", headers=_admin_headers())
    assert r.status_code == 409, "o admin inativo não deveria ter contado"


def test_falha_ao_verificar_recusa_em_vez_de_liberar(
    client: TestClient, banco: _FakeSupabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Não dá para afirmar que sobra admin → recusa. O custo é uma operação
    adiada; o do contrário é um portal sem dono.
    """
    class _Quebrado:
        def table(self, _n):
            raise RuntimeError("banco fora do ar")

    monkeypatch.setattr("app.settings_state._supabase", lambda: _Quebrado())
    r = client.post("/api/users/u-admin/deactivate", headers=_admin_headers())
    assert r.status_code == 503, r.text


# ──────────────────────────────────────────────────────────────────────────
# 7. Integridade: e-mail identifica a pessoa
#
# Nada impedia duas contas com o mesmo e-mail. O login faz
# `.eq("email", ...).limit(1)` e pega UMA arbitrariamente — a outra pessoa
# nunca mais entra, sem mensagem nenhuma. E `_resolve_user_id` passa a
# resolver para a conta errada, levando junto a carteira (quem pode instalar
# o quê) e a trilha (quem instalou).
# ──────────────────────────────────────────────────────────────────────────

def test_nao_cria_com_email_ja_usado(client: TestClient, banco: _FakeSupabase) -> None:
    r = client.post(
        "/api/users",
        json={"email": "CHEFE@empresa.com", "password": SENHA,
              "full_name": "Impostor", "role": "user"},
        headers=_admin_headers(),
    )
    assert r.status_code == 409, r.text
    assert sum(1 for u in banco.tabelas["users"] if "chefe@" in u["email"]) == 1


def test_nao_edita_para_email_de_outro(client: TestClient, banco: _FakeSupabase) -> None:
    r = client.put(
        "/api/users/u-gestor",
        json={"email": "chefe@empresa.com", "full_name": "Gestor", "role": "gestor"},
        headers=_admin_headers(),
    )
    assert r.status_code == 409, r.text
    assert _linha(banco, "u-gestor")["email"] == "gestor@empresa.com"


def test_manter_o_proprio_email_na_edicao_e_permitido(
    client: TestClient, banco: _FakeSupabase
) -> None:
    """
    A checagem tem de ignorar a própria linha — senão salvar sem mexer no
    e-mail acusaria duplicata contra si mesmo, e editar o nome viraria
    impossível.
    """
    r = client.put(
        "/api/users/u-gestor",
        json={"email": "gestor@empresa.com", "full_name": "Gestor Editado", "role": "gestor"},
        headers=_admin_headers(),
    )
    assert r.status_code == 200, r.text
    assert _linha(banco, "u-gestor")["full_name"] == "Gestor Editado"


def test_email_e_normalizado_para_minusculas(client: TestClient, banco: _FakeSupabase) -> None:
    """
    O login compara normalizado. Gravar "Fulano@x.com" cru deixaria a conta
    inacessível — e abriria espaço para uma segunda com o mesmo endereço.
    """
    r = client.post(
        "/api/users",
        json={"email": "  NOVO@Empresa.COM  ", "password": SENHA,
              "full_name": "Novo", "role": "user"},
        headers=_admin_headers(),
    )
    assert r.status_code == 200, r.text
    assert any(u["email"] == "novo@empresa.com" for u in banco.tabelas["users"])


@pytest.mark.parametrize("email", ["sem-arroba", "@semlocal.com", "sem@dominio", "a b@x.com", ""])
def test_email_implausivel_e_recusado(
    client: TestClient, banco: _FakeSupabase, email: str
) -> None:
    """
    Validação frouxa de propósito: "@" com algo dos dois lados e ponto no
    domínio. Regex de e-mail "completo" rejeita endereço válido e dá falsa
    sensação de rigor — o que prova que um e-mail funciona é chegar mensagem.
    """
    r = client.post(
        "/api/users",
        json={"email": email, "password": SENHA, "full_name": "X", "role": "user"},
        headers=_admin_headers(),
    )
    assert r.status_code == 422, r.text


def test_senha_curta_e_recusada_ao_criar(client: TestClient, banco: _FakeSupabase) -> None:
    """
    `reset_user_password` já exigia 6. Criar era mais permissivo que
    redefinir: dava para nascer com senha de um caractere e só descobrir o
    rigor ao trocá-la.
    """
    r = client.post(
        "/api/users",
        json={"email": "z@empresa.com", "password": "12345", "full_name": "Z", "role": "user"},
        headers=_admin_headers(),
    )
    assert r.status_code == 422, r.text
    assert "6" in r.json()["detail"]
