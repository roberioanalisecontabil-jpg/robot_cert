"""Rotas da conferência da estação e do relatório da remoção (Frente B, Task 5).

A bandeja manda o que tem no `CurrentUser\\My`; o portal responde o que sai
(`remover`), o que vai sair (`avisos`) e as liberações que vencem logo.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import computadores, remocao
from tests.test_computadores_rotas import PC_FIS, PC_SOL, _bandeja, _chave, _entrar
from tests.test_computadores_rotas import banco  # noqa: F401
from tests.test_seguranca_lote1 import _Fake
from tests.test_seguranca_lote4 import ADMIN, DOC_A, DOC_B, DOC_C, FISCAL_OP, _h
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401

FA, FB = "a" * 64, "b" * 64  # ALFA (DOC_A, na carteira do fis) e BETA (DOC_B, fora dela)


@pytest.fixture
def ligado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(remocao, "modo_carteira", lambda: "ligado")
    monkeypatch.setattr(remocao, "modo_sem_login", lambda: "ligado")


def _corpo(**extra) -> dict:
    return {"usuario_windows": " Fis ", "certificados": [FA, FB], **extra}


def _sem_conta(client: TestClient, maquina: str, **extra):
    return client.post("/api/estacao/conferencia/sem-conta",
                       json=_corpo(machine_id=maquina, **extra))


def _fixar(banco: _Fake, maquina: str) -> None:
    banco.tabelas[computadores.TABELA_CHAVE] = [
        {"machine_id": maquina, "chave_hash": computadores.hash_da_chave(_chave(maquina))}]


def test_logado_recebe_remover_no_modo_ligado(client: TestClient, banco: _Fake, ligado: None) -> None:
    seg = _entrar(client, "fis@x.com", PC_FIS)["segredo"]
    banco.tabelas["carteira"].append({"user_id": "u-fis", "documento": DOC_C, "origem": "manual",
                                      "valido_ate": (date.today() + timedelta(days=2)).isoformat()})
    r = client.post("/api/estacao/conferencia", headers=_bandeja(seg), json=_corpo())
    assert r.status_code == 200, r.text
    j = r.json()
    assert [(i["fingerprint"], i["nome"]) for i in j["remover"]] == [(FB, "BETA")]
    assert j["avisos"] == [] and j["proxima_em"] == 300
    assert [(v["documento"], v["nome"]) for v in j["vencendo"]] == [(DOC_C, DOC_C)]
    linha = banco.tabelas["remocao_estacao"][0]
    assert (linha["usuario_windows"], linha["user_id"], linha["estado"]) == ("fis", "u-fis", "remover")

    # Rodada seguinte: a bandeja conta que removeu; outra grafia do mesmo usuário é a mesma linha.
    r = client.post("/api/estacao/conferencia", headers=_bandeja(seg),
                    json={"usuario_windows": "FIS", "certificados": [FA],
                          "resultados": [{"fingerprint": FB, "ok": True}]})
    assert r.status_code == 200, r.text
    assert [(l["usuario_windows"], l["estado"]) for l in banco.tabelas["remocao_estacao"]] == [("fis", "removido")]


def test_logado_relatorio_devolve_vazio(client: TestClient, banco: _Fake, monkeypatch) -> None:
    monkeypatch.setattr(remocao, "modo_carteira", lambda: "relatorio")
    seg = _entrar(client, "fis@x.com", PC_FIS)["segredo"]
    r = client.post("/api/estacao/conferencia", headers=_bandeja(seg), json=_corpo())
    assert r.status_code == 200, r.text
    assert r.json() == {"remover": [], "avisos": [], "vencendo": [], "proxima_em": 300}
    assert [l["estado"] for l in banco.tabelas["remocao_estacao"]] == ["removeria"]


def test_desligado_nem_le_o_acervo(client: TestClient, banco: _Fake, monkeypatch) -> None:
    monkeypatch.setattr(remocao, "modo_sem_login", lambda: "desligado")
    banco.quebrado["cert_pfx_store"] = True
    r = _sem_conta(client, PC_SOL)
    assert r.status_code == 200, r.text
    assert r.json() == {"remover": [], "avisos": [], "proxima_em": 300}


def test_logado_sem_credencial_401(client: TestClient, banco: _Fake) -> None:
    assert client.post("/api/estacao/conferencia", json=_corpo()).status_code == 401


def test_sem_conta_chave_errada_403(client: TestClient, banco: _Fake, ligado: None) -> None:
    _fixar(banco, PC_SOL)
    for chave in (None, _chave(PC_FIS)):
        extra = {"chave": chave} if chave else {}
        r = _sem_conta(client, PC_SOL, **extra)
        assert r.status_code == 403 and r.json()["detail"] == "Chave da máquina não confere."
    assert banco.tabelas.get("remocao_estacao", []) == []
    r = _sem_conta(client, PC_SOL, chave=_chave(PC_SOL))
    assert r.status_code == 200, r.text


def test_sem_conta_maquina_sem_chave_aceita(client: TestClient, banco: _Fake, ligado: None) -> None:
    r = _sem_conta(client, PC_SOL)
    assert r.status_code == 200, r.text
    j = r.json()
    assert "vencendo" not in j and j["remover"] == []
    # Perfil sem login: tudo do acervo entra no aviso de 7 dias, com o nome do titular.
    assert sorted((i["fingerprint"], i["nome"], i["dias"]) for i in j["avisos"]) == [(FA, "ALFA", 7), (FB, "BETA", 7)]
    assert {l["user_id"] for l in banco.tabelas["remocao_estacao"]} == {None}


def test_segredo_revogado_de_outra_maquina_403(client: TestClient, banco: _Fake, ligado: None) -> None:
    seg = _entrar(client, "fis@x.com", PC_FIS)["segredo"]
    assert client.post("/api/estacao/sair", headers=_bandeja(seg)).status_code == 200
    r = _sem_conta(client, PC_SOL, segredo=seg)
    assert r.status_code == 403, r.text
    r = _sem_conta(client, PC_SOL, segredo="segredo-que-nao-existe")
    assert r.status_code == 403, r.text
    assert banco.tabelas.get("remocao_estacao", []) == []


def test_segredo_revogado_so_remove_nao_instala(client: TestClient, banco: _Fake, ligado: None) -> None:
    seg = _entrar(client, "fis@x.com", PC_FIS)["segredo"]
    assert client.post("/api/estacao/sair", headers=_bandeja(seg)).status_code == 200
    assert client.get("/api/estacao/instalacoes", headers=_bandeja(seg)).status_code == 401
    assert client.post("/api/estacao/conferencia", headers=_bandeja(seg), json=_corpo()).status_code == 401
    # Na rota sem conta, o último dono decide: vale a carteira dele.
    r = _sem_conta(client, PC_FIS, segredo=seg, chave=_chave(PC_FIS))
    assert r.status_code == 200, r.text
    assert [i["fingerprint"] for i in r.json()["remover"]] == [FB]
    assert {l["user_id"] for l in banco.tabelas["remocao_estacao"]} == {"u-fis"}


def test_segredo_de_dono_desativado_remove_tudo(client: TestClient, banco: _Fake, ligado: None) -> None:
    seg = _entrar(client, "fis@x.com", PC_FIS)["segredo"]
    next(u for u in banco.tabelas["users"] if u["id"] == "u-fis")["ativo"] = False
    r = _sem_conta(client, PC_FIS, segredo=seg, chave=_chave(PC_FIS))
    assert r.status_code == 200, r.text
    assert sorted(i["fingerprint"] for i in r.json()["remover"]) == [FA, FB]


def test_banco_fora_503_e_nada_gravado(client: TestClient, banco: _Fake, ligado: None) -> None:
    seg = _entrar(client, "fis@x.com", PC_FIS)["segredo"]
    banco.tabelas["remocao_estacao"] = [{"machine_id": PC_FIS, "usuario_windows": "fis", "fingerprint": FB,
                                         "estado": "aviso", "aviso_desde": "2026-11-10T00:00:00+00:00"}]
    antes = [dict(l) for l in banco.tabelas["remocao_estacao"]]
    banco.quebrado["cert_pfx_store"] = True
    r = client.post("/api/estacao/conferencia", headers=_bandeja(seg), json=_corpo())
    assert r.status_code == 503 and r.json()["detail"] == "Não foi possível conferir agora."
    assert _sem_conta(client, PC_SOL).status_code == 503
    assert banco.tabelas["remocao_estacao"] == antes
    assert not [g for g in banco.gravados if g[0] == "remocao_estacao"]


def test_fingerprint_malformado_422(client: TestClient, banco: _Fake) -> None:
    for certs in (["A" * 64], ["a" * 63], ["z" * 64]):
        r = client.post("/api/estacao/conferencia/sem-conta",
                        json={"usuario_windows": "x", "certificados": certs, "machine_id": PC_SOL})
        assert r.status_code == 422, certs
    r = _sem_conta(client, PC_SOL, resultados=[{"fingerprint": "xyz", "ok": True}])
    assert r.status_code == 422
    r = _sem_conta(client, PC_SOL, certificados=[FA] * 501)
    assert r.status_code == 422
    r = client.post("/api/estacao/conferencia/sem-conta",
                    json={"usuario_windows": "   ", "certificados": [FA], "machine_id": PC_SOL})
    assert r.status_code == 422


def test_relatorio_so_admin(client: TestClient, banco: _Fake) -> None:
    banco.tabelas["remocao_estacao"] = [
        {"machine_id": PC_FIS, "usuario_windows": "fis", "user_id": "u-fis", "fingerprint": FB,
         "documento": DOC_B, "estado": "removeria", "atualizado_em": "2026-11-14T10:00:00+00:00"},
        {"machine_id": PC_SOL, "usuario_windows": "x", "user_id": None, "fingerprint": FA,
         "documento": DOC_A, "estado": "aviso", "atualizado_em": "2026-11-14T11:00:00+00:00"},
    ]
    assert client.get("/api/remocao", headers=_h(*FISCAL_OP)).status_code == 403
    assert client.get("/api/remocao").status_code in (401, 403)
    r = client.get("/api/remocao", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    itens = r.json()["itens"]
    assert [(i["fingerprint"], i["titular"], i["pessoa"]) for i in itens] == [(FA, "ALFA", ""), (FB, "BETA", "FIS")]
    r = client.get("/api/remocao?estado=removeria", headers=_h(*ADMIN))
    assert [i["fingerprint"] for i in r.json()["itens"]] == [FB]
    assert client.get("/api/remocao?estado=xyz", headers=_h(*ADMIN)).status_code == 422
    assert client.get("/api/remocao?pagina=0", headers=_h(*ADMIN)).status_code == 422
    assert client.get("/api/remocao?pagina=2", headers=_h(*ADMIN)).json()["itens"] == []
