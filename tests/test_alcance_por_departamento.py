"""
O líder libera só o seu setor.

Até 18/08/2026 a regra era: `admin` e `gestor` com **alcance total**, `user`
limitado à carteira. Ou seja, qualquer gestor liberava qualquer cliente do
acervo para qualquer operador do portal. `users.gestor_id` existia e era
exibido, mas não autorizava nada — era informativo.

Este arquivo guarda o primeiro recorte real de permissão do sistema.

**A tela não é a barreira.** `/api/carteira/operadores` já devolve só quem o
líder alcança, mas isso é conveniência: quem chamar a API direto com outro
`user_id` tem de esbarrar no servidor. Metade dos testes daqui existe por
causa disso.
"""

from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

import app.cert_installer as ci
import app.main as m
from app import auth

FISCAL, CONTABIL = "dep-fiscal", "dep-contabil"
DOC = "33706943000193"


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

    def upsert(self, rows: Any, on_conflict: Optional[str] = None) -> "_Query":
        self._op, self._p = "upsert", rows
        return self

    def delete(self) -> "_Query":
        self._op = "delete"
        return self

    def eq(self, c: str, v: Any) -> "_Query":
        self._f.append((c, v))
        return self

    def in_(self, c: str, vs: List[Any]) -> "_Query":
        self._f.append((c, ("in", list(vs))))
        return self

    def order(self, *_a: Any, **_k: Any) -> "_Query":
        return self

    def limit(self, _n: int) -> "_Query":
        return self

    def _casa(self, r: Dict[str, Any]) -> bool:
        for c, v in self._f:
            if isinstance(v, tuple) and v and v[0] == "in":
                if r.get(c) not in v[1]:
                    return False
            elif r.get(c) != v:
                return False
        return True

    def execute(self) -> _Res:
        if self._b.quebrado.get(self._n):
            raise RuntimeError(f"banco fora do ar ao ler {self._n}")
        if self._op == "upsert":
            linhas = self._p if isinstance(self._p, list) else [self._p]
            self._l.extend(dict(x) for x in linhas)
            return _Res([dict(x) for x in linhas])
        if self._op == "delete":
            fora = [r for r in self._l if self._casa(r)]
            self._l[:] = [r for r in self._l if not self._casa(r)]
            return _Res(fora)
        return _Res([dict(r) for r in self._l if self._casa(r)])


class _Fake:
    def __init__(self, tabelas: Dict[str, List[Dict[str, Any]]]) -> None:
        self.tabelas = tabelas
        self.quebrado: Dict[str, bool] = {}

    def table(self, nome: str) -> _Query:
        return _Query(self.tabelas.setdefault(nome, []), self, nome)


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake({
        "users": [
            {"id": "u-adm", "email": "admin@x.com", "full_name": "Admin",
             "role": "admin", "ativo": True, "departamento_id": None},
            {"id": "u-lf", "email": "lider.fiscal@x.com", "full_name": "Líder Fiscal",
             "role": "gestor", "ativo": True, "departamento_id": FISCAL},
            {"id": "u-lc", "email": "lider.contabil@x.com", "full_name": "Líder Contábil",
             "role": "gestor", "ativo": True, "departamento_id": CONTABIL},
            {"id": "u-sem", "email": "gestor.sem.setor@x.com", "full_name": "Gestor Sem Setor",
             "role": "gestor", "ativo": True, "departamento_id": None},
            {"id": "u-fiscal", "email": "op.fiscal@x.com", "full_name": "Op Fiscal",
             "role": "user", "ativo": True, "departamento_id": FISCAL},
            {"id": "u-contabil", "email": "op.contabil@x.com", "full_name": "Op Contábil",
             "role": "user", "ativo": True, "departamento_id": CONTABIL},
            {"id": "u-solto", "email": "op.solto@x.com", "full_name": "Op Sem Setor",
             "role": "user", "ativo": True, "departamento_id": None},
        ],
        "departamento": [
            {"id": FISCAL, "nome": "Fiscal"},
            {"id": CONTABIL, "nome": "Contábil"},
        ],
        "departamento_lider": [
            {"departamento_id": FISCAL, "user_id": "u-lf"},
            {"departamento_id": CONTABIL, "user_id": "u-lc"},
        ],
        "carteira": [],
        "cert_snapshots": [],
    })
    monkeypatch.setattr(ci, "_supabase", lambda: fake)
    monkeypatch.setattr("app.settings_state._supabase", lambda: fake)
    monkeypatch.setattr(m, "_resolve_user_id",
                        lambda email: {
                            "admin@x.com": "u-adm",
                            "lider.fiscal@x.com": "u-lf",
                            "lider.contabil@x.com": "u-lc",
                            "gestor.sem.setor@x.com": "u-sem",
                        }.get(email))
    return fake


def _h(email: str, papel: str) -> dict:
    return {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": email, "role": papel})}


ADMIN = ("admin@x.com", "admin")
LIDER_FISCAL = ("lider.fiscal@x.com", "gestor")
LIDER_CONTABIL = ("lider.contabil@x.com", "gestor")
GESTOR_SEM_SETOR = ("gestor.sem.setor@x.com", "gestor")


def _atribuir(client: TestClient, quem, alvo: str):
    return client.post("/api/carteira", headers=_h(*quem),
                       json={"user_id": alvo, "documentos": [DOC]})


# ──────────────────────────────────────────────────────────────────────────
# 1. O recorte
# ──────────────────────────────────────────────────────────────────────────

def test_lider_libera_dentro_do_setor(client: TestClient, banco: _Fake) -> None:
    assert _atribuir(client, LIDER_FISCAL, "u-fiscal").status_code == 200


def test_lider_nao_libera_fora_do_setor(client: TestClient, banco: _Fake) -> None:
    """
    O ponto da etapa. Antes de 18/08 isto respondia 200: qualquer gestor
    liberava para qualquer operador do portal.
    """
    r = _atribuir(client, LIDER_FISCAL, "u-contabil")
    assert r.status_code == 403
    assert not banco.tabelas["carteira"], "gravou mesmo recusando"


def test_a_tela_nao_e_a_barreira(client: TestClient, banco: _Fake) -> None:
    """
    `/api/carteira/operadores` já filtra, mas isso é conveniência de tela.
    Quem monta a chamada à mão com outro `user_id` tem de esbarrar no servidor
    — senão o recorte seria apenas um filtro visual.
    """
    lista = client.get("/api/carteira/operadores", headers=_h(*LIDER_FISCAL)).json()
    ids = {o["id"] for o in lista["operadores"]}
    assert "u-contabil" not in ids, "a tela mostrou alguém de outro setor"

    # E a chamada direta, ignorando a tela:
    assert _atribuir(client, LIDER_FISCAL, "u-contabil").status_code == 403


def test_pessoa_sem_setor_nao_e_de_ninguem(client: TestClient, banco: _Fake) -> None:
    """
    Deliberado: o contrário — "sem setor, qualquer líder pode" — daria a todos
    os líderes alcance sobre quem acabou de ser cadastrado, que é exatamente
    quando ninguém decidiu ainda de quem aquela pessoa é.
    """
    assert _atribuir(client, LIDER_FISCAL, "u-solto").status_code == 403


def test_admin_alcanca_todo_mundo(client: TestClient, banco: _Fake) -> None:
    assert _atribuir(client, ADMIN, "u-contabil").status_code == 200
    assert _atribuir(client, ADMIN, "u-solto").status_code == 200


def test_lider_alcanca_a_si_mesmo(client: TestClient, banco: _Fake) -> None:
    """
    Sem isto, um líder que não pertence ao próprio setor não teria como liberar
    nada para si — e não haveria ninguém abaixo dele que pudesse fazê-lo,
    porque só líder libera. Não amplia poder: dentro do setor ele já pode
    atribuir qualquer cliente a qualquer pessoa.
    """
    assert _atribuir(client, LIDER_FISCAL, "u-lf").status_code == 200


# ──────────────────────────────────────────────────────────────────────────
# 2. Gestor sem liderança
# ──────────────────────────────────────────────────────────────────────────

def test_gestor_sem_setor_e_recusado_na_porta(client: TestClient, banco: _Fake) -> None:
    """
    Recusado ao ENTRAR, com uma mensagem que diz o que fazer. Deixá-lo abrir a
    tela e falhar em cada ação seria pior: o sintoma viraria "não consigo
    salvar nada", sem pista do motivo.
    """
    r = client.get("/api/carteira/operadores", headers=_h(*GESTOR_SEM_SETOR))
    assert r.status_code == 403
    assert "lidera" in r.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────────
# 3. Todas as portas, não só uma
# ──────────────────────────────────────────────────────────────────────────

def test_remover_tambem_respeita_o_alcance(client: TestClient, banco: _Fake) -> None:
    """
    Tirar acesso de alguém de outro setor é tão fora do alcance quanto dar.
    Uma barreira só no POST deixaria o líder do Fiscal sabotar o Contábil.
    """
    banco.tabelas["carteira"].append({"user_id": "u-contabil", "documento": DOC})
    r = client.delete(f"/api/carteira/u-contabil/{DOC}", headers=_h(*LIDER_FISCAL))
    assert r.status_code == 403
    assert banco.tabelas["carteira"], "removeu mesmo recusando"


def test_ver_a_carteira_alheia_tambem_e_recusado(
    client: TestClient, banco: _Fake
) -> None:
    """
    A carteira traz a trilha — quem liberou o quê e quando. É informação de
    dentro do setor.
    """
    assert client.get("/api/carteira/u-contabil",
                      headers=_h(*LIDER_FISCAL)).status_code == 403
    assert client.get("/api/carteira/u-fiscal",
                      headers=_h(*LIDER_FISCAL)).status_code == 200


# ──────────────────────────────────────────────────────────────────────────
# 4. Falha de leitura não vira recusa
# ──────────────────────────────────────────────────────────────────────────

def test_banco_fora_do_ar_devolve_503_e_nao_403(
    client: TestClient, banco: _Fake
) -> None:
    """
    "Não consegui verificar" não é "você não pode". Um 403 aqui faria o líder
    acreditar que perdeu a permissão e procurar o admin para resolver algo que
    é instabilidade do banco.

    Este cobre a PORTA (`require_admin_ou_lider`), que roda antes da rota.
    """
    banco.quebrado["departamento_lider"] = True
    r = _atribuir(client, LIDER_FISCAL, "u-fiscal")
    assert r.status_code == 503


def test_falha_ao_conferir_o_ALVO_tambem_da_503(
    client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    O de cima não cobria isto, e a mutação mostrou: quebrar
    `departamento_lider` faz a PORTA recusar com 503 antes de a rota rodar,
    então `_exigir_alcance` nunca era exercitado — trocar o `except` dele por
    `pass` deixava a suíte verde.

    Aqui a porta passa (o líder lidera algo) e só a conferência do alvo falha.
    """
    original = ci.pode_gerir

    def _falha(ator_id, ator_role, alvo_id):
        if (ator_role or "").strip().lower() == "admin":
            return original(ator_id, ator_role, alvo_id)
        raise ci.AlcanceIndisponivel("leitura do alvo falhou")

    monkeypatch.setattr(ci, "pode_gerir", _falha)
    r = _atribuir(client, LIDER_FISCAL, "u-fiscal")
    assert r.status_code == 503, "falha de leitura virou recusa de permissão"


# ──────────────────────────────────────────────────────────────────────────
# 5. Instalar segue a carteira, para todos menos admin
# ──────────────────────────────────────────────────────────────────────────

def test_gestor_perdeu_o_alcance_total_de_instalacao(banco: _Fake) -> None:
    """
    A contrapartida do recorte. A decisão de 15/08 dizia que limitar o gestor
    seria teatro, porque ele podia atribuir a si mesmo qualquer coisa. Com o
    recorte, o argumento inverte: se ele atribui só dentro do setor mas instala
    qualquer coisa, o recorte é que vira teatro.
    """
    assert ci.PAPEIS_COM_ALCANCE_TOTAL == ("admin",)
