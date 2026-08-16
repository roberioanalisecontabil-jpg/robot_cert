"""
Trocar o e-mail de alguém leva as seleções de alerta junto.

`colaborador_cert_selecoes` tem `user_email` como chave primária e nada a liga
ao `id` da pessoa. Antes disto, `PUT /api/users/{id}` com outro endereço deixava
a linha para trás — e o estrago era mudo dos dois lados: as escolhas sumiam da
tela de Acompanhamento, e `_get_todos_colaboradores_selecoes` passava a
descartar a órfã por não achar o endereço em `users`, no mesmo caminho que
existe para não mandar e-mail a quem não deve.

Ninguém abre chamado por parar de receber e-mail. É o tipo de defeito que só
aparece quando um certificado vence sem aviso.
"""

from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from app import auth

SELECOES = "colaborador_cert_selecoes"


class _Res:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _Query:
    def __init__(self, linhas: List[Dict[str, Any]], banco: "_Fake", nome: str) -> None:
        self._l, self._b, self._n = linhas, banco, nome
        self._f: List = []
        self._op = "select"
        self._p: Any = None

    def select(self, *_c: str) -> "_Query":
        self._op = "select"
        return self

    def update(self, p: Dict[str, Any]) -> "_Query":
        self._op, self._p = "update", p
        return self

    def upsert(self, p: Dict[str, Any], **_k: Any) -> "_Query":
        self._op, self._p = "upsert", p
        return self

    def delete(self) -> "_Query":
        self._op = "delete"
        return self

    def eq(self, coluna: str, valor: Any) -> "_Query":
        self._f.append((coluna, valor))
        return self

    def limit(self, _n: int) -> "_Query":
        return self

    def _casa(self, r: Dict[str, Any]) -> bool:
        return all(r.get(c) == v for c, v in self._f)

    def execute(self) -> _Res:
        if self._n in self._b.quebrado:
            raise RuntimeError(f"tabela {self._n} fora do ar")
        if self._op == "select":
            return _Res([dict(r) for r in self._l if self._casa(r)])
        if self._op == "update":
            alt = []
            for r in self._l:
                if self._casa(r):
                    r.update(self._p)
                    alt.append(dict(r))
            return _Res(alt)
        if self._op == "upsert":
            chave = "user_email" if self._n == SELECOES else "id"
            for r in self._l:
                if r.get(chave) == self._p.get(chave):
                    r.update(self._p)
                    return _Res([dict(r)])
            self._l.append(dict(self._p))
            return _Res([dict(self._p)])
        if self._op == "delete":
            fora = [r for r in self._l if self._casa(r)]
            self._l[:] = [r for r in self._l if not self._casa(r)]
            return _Res(fora)
        raise AssertionError(self._op)


class _Fake:
    def __init__(self, tabelas: Dict[str, List[Dict[str, Any]]]) -> None:
        self.tabelas = tabelas
        self.quebrado: set = set()

    def table(self, nome: str) -> _Query:
        return _Query(self.tabelas.setdefault(nome, []), self, nome)


DOCS = ["33706943000193", "55993256000139"]


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake({
        "users": [
            # O admin que faz a operação. Precisa existir e estar ativo: desde
            # f1c4aeb o papel vem do banco, não do token.
            {"id": "u-adm", "email": "chefe@x.com", "full_name": "Chefe",
             "role": "admin", "ativo": True, "gestor_id": None},
            {"id": "u-ana", "email": "ana@x.com", "full_name": "Ana",
             "role": "user", "ativo": True, "gestor_id": None},
        ],
        SELECOES: [
            {"user_email": "ana@x.com", "documentos": list(DOCS),
             "updated_at": "2026-08-01T10:00:00Z"},
        ],
    })
    monkeypatch.setattr("app.settings_state._supabase", lambda: fake)
    return fake


def _h() -> dict:
    return {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": "chefe@x.com", "role": "admin"})}


def _put(client: TestClient, **campos: Any):
    corpo = {"email": "ana@x.com", "full_name": "Ana", "role": "user"}
    corpo.update(campos)
    return client.put("/api/users/u-ana", json=corpo, headers=_h())


def _selecoes(banco: _Fake) -> Dict[str, List[str]]:
    return {r["user_email"]: r["documentos"] for r in banco.tabelas[SELECOES]}


# ──────────────────────────────────────────────────────────────────────────
# 1. O caso que quebrava
# ──────────────────────────────────────────────────────────────────────────

def test_trocar_o_email_leva_as_selecoes(client: TestClient, banco: _Fake) -> None:
    r = _put(client, email="ana.souza@x.com")
    assert r.status_code == 200, r.text

    sel = _selecoes(banco)
    assert sel.get("ana.souza@x.com") == DOCS, "as seleções não acompanharam"
    assert "ana@x.com" not in sel, "a linha antiga ficou para trás"


def test_nao_fica_linha_duplicada(client: TestClient, banco: _Fake) -> None:
    """
    Duas linhas com os mesmos documentos fariam a pessoa receber o alerta em
    duplicidade no dia em que o endereço antigo voltasse a casar com alguma
    conta — reaproveitar e-mail de quem saiu da empresa não é hipótese remota.
    """
    _put(client, email="ana.souza@x.com")
    assert len(banco.tabelas[SELECOES]) == 1
    # Sem esta segunda asserção o teste passaria também com o código antigo,
    # que não movia nada e portanto também deixava exatamente uma linha.
    assert banco.tabelas[SELECOES][0]["user_email"] == "ana.souza@x.com"


# ──────────────────────────────────────────────────────────────────────────
# 2. Não mexer no que não pediram
# ──────────────────────────────────────────────────────────────────────────

def test_sem_troca_de_email_nada_se_move(client: TestClient, banco: _Fake) -> None:
    """Editar só o nome não pode tocar nas seleções."""
    antes = _selecoes(banco)
    r = _put(client, full_name="Ana Souza")
    assert r.status_code == 200
    assert _selecoes(banco) == antes


def test_quem_nao_tem_selecao_nao_ganha_linha(client: TestClient, banco: _Fake) -> None:
    """
    Trocar o e-mail de quem nunca escolheu documento nenhum não pode criar uma
    linha vazia — ela viraria órfã no dia seguinte e poluiria o log de
    descartadas do job de alertas.
    """
    banco.tabelas[SELECOES].clear()
    r = _put(client, email="ana.souza@x.com")
    assert r.status_code == 200
    assert banco.tabelas[SELECOES] == []


# ──────────────────────────────────────────────────────────────────────────
# 3. Best-effort: falhar em mover não desfaz o que já foi gravado
# ──────────────────────────────────────────────────────────────────────────

def test_falha_ao_mover_nao_derruba_a_edicao(
    client: TestClient, banco: _Fake, caplog: pytest.LogCaptureFixture
) -> None:
    """
    A troca de e-mail já foi gravada em `users` quando chegamos aqui. Responder
    erro diria ao admin que a operação falhou quando ela funcionou, e a reação
    natural — tentar de novo — não teria efeito nenhum.

    Mas o aviso tem de sair nominal: o defeito que este arquivo fecha é o
    silêncio, não a falha.
    """
    banco.quebrado.add(SELECOES)

    with caplog.at_level("WARNING"):
        r = _put(client, email="ana.souza@x.com")

    assert r.status_code == 200
    assert banco.tabelas["users"][1]["email"] == "ana.souza@x.com"
    assert "ana.souza@x.com" in caplog.text and "ana@x.com" in caplog.text


def test_email_e_normalizado_antes_de_comparar(client: TestClient, banco: _Fake) -> None:
    """
    `_validar_email` grava em minúsculas. Comparar com o valor cru do corpo
    veria "ANA@X.COM" como endereço novo e moveria a linha para um e-mail que
    não existe em `users` — órfã na hora, e a pessoa deixaria de receber.
    """
    r = _put(client, email="ANA@X.COM")
    assert r.status_code == 200
    assert _selecoes(banco) == {"ana@x.com": DOCS}
