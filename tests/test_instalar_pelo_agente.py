"""Instalar pelo agente residente: o pedido que atravessa os dois portais.

A rota emite o token e pede ao portal de inventário que a estação instale. O
que ela guarda, além da barreira de carteira (essa fica em `test_carteira.py`,
que já a cobre pela matriz de rotas):

  * **a trilha não mente.** SOLICITADO só é gravado depois de o comando CHEGAR
    ao outro portal. Gravar antes deixaria o registro afirmando um pedido que
    talvez nunca tenha saído daqui — e a trilha existe para ser confiável.

  * **falha da ponte não vira "enviado".** Se o outro portal recusa, a pessoa
    precisa saber; a pior tela possível é "pedido enviado" para um agente que
    nunca vai receber nada.

  * **o token não volta na resposta.** Ele é a entrega da chave privada; o
    navegador não tem o que fazer com ele.

  * **ponte desligada é 503, não 404.** A rota existe; o que falta é a ligação
    entre os dois portais, e quem implanta precisa da diferença.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

import app.cert_installer as ci
import app.main as m
from app import auth

MAQUINA = "aa:bb:cc:dd:ee:ff"
CERT = "cert-do-operador"
TOKEN_EMITIDO = "token-de-uso-unico-emitido-agora"


@pytest.fixture
def cenario(monkeypatch: pytest.MonkeyPatch):
    """Barreira liberada, token previsível, trilha e ponte observáveis."""
    trilha: List[Dict[str, Any]] = []
    pedidos: List[Dict[str, Any]] = []

    monkeypatch.setattr(m, "_user_id_da_sessao", lambda t: "u-operador")
    monkeypatch.setattr(m, "_validar_pedido_de_instalacao", lambda *a, **k: None)
    monkeypatch.setattr(
        ci, "create_install_token",
        lambda **kw: (TOKEN_EMITIDO, "tid-1", None),
    )
    monkeypatch.setattr(ci, "log_event", lambda **kw: trilha.append(kw))
    monkeypatch.setattr("app.config.INVENT_API_URL", "http://invent-de-teste", raising=False)
    monkeypatch.setattr("app.config.CERT_PORTAL_TOKEN", "segredo", raising=False)

    def _ponte(machine_id, token_raw, hostname):
        pedidos.append({"machine_id": machine_id, "token": token_raw, "hostname": hostname})

    monkeypatch.setattr(m, "_pedir_instalacao_ao_invent", _ponte)
    return {"trilha": trilha, "pedidos": pedidos, "monkeypatch": monkeypatch}


def _h() -> dict:
    return {"Authorization": f"Bearer {auth.create_access_token({'sub': 'op@x.com', 'role': 'user'})}"}


def _pedir(client: TestClient, **extra):
    corpo = {"certificate_ids": [CERT], "machine_id": MAQUINA}
    corpo.update(extra)
    return client.post("/api/cert-installer/prepare", json=corpo, headers=_h())


# ── 1. O caminho feliz ───────────────────────────────────────────────────

def test_emite_o_token_e_pede_ao_outro_portal(client: TestClient, cenario) -> None:
    r = _pedir(client)
    assert r.status_code == 200, r.text
    assert r.json()["machine_id"] == MAQUINA

    assert len(cenario["pedidos"]) == 1
    assert cenario["pedidos"][0]["token"] == TOKEN_EMITIDO
    assert cenario["pedidos"][0]["machine_id"] == MAQUINA


def test_o_token_nao_volta_para_o_navegador(client: TestClient, cenario) -> None:
    """Ele é a entrega da chave privada; o front não tem o que fazer com ele."""
    assert TOKEN_EMITIDO not in _pedir(client).text


def test_a_trilha_registra_a_maquina_de_verdade(client: TestClient, cenario) -> None:
    """
    `/preparar-download` grava "download-avulso" porque não sabe onde o
    certificado vai cair. Aqui sabe — e é isso que torna a trilha capaz de
    responder ONDE o certificado entrou.
    """
    _pedir(client)
    assert cenario["trilha"], "nada foi registrado"
    assert all(e["target_machine"] == MAQUINA for e in cenario["trilha"])
    assert all(e["event"] == "SOLICITADO" for e in cenario["trilha"])


# ── 2. A trilha não mente ────────────────────────────────────────────────

def test_falha_da_ponte_nao_deixa_rastro_de_pedido(client: TestClient, cenario) -> None:
    """
    O teste central deste arquivo. Se SOLICITADO fosse gravado antes de o
    comando chegar, a trilha afirmaria um pedido que morreu aqui — e numa
    auditoria isso é pior que não registrar nada.
    """
    def _explode(*_a, **_k):
        raise RuntimeError("o portal de inventário respondeu 503")

    cenario["monkeypatch"].setattr(m, "_pedir_instalacao_ao_invent", _explode)

    r = _pedir(client)
    assert r.status_code == 502
    assert "inventário" in r.json()["detail"] or "inventario" in r.json()["detail"]
    assert cenario["trilha"] == [], "gravou SOLICITADO para um pedido que não saiu"


def test_falha_da_ponte_diz_o_motivo(client: TestClient, cenario) -> None:
    """"Erro interno" mandaria alguém ao log; o motivo resolve na tela."""
    def _explode(*_a, **_k):
        raise RuntimeError("CERT_PORTAL_TOKEN invalido")

    cenario["monkeypatch"].setattr(m, "_pedir_instalacao_ao_invent", _explode)
    assert "CERT_PORTAL_TOKEN" in _pedir(client).json()["detail"]


# ── 3. Configuração e entrada ────────────────────────────────────────────

def test_ponte_desligada_e_503(client: TestClient, cenario) -> None:
    """
    503 e não 404: a rota existe, o que falta é a ligação entre os portais.
    É também o estado em que este commit entra em produção.
    """
    cenario["monkeypatch"].setattr("app.config.INVENT_API_URL", "", raising=False)
    r = _pedir(client)
    assert r.status_code == 503
    assert "INVENT_API_URL" in r.json()["detail"]


def test_sem_maquina_e_400(client: TestClient, cenario) -> None:
    assert _pedir(client, machine_id="   ").status_code == 400


def test_sem_certificado_e_400(client: TestClient, cenario) -> None:
    assert _pedir(client, certificate_ids=[]).status_code == 400


def test_a_configuracao_e_conferida_antes_de_emitir_token(
    client: TestClient, cenario
) -> None:
    """
    Emitir um token e só então descobrir que não há para quem mandar deixaria um
    token válido solto, sem consumidor, até expirar. Barato de evitar: conferir
    a ponte primeiro.
    """
    emitidos = []
    cenario["monkeypatch"].setattr(
        ci, "create_install_token",
        lambda **kw: emitidos.append(kw) or (TOKEN_EMITIDO, "tid", None),
    )
    cenario["monkeypatch"].setattr("app.config.CERT_PORTAL_TOKEN", "", raising=False)

    assert _pedir(client).status_code == 503
    assert emitidos == [], "emitiu token mesmo sem ter para quem mandar"
