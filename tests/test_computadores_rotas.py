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


def _chave(maquina: str) -> str:
    """A chave que a bandeja 2.1.4 gerou na máquina física (adendo ao ADR 0002)."""
    return ("chave-da-maquina-" + maquina.lower()).ljust(43, "x")


def _registrar(client: TestClient, email: str, maquina: str, chave=None):
    corpo = {"email": email, "password": SENHA, "machine_id": maquina, "nome": "PC " + maquina[-2:]}
    if chave is not None:
        corpo["chave_maquina"] = chave
    return client.post("/api/agent/dispositivos/registrar", json=corpo)


def _entrar(client: TestClient, email: str, maquina: str) -> dict:
    r = _registrar(client, email, maquina, _chave(maquina))
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


def test_token_de_quem_pediu_nao_vai_para_quem_ocupa_a_maquina_depois(
    client: TestClient, banco: _Fake, tokens: dict
) -> None:
    """Auditoria de 10/10/2026 (claim-token-not-bound-to-requesting-user): a
    fila entregava por máquina e o /claim conferia o vínculo de quem chegava,
    não quem pediu. O dono principal que retomasse a máquina recebia o
    certificado que a pessoa do empréstimo pediu — fora da carteira dele."""
    _entrar(client, "solto@x.com", PC_FIS)
    _autorizar_pendente(client, PC_FIS)  # solto: principal
    _entrar(client, "fis@x.com", PC_FIS)
    _autorizar_pendente(client, PC_FIS, tipo="emprestimo", prazo="fim_do_dia")
    r = client.post("/api/cert-installer/prepare", headers=_h(*FISCAL_OP),
                    json={"certificate_ids": ["pfx-a"], "machine_id": PC_FIS})
    assert r.status_code == 200, r.text
    raw = next(iter(tokens))

    seg_solto = _entrar(client, "solto@x.com", PC_FIS)["segredo"]  # dono retoma
    assert client.get("/api/estacao/instalacoes", headers=_bandeja(seg_solto)).json()["tokens"] == []
    r = client.post("/api/cert-installer/claim", headers=_bandeja(seg_solto), json={"token": raw, "clientPublicKey": "x"})
    assert r.status_code == 403
    assert raw in tokens, "o token de quem pediu não pode ser queimado por quem não pediu"


def test_token_pedido_pelo_admin_vai_para_a_bandeja_da_maquina(
    client: TestClient, banco: _Fake, tokens: dict
) -> None:
    """Instalar na máquina de alguém é poder do administrador por desenho: o
    token dele continua sendo entregue e resgatado pela bandeja daquela máquina."""
    seg_sol = _entrar(client, "solto@x.com", PC_SOL)["segredo"]
    _autorizar_pendente(client, PC_SOL)
    assert client.post("/api/cert-installer/prepare", headers=_h(*ADMIN),
                       json={"certificate_ids": ["pfx-a"], "machine_id": PC_SOL}).status_code == 200
    raw = client.get("/api/estacao/instalacoes", headers=_bandeja(seg_sol)).json()["tokens"][0]
    r = client.post("/api/cert-installer/claim", headers=_bandeja(seg_sol), json={"token": raw, "clientPublicKey": "x"})
    assert r.status_code == 200 and r.json()["ids"] == ["pfx-a"]


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


def test_trocar_a_propria_senha_derruba_a_bandeja(client: TestClient, banco: _Fake) -> None:
    """Auditoria de 10/10/2026 (app/rotas/usuarios.py:senha_trocar:sem-sair_de_tudo):
    a redefinição pelo admin e por código derrubavam a bandeja, a troca pela
    própria pessoa não. Quem troca a senha por suspeitar de invasão deixava o
    segredo da bandeja do invasor valendo."""
    seg = _entrar(client, "fis@x.com", PC_FIS)["segredo"]
    assert client.get("/api/estacao/situacao", headers=_bandeja(seg)).status_code == 200
    r = client.post("/api/senha/trocar", headers=_h(*FISCAL_OP),
                    json={"senha_atual": SENHA, "nova_senha": "Outra-senha-123!"})
    assert r.status_code == 200, r.text
    assert client.get("/api/estacao/situacao", headers=_bandeja(seg)).status_code == 401
    assert client.post("/api/agent/dispositivos/token", json={"segredo": seg}).status_code == 401


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


def test_rota_de_principais_saiu(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    """12/10/2026: sem consumidor desde o Hardlyze 2.1.3. Nem com o segredo
    da ponte ela responde."""
    monkeypatch.setattr("app.config.CERT_PORTAL_TOKEN", "segredo-da-ponte", raising=False)
    r = client.get("/api/computadores/principais", headers={"Authorization": "Bearer segredo-da-ponte"})
    assert r.status_code in (401, 404, 405)
    assert "principais" not in r.text


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


def test_sem_bandeja_autorizada_nao_ha_instalacao(client: TestClient, banco: _Fake, tokens: dict) -> None:
    """08/10/2026: o caminho antigo pelo Hardlyze foi cortado. Pedido para
    máquina sem bandeja autorizada é recusado com o que fazer."""
    _entrar(client, "fis@x.com", PC_FIS)
    _autorizar_pendente(client, PC_FIS)
    r = client.post("/api/cert-installer/prepare", headers=_h(*FISCAL_OP),
                    json={"certificate_ids": ["pfx-a"], "machine_id": "aa:aa:aa:aa:aa:77"})
    assert r.status_code == 409 and "autorizado" in r.json()["detail"]
    _entrar(client, "solto@x.com", PC_SOL)  # pendente
    r = client.post("/api/cert-installer/prepare", headers=_h(*ADMIN),
                    json={"certificate_ids": ["pfx-a"], "machine_id": PC_SOL})
    assert r.status_code == 409 and "Usuários › Computadores" in r.json()["detail"]
    me = client.get("/api/cert-installer/minha-estacao", headers=_h(*ADMIN)).json()
    assert me["motivo"] == "sem_computador", "sem computador não há mais consulta ao Hardlyze"


def test_senha_sozinha_nao_da_bandeja_autorizada_na_maquina_da_vitima(
    client: TestClient, banco: _Fake, tokens: dict
) -> None:
    """Auditoria de 10/10/2026, item 1 (app/agent_devices.py:registrar:machine-id-
    autodeclarado-autoriza-reentrada): com a senha e o machine_id da vítima, de
    qualquer lugar, o par autorizado reconectava sem o admin, o segredo da bandeja
    verdadeira era trocado e os PFX da carteira saíam pelo /claim."""
    seg_real = _entrar(client, "fis@x.com", PC_FIS)["segredo"]
    _autorizar_pendente(client, PC_FIS)
    me = client.get("/api/cert-installer/minha-estacao", headers=_h(*FISCAL_OP)).json()
    assert me["dispositivos"][0]["machine_id"] == PC_FIS  # o machine_id não é segredo

    for chave_do_intruso in (None, "chave-de-quem-so-tem-a-senha".ljust(43, "z")):
        r = _registrar(client, "fis@x.com", PC_FIS, chave_do_intruso)
        assert r.status_code in (403, 409), r.text
        assert "segredo" not in r.text
    assert r.status_code == 409 or r.headers.get("X-Confirmacao-Pendente") == "1"
    assert client.get("/api/estacao/situacao", headers=_bandeja(seg_real)).status_code == 200,         "a bandeja verdadeira foi derrubada"
