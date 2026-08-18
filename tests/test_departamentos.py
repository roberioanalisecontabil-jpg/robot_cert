"""
Departamentos e líderes.

O departamento é o primeiro recorte real de permissão do portal. Até 18/08/2026
a regra era: `admin` e `gestor` têm alcance total, `user` só instala o que está
na carteira — ou seja, **qualquer gestor liberava qualquer cliente para qualquer
operador**. `users.gestor_id` existia e era exibido, mas não autorizava nada.

Este arquivo cobre a estrutura (setores, líderes, vínculo). O recorte de
permissão em si é a etapa seguinte, e tem testes próprios: sem eles, ter
departamento seria só organização.
"""

from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from app import auth


class _Res:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _Query:
    def __init__(self, linhas: List[Dict[str, Any]], banco: "_Fake", nome: str) -> None:
        self._l, self._b, self._n = linhas, banco, nome
        self._f: List = []
        self._op, self._p = "select", None

    def select(self, *_c: str) -> "_Query":
        return self

    def insert(self, p: Any) -> "_Query":
        self._op, self._p = "insert", p
        return self

    def update(self, p: Dict[str, Any]) -> "_Query":
        self._op, self._p = "update", p
        return self

    def delete(self) -> "_Query":
        self._op = "delete"
        return self

    def eq(self, c: str, v: Any) -> "_Query":
        self._f.append((c, v))
        return self

    def limit(self, _n: int) -> "_Query":
        return self

    def _casa(self, r: Dict[str, Any]) -> bool:
        return all(r.get(c) == v for c, v in self._f)

    def execute(self) -> _Res:
        if self._n in self._b.quebrado:
            raise RuntimeError(self._b.quebrado[self._n])
        if self._op == "insert":
            linhas = self._p if isinstance(self._p, list) else [self._p]
            saida = []
            for x in linhas:
                linha = dict(x)
                linha.setdefault("id", f"{self._n[:3]}-{len(self._l) + 1}")
                self._l.append(linha)
                saida.append(dict(linha))
            return _Res(saida)
        if self._op == "update":
            alt = []
            for r in self._l:
                if self._casa(r):
                    r.update(self._p)
                    alt.append(dict(r))
            return _Res(alt)
        if self._op == "delete":
            fora = [r for r in self._l if self._casa(r)]
            self._l[:] = [r for r in self._l if not self._casa(r)]
            # O ON DELETE CASCADE/SET NULL do banco, imitado: sem isto o teste
            # veria um mundo mais limpo que o real e não pegaria órfão nenhum.
            if self._n == "departamento":
                for d in fora:
                    did = d.get("id")
                    lid = self._b.tabelas.get("departamento_lider", [])
                    lid[:] = [x for x in lid if x.get("departamento_id") != did]
                    for u in self._b.tabelas.get("users", []):
                        if u.get("departamento_id") == did:
                            u["departamento_id"] = None
            return _Res(fora)
        return _Res([dict(r) for r in self._l if self._casa(r)])


class _Fake:
    def __init__(self, tabelas: Dict[str, List[Dict[str, Any]]]) -> None:
        self.tabelas = tabelas
        self.quebrado: Dict[str, str] = {}

    def table(self, nome: str) -> _Query:
        return _Query(self.tabelas.setdefault(nome, []), self, nome)


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake({
        "users": [
            {"id": "u-adm", "email": "chefe@x.com", "full_name": "Chefe", "role": "admin",
             "ativo": True, "departamento_id": None, "deve_trocar_senha": False},
            {"id": "u-lider", "email": "lider@x.com", "full_name": "Lider Fiscal",
             "role": "gestor", "ativo": True, "departamento_id": "dep-1",
             "deve_trocar_senha": False},
            {"id": "u-op", "email": "op@x.com", "full_name": "Operador", "role": "user",
             "ativo": True, "departamento_id": "dep-1", "deve_trocar_senha": False},
            {"id": "u-saiu", "email": "saiu@x.com", "full_name": "Saiu", "role": "user",
             "ativo": False, "departamento_id": None, "deve_trocar_senha": False},
        ],
        "departamento": [{"id": "dep-1", "nome": "Fiscal", "criado_em": "2026-08-18T10:00:00Z"}],
        "departamento_lider": [{"departamento_id": "dep-1", "user_id": "u-lider"}],
    })
    monkeypatch.setattr("app.settings_state._supabase", lambda: fake)
    return fake


def _admin() -> dict:
    return {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": "chefe@x.com", "role": "admin"})}


def _operador() -> dict:
    return {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": "op@x.com", "role": "user"})}


# ──────────────────────────────────────────────────────────────────────────
# 1. Listagem
# ──────────────────────────────────────────────────────────────────────────

def test_lista_traz_lideres_e_contagem(client: TestClient, banco: _Fake) -> None:
    """
    A contagem vem junto porque é o que responde "posso apagar este?" sem um
    segundo clique — e apagar um setor com gente dentro deixa essas pessoas sem
    departamento, o que ninguém quer descobrir depois.
    """
    r = client.get("/api/departamentos", headers=_admin())
    assert r.status_code == 200, r.text
    dep = r.json()[0]
    assert dep["nome"] == "Fiscal"
    assert [l["nome"] for l in dep["lideres"]] == ["Lider Fiscal"]
    assert dep["membros"] == 2


def test_listar_e_de_admin(client: TestClient, banco: _Fake) -> None:
    assert client.get("/api/departamentos", headers=_operador()).status_code == 403


# ──────────────────────────────────────────────────────────────────────────
# 2. Criar e renomear
# ──────────────────────────────────────────────────────────────────────────

def test_cria_departamento(client: TestClient, banco: _Fake) -> None:
    r = client.post("/api/departamentos", headers=_admin(), json={"nome": "  Contábil  "})
    assert r.status_code == 200, r.text
    assert any(d["nome"] == "Contábil" for d in banco.tabelas["departamento"]), \
        "não aparou os espaços — 'Contábil ' e 'Contábil' virariam dois setores"


def test_nome_vazio_recusado(client: TestClient, banco: _Fake) -> None:
    assert client.post("/api/departamentos", headers=_admin(),
                       json={"nome": "   "}).status_code == 422


def test_nome_duplicado_da_mensagem_legivel(
    client: TestClient, banco: _Fake
) -> None:
    """
    O índice único é sobre `lower(btrim(nome))`. A mensagem crua do PostgREST
    seria "duplicate key value violates unique constraint", que não ajuda quem
    está olhando um campo de texto.
    """
    banco.quebrado["departamento"] = "duplicate key value violates unique constraint"
    r = client.post("/api/departamentos", headers=_admin(), json={"nome": "Fiscal"})
    assert r.status_code == 409
    assert "Fiscal" in r.json()["detail"]


def test_criar_e_de_admin(client: TestClient, banco: _Fake) -> None:
    assert client.post("/api/departamentos", headers=_operador(),
                       json={"nome": "X"}).status_code == 403


# ──────────────────────────────────────────────────────────────────────────
# 3. Líderes
# ──────────────────────────────────────────────────────────────────────────

def test_define_lideres_substituindo(client: TestClient, banco: _Fake) -> None:
    """
    Substitui em vez de somar porque a tela mostra a lista inteira: se o
    servidor só acrescentasse, tirar alguém exigiria outra rota e a tela
    passaria a mentir sobre o que salvou.
    """
    r = client.put("/api/departamentos/dep-1/lideres", headers=_admin(),
                   json={"lideres": ["u-adm"]})
    assert r.status_code == 200, r.text
    atuais = [l["user_id"] for l in banco.tabelas["departamento_lider"]]
    assert atuais == ["u-adm"], "o líder anterior não saiu"


def test_lista_vazia_deixa_o_setor_sem_lider(client: TestClient, banco: _Fake) -> None:
    """Tirar todos é uma operação válida — e a tela marca o setor como pendente."""
    r = client.put("/api/departamentos/dep-1/lideres", headers=_admin(), json={"lideres": []})
    assert r.status_code == 200
    assert banco.tabelas["departamento_lider"] == []


def test_conta_desativada_nao_pode_liderar(client: TestClient, banco: _Fake) -> None:
    """
    Líder desativado não entra no portal, então o setor ficaria com um
    responsável que não consegue liberar nada — a mesma situação de não ter
    líder, mas parecendo resolvida.
    """
    r = client.put("/api/departamentos/dep-1/lideres", headers=_admin(),
                   json={"lideres": ["u-saiu"]})
    assert r.status_code == 422
    assert [l["user_id"] for l in banco.tabelas["departamento_lider"]] == ["u-lider"], \
        "recusou mas já tinha apagado os líderes existentes"


def test_pessoa_inexistente_recusada(client: TestClient, banco: _Fake) -> None:
    assert client.put("/api/departamentos/dep-1/lideres", headers=_admin(),
                      json={"lideres": ["u-fantasma"]}).status_code == 422


def test_repetida_na_lista_recusada(client: TestClient, banco: _Fake) -> None:
    assert client.put("/api/departamentos/dep-1/lideres", headers=_admin(),
                      json={"lideres": ["u-adm", "u-adm"]}).status_code == 422


# ──────────────────────────────────────────────────────────────────────────
# 4. Apagar
# ──────────────────────────────────────────────────────────────────────────

def test_apagar_solta_as_pessoas_sem_apaga_las(
    client: TestClient, banco: _Fake
) -> None:
    """
    `ON DELETE SET NULL`, e não CASCADE. Perder o vínculo é corrigível na tela;
    perder as contas não seria.
    """
    r = client.delete("/api/departamentos/dep-1", headers=_admin())
    assert r.status_code == 200

    assert banco.tabelas["departamento"] == []
    emails = {u["email"] for u in banco.tabelas["users"]}
    assert "op@x.com" in emails and "lider@x.com" in emails, "apagou pessoas junto com o setor"
    assert all(u.get("departamento_id") is None for u in banco.tabelas["users"])


def test_apagar_leva_as_liderancas(client: TestClient, banco: _Fake) -> None:
    """
    Liderança órfã daria alcance sobre um setor que não existe, e o código
    teria de adivinhar o que fazer com ela.
    """
    client.delete("/api/departamentos/dep-1", headers=_admin())
    assert banco.tabelas["departamento_lider"] == []


def test_apagar_e_de_admin(client: TestClient, banco: _Fake) -> None:
    assert client.delete("/api/departamentos/dep-1", headers=_operador()).status_code == 403


# ──────────────────────────────────────────────────────────────────────────
# 5. O vínculo com a pessoa
# ──────────────────────────────────────────────────────────────────────────

def test_edicao_grava_o_departamento(client: TestClient, banco: _Fake) -> None:
    r = client.put("/api/users/u-op", headers=_admin(), json={
        "email": "op@x.com", "full_name": "Operador", "role": "user",
        "departamento_id": "dep-1",
    })
    assert r.status_code == 200, r.text
    assert banco.tabelas["users"][2]["departamento_id"] == "dep-1"


def test_string_vazia_tira_a_pessoa_do_setor(client: TestClient, banco: _Fake) -> None:
    """
    Omitir mantém o que está gravado; string vazia limpa. Sem a distinção, não
    haveria como tirar alguém de um setor sem inventar um valor.
    """
    r = client.put("/api/users/u-op", headers=_admin(), json={
        "email": "op@x.com", "full_name": "Operador", "role": "user",
        "departamento_id": "",
    })
    assert r.status_code == 200, r.text
    assert banco.tabelas["users"][2]["departamento_id"] is None


def test_omitir_mantem_o_setor(client: TestClient, banco: _Fake) -> None:
    r = client.put("/api/users/u-op", headers=_admin(), json={
        "email": "op@x.com", "full_name": "Operador", "role": "user",
    })
    assert r.status_code == 200, r.text
    assert banco.tabelas["users"][2]["departamento_id"] == "dep-1"
