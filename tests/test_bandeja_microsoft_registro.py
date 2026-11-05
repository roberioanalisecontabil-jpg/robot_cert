"""Rotas que a bandeja chama na entrada pela Microsoft: /api/agent/microsoft e
/api/agent/dispositivos/registrar-microsoft, mais o contador da virada em
/api/computadores. Sem rede nem banco: o duplo da recuperação de senha."""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from app import bandeja_codigo, computadores, agent_devices
from tests.test_recuperacao_de_senha import _Fake
from tests.test_seguranca_lote4 import ADMIN, _h

DOM = "analisegroup.cnt.br"
EMAIL = f"ana@{DOM}"
VERIFICADOR = "verificador-da-bandeja"
MAQUINA = "aa:aa:aa:aa:aa:01"


@pytest.fixture(autouse=True)
def ligado(monkeypatch: pytest.MonkeyPatch) -> None:
    for nome, valor in (
        ("MICROSOFT_TENANT_ID", "t-1"), ("MICROSOFT_CLIENT_ID", "c-1"),
        ("MICROSOFT_CLIENT_SECRET", "s-1"), ("MICROSOFT_DOMINIOS", frozenset({DOM})),
        ("PORTAL_BASE_URL", "https://certificado.analisegroup.cnt.br"),
    ):
        monkeypatch.setattr(f"app.config.{nome}", valor, raising=False)


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake({
        "users": [
            {"id": "u-ana", "email": EMAIL, "full_name": "Ana", "role": "user", "ativo": True},
            {"id": "u-adm", "email": ADMIN[0], "full_name": "Adm", "role": "admin", "ativo": True},
            {"id": "u-saiu", "email": f"saiu@{DOM}", "full_name": "Saiu", "role": "user", "ativo": False},
        ],
        "bandeja_codigo": [],
        "user_activity": [],
    })
    monkeypatch.setattr("app.settings_state._banco", lambda: fake)
    return fake


@pytest.fixture
def entrar(monkeypatch: pytest.MonkeyPatch) -> List[tuple]:
    chamadas: List[tuple] = []

    def _fake(user_id: str, machine_id: str, nome: str, chave: Any = None):
        chamadas.append((user_id, machine_id, nome, chave))
        return "segredo-1", {"autorizacao": "autorizado", "tipo": "principal"}

    monkeypatch.setattr(computadores, "entrar", _fake)
    return chamadas


def _codigo(user_id: str = "u-ana") -> str:
    return bandeja_codigo.emitir(user_id, bandeja_codigo.desafio_de(VERIFICADOR))


def _registrar(client: TestClient, codigo: str, verificador: str = VERIFICADOR):
    return client.post("/api/agent/dispositivos/registrar-microsoft", json={
        "codigo": codigo, "verificador": verificador, "machine_id": MAQUINA, "nome": "PC 01",
    })


def test_microsoft_ligado_reflete_a_configuracao(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert client.get("/api/agent/microsoft").json() == {"ligado": True}
    monkeypatch.setattr("app.config.MICROSOFT_CLIENT_ID", "", raising=False)
    assert client.get("/api/agent/microsoft").json() == {"ligado": False}


def test_registrar_microsoft_devolve_o_mesmo_corpo(client: TestClient, banco: _Fake, entrar: List[tuple]) -> None:
    r = _registrar(client, _codigo())
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["segredo"] == "segredo-1" and j["machine_id"] == MAQUINA
    assert j["email"] == EMAIL and j["role"] == "user"
    assert {"autorizacao", "mensagem"} <= set(j)
    assert entrar[0][0] == "u-ana"


def test_registrar_microsoft_codigo_reusado_401(client: TestClient, banco: _Fake, entrar: List[tuple]) -> None:
    c = _codigo()
    assert _registrar(client, c).status_code == 200
    r = _registrar(client, c)
    assert r.status_code == 401 and "expirou" in r.json()["detail"]
    assert _registrar(client, _codigo(), "outro-verificador").status_code == 401


def test_registrar_microsoft_conta_desativada_403(client: TestClient, banco: _Fake, entrar: List[tuple]) -> None:
    r = _registrar(client, _codigo("u-saiu"))
    assert r.status_code == 403 and "desativada" in r.json()["detail"]
    assert not entrar


def test_registrar_microsoft_confirmacao_pendente_igual(
    client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(computadores, "entrar", lambda *a, **k: (None, {"autorizacao": "pendente"}))
    r = _registrar(client, _codigo())
    assert r.status_code == 403 and r.headers.get("X-Confirmacao-Pendente") == "1"


def test_registrar_microsoft_banco_fora_503(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    def _quebra(*a: Any, **k: Any):
        raise RuntimeError("banco fora")

    monkeypatch.setattr(bandeja_codigo, "queimar", _quebra)
    r = _registrar(client, "x")
    assert r.status_code == 503 and r.json()["detail"] == "Não foi possível concluir agora. Tente de novo."


def test_registrar_microsoft_desligado_404(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.config.MICROSOFT_CLIENT_ID", "", raising=False)
    assert _registrar(client, "x").status_code == 404


def test_computadores_mostra_quem_segura_a_virada(
    client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    agora = datetime.now(timezone.utc)
    disp: List[Dict[str, Any]] = [
        {"user_id": "u-ana", "machine_id": MAQUINA, "nome": "PC 01", "versao": "certguard-1.1.1",
         "visto_em": agora.isoformat(), "revogado_em": None},
        {"user_id": "u-ana", "machine_id": "bb", "nome": "Velho", "versao": "certguard-1.0.0",
         "visto_em": (agora - timedelta(days=90)).isoformat(), "revogado_em": None},
    ]
    monkeypatch.setattr(agent_devices, "listar", lambda *a, **k: disp)
    monkeypatch.setattr(computadores, "listar", lambda *a, **k: [])
    r = client.get("/api/computadores", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    b = r.json()["resumo"]["bandeja"]
    assert b["desligada_em"] is None
    assert b["segurando"] == [{"nome": "PC 01", "machine_id": MAQUINA, "versao": "certguard-1.1.1", "email": EMAIL}]
    monkeypatch.setattr("app.config.MICROSOFT_CLIENT_ID", "", raising=False)
    assert "bandeja" not in client.get("/api/computadores", headers=_h(*ADMIN)).json()["resumo"]
