"""
Trocar o e-mail de alguém não mexe na seleção de alertas — nem precisa mexer.

Este arquivo substitui `test_selecoes_seguem_o_email.py`, que garantia o
contrário: que `update_user` **carregasse** a linha para o endereço novo. Aquilo
era o remendo de 16/08, e consertava o chamador — um UPDATE direto no banco,
uma rota nova ou uma importação voltavam a desprender a seleção.

Depois do rechaveamento a linha é chaveada por `user_id`, então não há o que
carregar. A garantia aqui é mais forte, e a diferença importa: antes o
comportamento certo dependia de *lembrar de chamar* um helper; agora ele é
consequência do modelo, e vale para qualquer caminho de escrita.

O teste que fecha o arquivo é o do destinatário: prova que o alerta passa a ir
para o endereço NOVO sem ninguém ter tocado na tabela de seleções.
"""

from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

import app.alert_state as als
import app.settings_state as st
from app import auth

DOCS = ["27049257000194", "37894958000183"]
SELECOES = "colaborador_cert_selecoes"


class _Res:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _Query:
    def __init__(self, linhas: List[Dict[str, Any]]) -> None:
        self._l, self._f = linhas, []
        self._op, self._p = "select", None

    def select(self, *_c: str) -> "_Query":
        return self

    def update(self, p: Dict[str, Any]) -> "_Query":
        self._op, self._p = "update", p
        return self

    def eq(self, coluna: str, valor: Any) -> "_Query":
        self._f.append((coluna, valor))
        return self

    def limit(self, _n: int) -> "_Query":
        return self

    def _casa(self, r: Dict[str, Any]) -> bool:
        return all(r.get(c) == v for c, v in self._f)

    def execute(self) -> _Res:
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
            {"id": "u-adm", "email": "chefe@x.com", "full_name": "Chefe",
             "role": "admin", "ativo": True, "gestor_id": None},
            {"id": "u-ana", "email": "ana@x.com", "full_name": "Ana",
             "role": "user", "ativo": True, "gestor_id": None},
        ],
        # Sem `user_email`: é o estado depois da fase 3c.
        SELECOES: [{"user_id": "u-ana", "documentos": list(DOCS),
                    "updated_at": "2026-08-01T10:00:00Z"}],
        "user_activity": [],
    })
    monkeypatch.setattr("app.settings_state._supabase", lambda: fake)
    monkeypatch.setattr(als, "_supabase", lambda: fake)
    return fake


def _h() -> dict:
    return {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": "chefe@x.com", "role": "admin"})}


def _trocar_email(client: TestClient, novo: str):
    return client.put(
        "/api/users/u-ana",
        json={"email": novo, "full_name": "Ana", "role": "user"},
        headers=_h(),
    )


# ──────────────────────────────────────────────────────────────────────────

def test_a_linha_de_selecao_nao_e_tocada(client: TestClient, banco: _Fake) -> None:
    """
    Contraprova do modelo: o `updated_at` intacto mostra que ninguém reescreveu
    a linha. Se alguém reintroduzir um helper que "carrega" a seleção, este
    teste acusa — e o helper seria trabalho inútil, além de mais uma coisa a
    lembrar de chamar.
    """
    antes = [dict(r) for r in banco.tabelas[SELECOES]]
    assert _trocar_email(client, "ana.souza@x.com").status_code == 200
    assert banco.tabelas[SELECOES] == antes


def test_a_selecao_continua_sendo_encontrada(client: TestClient, banco: _Fake) -> None:
    """O que a pessoa vê ao abrir Acompanhamento depois da troca."""
    _trocar_email(client, "ana.souza@x.com")
    assert st.load_colaborador_selecao("ana.souza@x.com", "u-ana") == DOCS


def test_o_alerta_passa_a_ir_para_o_endereco_novo(
    client: TestClient, banco: _Fake
) -> None:
    """
    O teste que fecha o assunto.

    Antes do rechaveamento, este era o defeito mudo: a linha ficava com o
    endereço antigo, `_get_todos_colaboradores_selecoes` não o achava em
    `users` e descartava a seleção — no caminho que existe justamente para não
    mandar e-mail a quem não deve. Sem erro e sem aviso; a pessoa só parava de
    ser avisada de certificado vencendo.

    Agora o destino sai da conta, então acompanha a troca sem que nada na
    tabela de seleções tenha sido escrito.
    """
    assert als._get_todos_colaboradores_selecoes() == {"ana@x.com": DOCS}

    _trocar_email(client, "ana.souza@x.com")

    assert als._get_todos_colaboradores_selecoes() == {"ana.souza@x.com": DOCS}


def test_desativar_continua_cortando_o_alerta(client: TestClient, banco: _Fake) -> None:
    """
    Identidade estável não pode virar acesso perpétuo: ela resolve QUEM é a
    pessoa, não SE ela deve receber.
    """
    client.put(
        "/api/users/u-ana",
        json={"email": "ana@x.com", "full_name": "Ana", "role": "user", "ativo": False},
        headers=_h(),
    )
    assert als._get_todos_colaboradores_selecoes() == {}
