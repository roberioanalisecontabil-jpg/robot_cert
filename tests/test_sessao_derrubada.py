"""
Auditoria de 10/10/2026: trocar a senha, mudar o e-mail de dono e rebaixar o
papel têm de derrubar o que foi emitido antes. A regra de antes era só o
`senha_alterada_em` com 5 s de margem (o token emitido nesses 5 s sobrevivia
8 h), a sessão seguia o e-mail para a conta nova, e o token de instalação
pedido com o alcance antigo continuava resgatável.
"""

from typing import Dict

import pytest
from fastapi.testclient import TestClient

from app import auth, papeis
from tests.test_ajustes_ui_30_09 import _admin, banco_usuarios  # noqa: F401
from tests.test_recuperacao_de_senha import EMAIL, TABELA, _Fake, banco  # noqa: F401


def _h(email: str = EMAIL, sv: int = 0) -> Dict[str, str]:
    return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": "user", "sv": sv})}


def _vale(client: TestClient, h: Dict[str, str]) -> bool:
    return client.get("/api/users/me/app-autenticador", headers=h).status_code == 200


def test_token_emitido_logo_antes_da_troca_morre(client: TestClient, banco: _Fake) -> None:  # noqa: F811
    h = _h()
    assert _vale(client, h)
    r = client.post("/api/senha/trocar", headers=h, json={"senha_atual": "antiga-123", "nova_senha": "nova-senha-forte-1"})
    assert r.status_code == 200, r.text
    assert not _vale(client, h), "emitido 0 s antes da troca, dentro da margem de 5 s"


def test_redefinir_por_codigo_derruba_as_sessoes(client: TestClient, banco: _Fake) -> None:  # noqa: F811
    h = _h()
    client.post("/api/senha/codigo", json={"email": EMAIL})
    codigo = banco.enviados[-1]["codigo"]
    r = client.post("/api/senha/redefinir", json={"email": EMAIL, "codigo": codigo, "password": "nova-senha-forte-1"})
    assert r.status_code == 200, r.text
    assert not _vale(client, h)


def test_sessao_nao_segue_o_email_para_outra_conta(client: TestClient, banco_usuarios) -> None:
    """O admin passa o e-mail de A para B (cadastros trocados): o token de A
    não pode virar sessão de B — com o papel de B."""
    h_da_ana = _h("ana@x.com")
    assert _vale(client, h_da_ana)
    contas = {u["id"]: u for u in banco_usuarios.tabelas["users"]}
    r = client.put("/api/users/u-ana", json={"email": "ana.antiga@x.com", "full_name": "Ana", "role": "user"},
                   headers=_admin())
    assert r.status_code == 200, r.text
    r = client.put("/api/users/u-adm", json={"email": "ana@x.com", "full_name": "Adm", "role": "admin"},
                   headers=_admin())
    assert r.status_code == 200, r.text
    assert contas["u-adm"]["email"] == "ana@x.com"
    assert not _vale(client, h_da_ana), "o token da Ana entrou como a conta do administrador"


def test_troca_de_papel_queima_token_de_instalacao(banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    banco.tabelas["install_token"] = [{"id": "t1", "user_id": "u-ana", "consumed_at": None},
                                      {"id": "t2", "user_id": "u-outro", "consumed_at": None}]
    papeis.apos_troca_de_papel(banco, "u-ana")
    t1, t2 = banco.tabelas["install_token"]
    assert t1["consumed_at"] and t2["consumed_at"] is None
    assert banco.tabelas["users"][0]["sessao_versao"] == 1


def test_reativar_nao_ressuscita_o_token_de_antes_da_desativacao(client: TestClient, banco_usuarios) -> None:
    """Auditoria run-2 (12/10/2026): desativar só mexia no `ativo`, reversível.
    Reativar devolvia a vida a todo token ainda no prazo — inclusive o de quem
    motivou a desativação."""
    h_da_ana = _h("ana@x.com")
    assert _vale(client, h_da_ana)
    assert client.post("/api/users/u-ana/deactivate", headers=_admin()).status_code == 200
    assert not _vale(client, h_da_ana)
    assert client.post("/api/users/u-ana/reactivate", headers=_admin()).status_code == 200
    assert not _vale(client, h_da_ana), "o token de antes da desativação voltou a valer"


def test_contadores_iguais_nao_levam_o_token_para_a_conta_que_recebeu_o_email(
    client: TestClient, banco_usuarios
) -> None:
    """Auditoria run-2, item 7: `sv` é contador por conta. A Ana (sv 1) perde o
    e-mail; a Carla (sv 0) o recebe e sobe para 1. Sem o id da conta no token,
    o token da Ana passava a ser sessão da Carla, com o papel dela."""
    from tests.test_seguranca_lote1 import _usuario

    contas = {u["id"]: u for u in banco_usuarios.tabelas["users"]}
    contas["u-ana"]["sessao_versao"] = 1
    contas["u-adm"]["sessao_versao"] = 0
    banco_usuarios.tabelas["users"].append(_usuario("u-carla", "carla@x.com", "admin", sessao_versao=0))
    h_da_ana = {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": "ana@x.com", "role": "user", "sv": 1, "uid": "u-ana"})}
    assert _vale(client, h_da_ana)
    r = client.put("/api/users/u-ana", json={"email": "ana.antiga@x.com", "full_name": "Ana", "role": "user"},
                   headers=_admin())
    assert r.status_code == 200, r.text
    r = client.put("/api/users/u-carla", json={"email": "ana@x.com", "full_name": "Carla", "role": "admin"},
                   headers=_admin())
    assert r.status_code == 200, r.text
    carla = next(u for u in banco_usuarios.tabelas["users"] if u["id"] == "u-carla")
    assert carla["sessao_versao"] == 1, "o cenário precisa dos contadores iguais"
    assert not _vale(client, h_da_ana), "o token da Ana entrou como a Carla"


def test_login_grava_o_id_da_conta_no_token() -> None:
    from app.rotas import usuarios
    import inspect

    assert '"uid": str(user.get("id")' in inspect.getsource(usuarios._abrir_sessao)
    dados = auth.decode_access_token(auth.create_access_token({"sub": "a@x.com", "role": "user", "uid": "u-1"}))
    assert dados is not None and dados.conta_id == "u-1"
