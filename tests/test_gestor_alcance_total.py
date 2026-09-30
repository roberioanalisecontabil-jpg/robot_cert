"""
Carteira do GESTOR — decisão de produto de 30/09/2026 (segunda versão).

A primeira versão do dia dava ao gestor alcance total por uma flag
(`users.acesso_restrito`). Em uso, o usuário pediu outra coisa, mais
concreta: a carteira do gestor existe de verdade, como a de qualquer
operador, e a REGRA a preenche.

  * Ao virar gestor, a pessoa recebe TODOS os clientes do inventário na
    carteira, marcados como concedidos pela regra (`atribuido_por_email =
    "regra:gestor"`). A tela mostra tudo em "Na carteira", e o administrador
    tira clientes um a um se quiser.
  * O alcance de leitura e de instalação do gestor é o da carteira (própria +
    carteiras do setor que lidera), exatamente como o lote 4 definiu — só que
    a carteira começa cheia.
  * Ao deixar de ser gestor, saem os clientes concedidos pela regra; os
    atribuídos à mão ficam. Voltar a ser gestor aplica a regra de novo.
  * Operador comum: só o que foi atribuído à mão. Nada muda para ele.

A flag `acesso_restrito` deixou de ter efeito (a coluna pode ser removida
pela migration 20260930130000).

Escritos antes da correção; falhavam em 2f2ebd6.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.cert_installer as ci
from tests.test_seguranca_lote4 import (  # noqa: F401 — `banco` é fixture; o resto, helpers
    ADMIN, DOC_A, DOC_B, DOC_C, DOC_L, FISCAL_OP, GESTOR, _docs, _h, banco,
)
from tests.test_seguranca_lote1 import _Fake

RAIZ = Path(__file__).resolve().parents[1]
CERTS = "/api/certificados?fonte=remoto&todas_filtradas=true"
TODOS = {DOC_A, DOC_B, DOC_C, DOC_L}


def _carteira(banco: _Fake, uid: str) -> dict:
    """documento -> quem atribuiu, para a pessoa `uid`."""
    return {r["documento"]: r.get("atribuido_por_email") for r in banco.tabelas["carteira"] if r["user_id"] == uid}


def _corpo(u: dict, **extra) -> dict:
    return {"email": u["email"], "full_name": u["full_name"], "role": u["role"], **extra}


def _u(banco: _Fake, uid: str) -> dict:
    return next(u for u in banco.tabelas["users"] if u["id"] == uid)


# ── A regra enche a carteira ao virar gestor ──────────────────────────────

def test_virar_gestor_recebe_todos_os_clientes_na_carteira(client: TestClient, banco: _Fake) -> None:
    """u-fis é operador com DOC_A à mão. Promovido, recebe o resto pela regra."""
    fis = _u(banco, "u-fis")
    r = client.put("/api/users/u-fis", json=_corpo(fis, role="gestor"), headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    cart = _carteira(banco, "u-fis")
    assert set(cart) == TODOS
    assert cart[DOC_A] != ci.ORIGEM_REGRA_GESTOR, "o que já era manual continua manual"
    assert all(cart[d] == ci.ORIGEM_REGRA_GESTOR for d in (DOC_B, DOC_C, DOC_L))
    assert r.json().get("regra_gestor", {}).get("acrescentados") == 3


def test_gestor_le_e_instala_pela_carteira_que_a_regra_encheu(client: TestClient, banco: _Fake) -> None:
    fis = _u(banco, "u-fis")
    client.put("/api/users/u-fis", json=_corpo(fis, role="gestor"), headers=_h(*ADMIN))
    r = client.get(CERTS, headers=_h("fis@x.com", "gestor"))
    assert r.status_code == 200, r.text
    assert _docs(r.json()["itens"]) == TODOS, "a carteira cheia = vê tudo"


def test_admin_tira_um_cliente_e_o_gestor_deixa_de_ve_lo(client: TestClient, banco: _Fake) -> None:
    fis = _u(banco, "u-fis")
    client.put("/api/users/u-fis", json=_corpo(fis, role="gestor"), headers=_h(*ADMIN))
    r = client.delete(f"/api/carteira/u-fis/{DOC_B}", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert set(_carteira(banco, "u-fis")) == TODOS - {DOC_B}
    assert _docs(client.get(CERTS, headers=_h("fis@x.com", "gestor")).json()["itens"]) == TODOS - {DOC_B}


def test_deixar_de_ser_gestor_tira_so_o_que_a_regra_deu(client: TestClient, banco: _Fake) -> None:
    fis = _u(banco, "u-fis")
    client.put("/api/users/u-fis", json=_corpo(fis, role="gestor"), headers=_h(*ADMIN))
    assert set(_carteira(banco, "u-fis")) == TODOS
    r = client.put("/api/users/u-fis", json=_corpo(fis, role="user"), headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert set(_carteira(banco, "u-fis")) == {DOC_A}, "o manual fica; o da regra sai"
    assert r.json().get("regra_gestor", {}).get("removidos") == 3
    assert _docs(client.get(CERTS, headers=_h(*FISCAL_OP)).json()["itens"]) == {DOC_A}


def test_voltar_a_ser_gestor_aplica_a_regra_de_novo(client: TestClient, banco: _Fake) -> None:
    fis = _u(banco, "u-fis")
    client.put("/api/users/u-fis", json=_corpo(fis, role="gestor"), headers=_h(*ADMIN))
    client.delete(f"/api/carteira/u-fis/{DOC_B}", headers=_h(*ADMIN))
    client.put("/api/users/u-fis", json=_corpo(fis, role="user"), headers=_h(*ADMIN))
    client.put("/api/users/u-fis", json=_corpo(fis, role="gestor"), headers=_h(*ADMIN))
    assert set(_carteira(banco, "u-fis")) == TODOS, "inclusive o que o admin tinha tirado antes"


def test_editar_gestor_sem_trocar_papel_nao_reaplica_a_regra(client: TestClient, banco: _Fake) -> None:
    """Renomear um gestor não pode devolver o cliente que o admin tirou."""
    fis = _u(banco, "u-fis")
    client.put("/api/users/u-fis", json=_corpo(fis, role="gestor"), headers=_h(*ADMIN))
    client.delete(f"/api/carteira/u-fis/{DOC_B}", headers=_h(*ADMIN))
    r = client.put("/api/users/u-fis", json=_corpo(fis, role="gestor", full_name="Fis Renomeado"), headers=_h(*ADMIN))
    assert r.status_code == 200
    assert DOC_B not in _carteira(banco, "u-fis")


def test_cadastrar_ja_como_gestor_aplica_a_regra(client: TestClient, banco: _Fake) -> None:
    r = client.post("/api/users", json={"email": "novo.gestor@x.com", "password": "senha-forte-123456",
                                        "full_name": "Novo Gestor", "role": "gestor"}, headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    novo = next(u for u in banco.tabelas["users"] if u["email"] == "novo.gestor@x.com")
    assert set(_carteira(banco, novo["id"])) == TODOS


def test_aplicar_a_regra_a_todos_os_gestores_de_uma_vez(client: TestClient, banco: _Fake) -> None:
    """Para os gestores que já existiam no deploy (e para quem quiser
    completar a carteira quando entrarem clientes novos no inventário)."""
    assert set(_carteira(banco, "u-lf")) == {DOC_L}
    r = client.post("/api/carteira/regra-gestor/aplicar", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert set(_carteira(banco, "u-lf")) == TODOS
    assert r.json()["gestores"] == 1 and r.json()["acrescentados"] == 3
    # Idempotente.
    assert client.post("/api/carteira/regra-gestor/aplicar", headers=_h(*ADMIN)).json()["acrescentados"] == 0
    # E a regra é do administrador.
    assert client.post("/api/carteira/regra-gestor/aplicar", headers=_h(*GESTOR)).status_code == 403


def test_a_flag_antiga_nao_tem_mais_efeito(client: TestClient, banco: _Fake) -> None:
    """`acesso_restrito` da primeira versão do dia: ligada ou não, o gestor
    lê a carteira própria + setor. u-lf tem DOC_L à mão e lidera o setor de
    u-fis (DOC_A)."""
    lf = _u(banco, "u-lf")
    for valor in (True, False):
        lf["acesso_restrito"] = valor
        assert _docs(client.get(CERTS, headers=_h(*GESTOR)).json()["itens"]) == {DOC_A, DOC_L}
    assert not hasattr(ci, "gestor_com_acesso_restrito")


def test_operador_comum_nao_muda(client: TestClient, banco: _Fake) -> None:
    assert _docs(client.get(CERTS, headers=_h(*FISCAL_OP)).json()["itens"]) == {DOC_A}


# ── Tela de Carteiras e de Usuários ────────────────────────────────────────

from tests.test_carteiras_ui import _h as _h_cart  # noqa: E402
from tests.test_carteiras_ui import banco as banco_cart  # noqa: E402,F401


def test_lista_de_operadores_traz_gestores_como_quem_depende_de_carteira(client: TestClient, banco_cart) -> None:
    r = client.get("/api/carteira/operadores", headers=_h_cart("admin"))
    assert r.status_code == 200, r.text
    por_id = {o["id"]: o for o in r.json()["operadores"]}
    g = por_id["u-gest"]
    assert g["role"] == "gestor" and g["depende_de_carteira"] is True
    assert g["sem_carteira"] is True, "gestor sem nada na carteira é pendência: a regra ainda não foi aplicada"
    assert "acesso_restrito" not in g


def test_telas_sem_a_flag_e_com_a_lista_rolavel() -> None:
    usuarios = (RAIZ / "templates" / "usuarios.html").read_text(encoding="utf-8")
    assert 'id="ed-acesso-restrito"' not in usuarios and "acesso_restrito" not in usuarios
    carteiras = (RAIZ / "templates" / "carteiras.html").read_text(encoding="utf-8")
    assert "Vê tudo" not in carteiras
    assert 'class="cg-op-rolagem"' in carteiras, "a lista de operadores rola dentro do próprio painel"
    assert "regra-gestor/aplicar" in carteiras, "o admin aplica a regra pela tela"
    assert "regra de gestor" in carteiras.lower(), "a trilha nomeia a origem"
    css = (RAIZ / "static" / "aguia-carteiras.css").read_text(encoding="utf-8")
    bloco = css.split(".cg-op-rolagem {")[1].split("}")[0]
    assert "overflow-y: auto" in bloco and "max-height" in bloco
    assert "aguia-carteiras.css?v=aguia-2026-09d" in carteiras


def test_migration_que_descarta_a_flag_existe() -> None:
    sqls = list((RAIZ / "supabase" / "migrations").glob("*acesso_restrito_drop*.sql"))
    assert sqls and "DROP COLUMN IF EXISTS acesso_restrito" in sqls[0].read_text(encoding="utf-8")
