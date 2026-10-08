"""
Rotas do vínculo pessoa–computador (ADR 0002, 07/10/2026), ponta a ponta:
bandeja entra → pedido → administrador autoriza → Início vê o computador →
Instalar enfileira neste portal → bandeja busca → resgate conferido.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import auth, cert_installer as ci
from tests.test_seguranca_lote1 import _Fake
from tests.test_seguranca_lote4 import ADMIN, FISCAL_OP, _h  # noqa: F401
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401

SENHA = "senha-boa-123"
PC_FIS, PC_SOL = "aa:aa:aa:aa:aa:01", "aa:aa:aa:aa:aa:02"


@pytest.fixture
def banco(banco_base: _Fake, monkeypatch: pytest.MonkeyPatch) -> _Fake:
    for u in banco_base.tabelas["users"]:
        u["password_hash"] = auth.get_password_hash(SENHA)
        u["deve_trocar_senha"] = False
    for t in ("computador_vinculo", "fila_instalacao", "agent_devices", "carteira_excecao", "install_tokens"):
        banco_base.tabelas[t] = []
    # Ponte com o Hardlyze desligada: só o caminho novo.
    monkeypatch.setattr("app.config.INVENT_API_URL", "", raising=False)
    return banco_base


@pytest.fixture
def tokens(monkeypatch: pytest.MonkeyPatch):
    """Emissão e resgate simulados: o que importa aqui é quem pode o quê."""
    emitidos = {}

    def criar(**kw):
        raw = f"tok-{len(emitidos) + 1}"
        emitidos[raw] = {"id": f"t{len(emitidos) + 1}", "user_id": kw["user_id"], "user_email": kw["user_email"],
                         "target_machine": kw["target_machine"], "certificate_ids": kw["certificate_ids"]}
        return raw, emitidos[raw]["id"], datetime.now(timezone.utc) + timedelta(minutes=10)

    monkeypatch.setattr(ci, "create_install_token", criar)
    monkeypatch.setattr(ci, "alvo_do_token", lambda raw: emitidos.get(raw))
    monkeypatch.setattr(ci, "validate_and_consume_token", lambda raw: emitidos.pop(raw, None))
    monkeypatch.setattr(ci, "build_encrypted_bundle", lambda **kw: {"bundle": "ok", "ids": kw["certificate_ids"]})
    return emitidos


def _entrar(client: TestClient, email: str, maquina: str) -> dict:
    r = client.post("/api/agent/dispositivos/registrar",
                    json={"email": email, "password": SENHA, "machine_id": maquina, "nome": "PC " + maquina[-2:]})
    assert r.status_code == 200, r.text
    return r.json()


def _bandeja(segredo: str) -> dict:
    return {"X-Device-Secret": segredo}


def _autorizar_pendente(client: TestClient, maquina: str, tipo: str = "principal", prazo=None) -> dict:
    itens = client.get("/api/computadores", headers=_h(*ADMIN)).json()["itens"]
    v = next(i for i in itens if i["machine_id"] == maquina and i["estado"] == "pendente")
    r = client.post(f"/api/computadores/{v['id']}/autorizar", headers=_h(*ADMIN), json={"tipo": tipo, "prazo": prazo})
    assert r.status_code == 200, r.text
    return r.json()


def test_fluxo_completo_pelo_portal(client: TestClient, banco: _Fake, tokens: dict) -> None:
    reg = _entrar(client, "fis@x.com", PC_FIS.upper())
    assert reg["autorizacao"] == "pendente" and reg["machine_id"] == PC_FIS
    seg = reg["segredo"]
    assert client.get("/api/estacao/situacao", headers=_bandeja(seg)).json()["autorizacao"] == "pendente"
    # Pendente: o Início diz que aguarda; a fila não entrega nada.
    me = client.get("/api/cert-installer/minha-estacao", headers=_h(*FISCAL_OP)).json()
    assert me["disponivel"] is False and me["motivo"] == "aguardando_autorizacao"

    lista = client.get("/api/computadores", headers=_h(*ADMIN)).json()
    assert lista["resumo"]["pendentes"] == 1 and lista["itens"][0]["email"] == "fis@x.com"
    _autorizar_pendente(client, PC_FIS)

    assert client.get("/api/estacao/situacao", headers=_bandeja(seg)).json()["autorizacao"] == "autorizado"
    me = client.get("/api/cert-installer/minha-estacao", headers=_h(*FISCAL_OP)).json()
    assert me["disponivel"] is True and me["canal"] == "portal" and me["dispositivos"][0]["machine_id"] == PC_FIS

    r = client.post("/api/cert-installer/prepare", headers=_h(*FISCAL_OP),
                    json={"certificate_ids": ["pfx-a"], "machine_id": PC_FIS})
    assert r.status_code == 200, r.text
    assert r.json()["canal"] == "portal"
    entregues = client.get("/api/estacao/instalacoes", headers=_bandeja(seg)).json()["tokens"]
    assert len(entregues) == 1
    assert client.get("/api/estacao/instalacoes", headers=_bandeja(seg)).json()["tokens"] == [], "uma vez só"
    claim = client.post("/api/cert-installer/claim", headers=_bandeja(seg),
                        json={"token": entregues[0], "clientPublicKey": "x"})
    assert claim.status_code == 200 and claim.json()["ids"] == ["pfx-a"]


def test_operador_nao_instala_na_maquina_de_outro_e_admin_instala(client: TestClient, banco: _Fake, tokens: dict) -> None:
    seg_sol = _entrar(client, "solto@x.com", PC_SOL)["segredo"]
    _autorizar_pendente(client, PC_SOL)
    r = client.post("/api/cert-installer/prepare", headers=_h(*FISCAL_OP),
                    json={"certificate_ids": ["pfx-a"], "machine_id": PC_SOL})
    assert r.status_code == 403
    r = client.post("/api/cert-installer/prepare", headers=_h(*ADMIN),
                    json={"certificate_ids": ["pfx-a"], "machine_id": PC_SOL})
    assert r.status_code == 200 and r.json()["canal"] == "portal"
    assert len(client.get("/api/estacao/instalacoes", headers=_bandeja(seg_sol)).json()["tokens"]) == 1


def test_resgate_de_outra_maquina_e_recusado(client: TestClient, banco: _Fake, tokens: dict) -> None:
    seg_fis = _entrar(client, "fis@x.com", PC_FIS)["segredo"]
    _autorizar_pendente(client, PC_FIS)
    seg_sol = _entrar(client, "solto@x.com", PC_SOL)["segredo"]
    _autorizar_pendente(client, PC_SOL)
    client.post("/api/cert-installer/prepare", headers=_h(*FISCAL_OP), json={"certificate_ids": ["pfx-a"], "machine_id": PC_FIS})
    raw = client.get("/api/estacao/instalacoes", headers=_bandeja(seg_fis)).json()["tokens"][0]
    r = client.post("/api/cert-installer/claim", headers=_bandeja(seg_sol), json={"token": raw, "clientPublicKey": "x"})
    assert r.status_code == 403


def test_senha_redefinida_derruba_a_bandeja(client: TestClient, banco: _Fake) -> None:
    seg = _entrar(client, "fis@x.com", PC_FIS)["segredo"]
    r = client.post("/api/users/u-fis/reset-password", headers=_h(*ADMIN), json={"password": "Outra-senha-123!"})
    assert r.status_code == 200, r.text
    assert client.get("/api/estacao/situacao", headers=_bandeja(seg)).status_code == 401


def test_bandeja_sair_e_recusar(client: TestClient, banco: _Fake) -> None:
    seg = _entrar(client, "fis@x.com", PC_FIS)["segredo"]
    assert client.post("/api/estacao/sair", headers=_bandeja(seg)).status_code == 200
    assert client.get("/api/estacao/situacao", headers=_bandeja(seg)).status_code == 401
    seg = _entrar(client, "solto@x.com", PC_SOL)["segredo"]
    v = client.get("/api/computadores", headers=_h(*ADMIN)).json()["itens"]
    pend = next(i for i in v if i["machine_id"] == PC_SOL)
    assert client.post(f"/api/computadores/{pend['id']}/recusar", headers=_h(*ADMIN)).status_code == 200
    assert client.get("/api/estacao/situacao", headers=_bandeja(seg)).status_code == 401
    assert client.get("/api/computadores", headers=_h(*FISCAL_OP)).status_code == 403


def test_principais_para_o_hardlyze_exige_o_segredo_da_ponte(client: TestClient, banco: _Fake,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.config.CERT_PORTAL_TOKEN", "segredo-da-ponte", raising=False)
    _entrar(client, "fis@x.com", PC_FIS)
    _autorizar_pendente(client, PC_FIS)
    assert client.get("/api/computadores/principais").status_code == 401
    r = client.get("/api/computadores/principais", headers={"Authorization": "Bearer segredo-da-ponte"})
    assert r.status_code == 200
    assert r.json()["principais"] == [{**r.json()["principais"][0], "machine_id": PC_FIS, "email": "fis@x.com"}]


def test_importar_do_hardlyze_cria_pedidos_pendentes(client: TestClient, banco: _Fake, monkeypatch) -> None:
    """Transição: logins da bandeja antiga viram pedidos; a máquina vista por
    último vira principal sugerida; o resto é empréstimo; repetir não duplica."""
    import httpx

    monkeypatch.setattr("app.config.INVENT_API_URL", "http://invent", raising=False)
    monkeypatch.setattr("app.config.CERT_PORTAL_TOKEN", "tk", raising=False)
    logins = [
        {"email": "FIS@x.com", "machine_id": PC_FIS.upper(), "nome": "PC-FIS", "visto_em": "2026-10-07T10:00:00Z"},
        {"email": "fis@x.com", "machine_id": PC_SOL, "nome": "PC-SOL", "visto_em": "2026-10-01T10:00:00Z"},
        {"email": "ninguem@x.com", "machine_id": "aa:aa:aa:aa:aa:09", "nome": "PC-9", "visto_em": None},
    ]
    vistos = []

    def falso_get(url, headers=None, timeout=None):
        vistos.append((url, headers))
        return httpx.Response(200, json={"dispositivos": logins}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", falso_get)
    assert client.post("/api/computadores/importar-do-hardlyze", headers=_h(*FISCAL_OP)).status_code == 403
    r = client.post("/api/computadores/importar-do-hardlyze", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert (r.json()["criados"], r.json()["sem_conta"]) == (2, 1)
    assert vistos[0] == ("http://invent/api/agent/devices/todos", {"Authorization": "Bearer tk"})
    pend = {v["machine_id"]: v["tipo"] for v in banco.tabelas["computador_vinculo"] if v["estado"] == "pendente"}
    assert pend == {PC_FIS: "principal", PC_SOL: "emprestimo"}
    r = client.post("/api/computadores/importar-do-hardlyze", headers=_h(*ADMIN)).json()
    assert (r["criados"], r["pulados"]) == (0, 2), "repetir não duplica"


def test_importar_sem_ponte_avisa(client: TestClient, banco: _Fake) -> None:
    r = client.post("/api/computadores/importar-do-hardlyze", headers=_h(*ADMIN))
    assert r.status_code == 409 and "ponte" in r.json()["detail"]


def test_sem_desvio_silencioso_para_o_hardlyze(client: TestClient, banco: _Fake, tokens: dict, monkeypatch) -> None:
    """08/10/2026: com a ponte ligada, o pedido para máquina sem bandeja
    autorizada ia pelo Hardlyze, que a bandeja 2.1.x não atende, e expirava
    sem aviso. Agora é recusado com o que fazer."""
    monkeypatch.setattr("app.config.INVENT_API_URL", "http://invent", raising=False)
    monkeypatch.setattr("app.config.CERT_PORTAL_TOKEN", "tk", raising=False)
    import app.main as m

    monkeypatch.setattr(m, "_pedir_instalacao_ao_invent", lambda *a, **k: pytest.fail("não pode ir pelo Hardlyze"))
    _entrar(client, "fis@x.com", PC_FIS)
    _autorizar_pendente(client, PC_FIS)
    # Operador com bandeja nova pede para outra máquina: recusa.
    r = client.post("/api/cert-installer/prepare", headers=_h(*FISCAL_OP),
                    json={"certificate_ids": ["pfx-a"], "machine_id": "aa:aa:aa:aa:aa:77"})
    assert r.status_code == 409 and "autorizado" in r.json()["detail"]
    # Máquina com bandeja nova ainda pendente: recusa até para o admin.
    _entrar(client, "solto@x.com", PC_SOL)
    r = client.post("/api/cert-installer/prepare", headers=_h(*ADMIN),
                    json={"certificate_ids": ["pfx-a"], "machine_id": PC_SOL})
    assert r.status_code == 409 and "Usuários › Computadores" in r.json()["detail"]
