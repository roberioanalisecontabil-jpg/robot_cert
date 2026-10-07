"""
Revisão da página Usuários (01/10/2026) — decisões U1 a U6 e defeitos.

Registro em docs/revisao-paginas-2026-10.md. Em resumo:

  U1  Usuários é só do Administrador; a matriz não governa o módulo.
  U2  O campo "Gestor responsável" (`gestor_id`) saiu da tela e do servidor.
  U3  Desativar tira as lideranças: o gestor volta a Operador pela regra, e
      reativar devolve a conta como Operador.
  U4  Não existe apagar usuário; desativar é o caminho.
  U5  Linhas ignoradas na importação por CSV vêm listadas, com o motivo.
  U6  A contagem de pessoas de um departamento é só de ativos.

Escritos antes da implementação; falhavam em 4dda2f8.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_seguranca_lote1 import _Fake, _usuario
from tests.test_seguranca_lote4 import ADMIN, FISCAL, GESTOR, _h  # noqa: F401
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture
def banco(banco_base: _Fake) -> _Fake:
    banco_base.tabelas["departamento"] = [{"id": FISCAL, "nome": "Fiscal"}]
    banco_base.tabelas["users"].append(_usuario("u-inativo", "inativo@x.com", "user", departamento_id=FISCAL, ativo=False))
    banco_base.tabelas["carteira_excecao"] = []
    return banco_base


def _u(banco: _Fake, uid: str) -> dict:
    return next(u for u in banco.tabelas["users"] if u["id"] == uid)


def _csv(texto: str) -> dict:
    return {"file": ("usuarios.csv", io.BytesIO(texto.encode("utf-8")), "text/csv")}


# ── U2: gestor_id não existe mais para a tela ─────────────────────────────

def test_lista_e_edicao_nao_falam_mais_de_gestor_responsavel(client: TestClient, banco: _Fake) -> None:
    r = client.get("/api/users", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert all("gestor_id" not in u for u in r.json())
    fis = _u(banco, "u-fis")
    r = client.put("/api/users/u-fis", json={"email": fis["email"], "full_name": fis["full_name"],
                                             "role": "user", "gestor_id": "u-lf"}, headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert _u(banco, "u-fis").get("gestor_id") is None, "campo desconhecido é ignorado, não gravado"
    ops = client.get("/api/carteira/operadores", headers=_h(*ADMIN)).json()["operadores"]
    assert all("gestor_id" not in o for o in ops)


# ── U3: desativar um gestor tira as lideranças ────────────────────────────

def test_desativar_gestor_tira_a_lideranca_e_rebaixa(client: TestClient, banco: _Fake) -> None:
    r = client.post("/api/users/u-lf/deactivate", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert not any(l["user_id"] == "u-lf" for l in banco.tabelas["departamento_lider"])
    assert _u(banco, "u-lf")["role"] == "user" and _u(banco, "u-lf")["ativo"] is False
    assert r.json()["papel"]["de"] == "gestor" and r.json()["papel"]["para"] == "user"
    # O departamento fica sem gestor, e a lista diz isso.
    deps = client.get("/api/departamentos", headers=_h(*ADMIN)).json()
    assert deps[0]["lideres"] == []
    # Reativar volta como operador, com a carteira vazia.
    assert client.post("/api/users/u-lf/reactivate", headers=_h(*ADMIN)).status_code == 200
    assert _u(banco, "u-lf")["role"] == "user" and _u(banco, "u-lf")["ativo"] is True


def test_desativar_operador_nao_mexe_em_papel(client: TestClient, banco: _Fake) -> None:
    r = client.post("/api/users/u-fis/deactivate", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert _u(banco, "u-fis")["role"] == "user"
    assert r.json()["papel"] == {} and r.json()["atribuicoes"] == 1


# ── U4: não há apagar ─────────────────────────────────────────────────────

def test_nao_existe_apagar_usuario(client: TestClient, banco: _Fake) -> None:
    assert client.delete("/api/users/u-fis", headers=_h(*ADMIN)).status_code in (404, 405)
    assert any(u["id"] == "u-fis" for u in banco.tabelas["users"])


# ── U5: ignoradas com motivo ──────────────────────────────────────────────

def test_importacao_lista_as_ignoradas_com_motivo(client: TestClient, banco: _Fake) -> None:
    csv = ("nome;email;senha;nivel;departamento\n"
           "Nova;nova@x.com;senha-forte-123456;user;Fiscal\n"
           "Repetida;fis@x.com;senha-forte-123456;user;Fiscal\n"
           ";semnome@x.com;senha-forte-123456;user;Fiscal\n")
    r = client.post("/api/users/import", headers=_h(*ADMIN), files=_csv(csv))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["criados"] == 1 and d["ignorados"] == 2 and d["erros"] == []
    motivos = {i["linha"]: i["motivo"] for i in d["ignoradas"]}
    assert "Já existe" in motivos[3]
    assert "Campo vazio: nome" in motivos[4]


# ── U6: pessoas do departamento = ativos ──────────────────────────────────

def test_departamento_conta_so_ativos_e_informa_inativos(client: TestClient, banco: _Fake) -> None:
    r = client.get("/api/departamentos", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    fiscal = next(d for d in r.json() if d["id"] == FISCAL)
    # u-lf (gestor) e u-fis estão no Fiscal e ativos; u-inativo está inativo.
    assert fiscal["membros"] == 2 and fiscal["inativos"] == 1


# ── Vocabulário e estados da tela ─────────────────────────────────────────

def test_mensagens_do_servidor_sem_setor_nem_lider(client: TestClient, banco: _Fake) -> None:
    r = client.put(f"/api/departamentos/{FISCAL}/lideres", json={"lideres": ["u-fantasma"]}, headers=_h(*ADMIN))
    assert r.status_code == 422 and "gestores" in r.json()["detail"]
    r = client.post("/api/users/import", headers=_h(*ADMIN), files=_csv("nome;email;senha;nivel\nA;a@x.com;x;user\n"))
    assert r.status_code == 422 and "setor" not in r.json()["detail"]


def test_tela_de_usuarios_revisada() -> None:
    html = (RAIZ / "templates" / "usuarios.html").read_text(encoding="utf-8")
    assert "remova" not in html, "não há remover usuário"
    assert "gestor_id" not in html and "Gestor responsável" not in html
    assert "setor" not in html.lower().replace("insetor", ""), "vocabulário: departamento"
    assert "A sessão aberta dela não cai" not in html
    assert "erroNaTabela(" in html, "erro de carregamento precisa aparecer na tabela"
    assert "avisarPapeis(" in html, "quem mudou de papel é anunciado"
    assert "só o administrador" in html, "Níveis de acesso explica por que Usuários está travado"
    assert "ignoradas" in html, "linhas ignoradas entram na lista"


# ── Leva C (06/10/2026): Departamentos e Níveis de acesso no Águia ─────────

def test_gestores_do_departamento_vem_com_nome_de_exibicao(client: TestClient, banco: _Fake) -> None:
    deps = client.get("/api/departamentos", headers=_h(*ADMIN)).json()
    lideres = [l for d in deps for l in d["lideres"]]
    assert lideres, "a base de teste tem departamento com gestor"
    for l in lideres:
        assert l["nome_exibicao"] == (l["nome"] or "").strip().upper()


def test_abas_departamentos_e_niveis_sem_classes_legadas() -> None:
    html = (RAIZ / "templates" / "usuarios.html").read_text(encoding="utf-8")
    assert "item 87" not in html
    assert "btn-action" not in html and "row-actions" not in html and "form-control" not in html
    assert "cg-tabela-dep" in html and "cg-tabela-perm" in html and "cg-perm-nota" in html
    assert "'🏢'" not in html
