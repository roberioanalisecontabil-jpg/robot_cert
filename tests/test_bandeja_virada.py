"""Virada da senha da bandeja: só vira quando a frota inteira (vista nos
últimos 30 dias) está na bandeja nova, e depois dela o registro por senha dos
domínios da Microsoft é 403 antes de conferir a senha."""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from app import bandeja_virada
from tests.test_login_microsoft_obrigacao import DOM, OP, SENHA, ligado, _u  # noqa: F401
from tests.test_recuperacao_de_senha import _Fake

AGORA = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def _d(versao: Any, dias: int = 1, revogado: Any = None) -> Dict[str, Any]:
    return {"id": "d", "versao": versao, "revogado_em": revogado,
            "visto_em": (AGORA - timedelta(days=dias)).isoformat()}


def test_hardlyze_e_nulas_nao_contam() -> None:
    s = bandeja_virada.situacao([_d("certguard-1.2.0"), _d("2.2.0"), _d(None)], AGORA)
    assert s["na_nova"] == 1 and s["segurando"] == [] and bandeja_virada.pronta(s)


def test_antiga_recente_segura() -> None:
    antiga = _d("certguard-1.1.1", dias=3)
    s = bandeja_virada.situacao([_d("certguard-1.2.0"), antiga], AGORA)
    assert s["segurando"] == [antiga] and not bandeja_virada.pronta(s)


def test_antiga_revogada_ou_velha_nao_segura() -> None:
    s = bandeja_virada.situacao(
        [_d("certguard-1.2.0"), _d("certguard-1.1.1", revogado="2026-11-01T00:00:00+00:00"),
         _d("certguard-1.1.1", dias=31)], AGORA)
    assert s["segurando"] == [] and bandeja_virada.pronta(s)


def test_frota_vazia_nao_vira() -> None:
    s = bandeja_virada.situacao([_d("2.2.0")], AGORA)
    assert s["na_nova"] == 0 and not bandeja_virada.pronta(s)


def test_versao_acima_conta_como_nova() -> None:
    assert bandeja_virada.situacao([_d("certguard-1.3.0")], AGORA)["na_nova"] == 1


def _frota_nova() -> List[Dict[str, Any]]:
    agora = datetime.now(timezone.utc).isoformat()
    return [{"id": "d1", "user_id": "u", "machine_id": "m", "nome": "x",
             "versao": "certguard-1.2.0", "visto_em": agora, "revogado_em": None}]


def test_conferir_vira_uma_vez_e_avisa_uma_vez(monkeypatch: pytest.MonkeyPatch, ligado: None) -> None:
    fake = _Fake({"agent_devices": _frota_nova(), bandeja_virada.TABELA: []})
    avisos: List[Any] = []
    monkeypatch.setattr("app.microsoft_conferencia._enviar_ti", lambda a, l: avisos.append((a, l)) or True)
    assert "desligada_em" in bandeja_virada.conferir(fake)
    assert "desligada_em" in bandeja_virada.conferir(fake)
    assert len(fake.tabelas[bandeja_virada.TABELA]) == 1 and len(avisos) == 1


def test_conferir_desligada_sem_configuracao() -> None:
    fake = _Fake({"agent_devices": _frota_nova(), bandeja_virada.TABELA: []})
    assert bandeja_virada.conferir(fake) == {"ligada": False}
    assert fake.tabelas[bandeja_virada.TABELA] == []


@pytest.fixture
def virada(monkeypatch: pytest.MonkeyPatch, ligado: None) -> _Fake:
    from app import auth
    fake = _Fake({"users": [_u("u-op", OP, microsoft_oid="o")], "user_activity": [],
                  bandeja_virada.TABELA: [{"id": 1, "desligada_em": "2026-11-05T00:00:00+00:00", "versao": "1.2.0"}]})
    monkeypatch.setattr("app.settings_state._banco", lambda: fake)
    return fake


def _registrar(client: TestClient, email: str, senha: str = SENHA):
    return client.post("/api/agent/dispositivos/registrar",
                       json={"email": email, "password": senha, "machine_id": "AA:BB:CC:DD:EE:FF"})


def _nao_conferir(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*a: Any, **k: Any) -> None:
        raise AssertionError("senha conferida")
    monkeypatch.setattr("app.rotas.agente._conferir_credenciais", _boom)


@pytest.mark.parametrize("email,senha", [(OP, SENHA), (OP, "errada"), (f"ninguem@{DOM}", SENHA)])
def test_registrar_depois_da_virada_403_antes_da_senha(
    client: TestClient, virada: _Fake, monkeypatch: pytest.MonkeyPatch, email: str, senha: str
) -> None:
    _nao_conferir(monkeypatch)
    r = _registrar(client, email, senha)
    assert r.status_code == 403 and r.json()["detail"] == "Use Entrar com a Microsoft."
    assert virada.tabelas["user_activity"][-1]["contexto"]["motivo"] == "bandeja_so_microsoft"


def test_registrar_fora_do_dominio_segue(client: TestClient, virada: _Fake) -> None:
    r = _registrar(client, "fulano@gmail.com")
    assert r.json().get("detail") != "Use Entrar com a Microsoft."


def test_registrar_sem_configuracao_ignora_a_marca(client: TestClient, virada: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.config.MICROSOFT_TENANT_ID", "", raising=False)
    chamadas: List[Any] = []

    def _conf(*a: Any, **k: Any) -> None:
        chamadas.append(a)
        raise RuntimeError("parou aqui")
    monkeypatch.setattr("app.rotas.agente._conferir_credenciais", _conf)
    with pytest.raises(RuntimeError):
        _registrar(client, OP)
    assert chamadas
