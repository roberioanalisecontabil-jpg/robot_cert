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
