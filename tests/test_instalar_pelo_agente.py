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

    def _ponte(machine_id, token_raw, hostname, expira_em=None):
        pedidos.append({
            "machine_id": machine_id,
            "token": token_raw,
            "hostname": hostname,
            "expira_em": expira_em,
        })

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
    Até 23/08/2026 o caminho do download gravava "download-avulso", porque não
    sabia onde o certificado ia cair. Ele saiu, e agora a trilha sempre sabe —
    é o que a torna capaz de responder ONDE o certificado entrou.
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


# ── 4. "Onde estou?" — e o que acontece quando não dá para saber ─────────

def _minha_estacao(client: TestClient):
    return client.get("/api/cert-installer/minha-estacao", headers=_h())


def test_sem_ponte_configurada_o_botao_nao_aparece(client: TestClient) -> None:
    """Estado em que este commit entra em produção: nada muda no Início."""
    r = _minha_estacao(client)
    assert r.status_code == 200
    assert r.json()["disponivel"] is False
    assert r.json()["motivo"] == "nao_configurado"


def test_portal_de_inventario_fora_do_ar_nao_derruba_o_inicio(
    client: TestClient, cenario
) -> None:
    """
    O teste que importa nesta rota.

    Uma indisponibilidade do outro portal não pode quebrar a tela onde todo
    mundo aterrissa depois do login. Ela apenas faz o botão não aparecer, e a
    pessoa cai no caminho do .exe — que é o que ela já fazia antes de tudo isto
    existir. Degradar para o caminho antigo é diferente de quebrar.
    """
    import httpx

    def _explode(*_a, **_k):
        raise httpx.ConnectError("sem rede")

    cenario["monkeypatch"].setattr(httpx, "get", _explode)

    r = _minha_estacao(client)
    assert r.status_code == 200, "o Início não pode receber erro por causa disto"
    assert r.json()["disponivel"] is False
    assert r.json()["motivo"] == "indisponivel"


def test_resposta_de_erro_do_outro_portal_tambem_degrada(
    client: TestClient, cenario
) -> None:
    import httpx

    class _R:
        status_code = 503

        def json(self):
            return {}

    cenario["monkeypatch"].setattr(httpx, "get", lambda *a, **k: _R())
    assert _minha_estacao(client).json()["disponivel"] is False


def test_com_agente_vivo_o_botao_aparece(client: TestClient, cenario) -> None:
    import httpx

    class _R:
        status_code = 200

        def json(self):
            return {"dispositivos": [{"machine_id": MAQUINA, "nome": "TI-002"}]}

    cenario["monkeypatch"].setattr(httpx, "get", lambda *a, **k: _R())

    corpo = _minha_estacao(client).json()
    assert corpo["disponivel"] is True
    assert corpo["dispositivos"][0]["machine_id"] == MAQUINA


def test_sem_agente_vivo_diz_o_motivo(client: TestClient, cenario) -> None:
    """
    "Nenhum agente vivo" e "não consegui perguntar" são situações diferentes, e
    a tela pode querer dizer coisas diferentes. Um motivo só apagaria isso.
    """
    import httpx

    class _R:
        status_code = 200

        def json(self):
            return {"dispositivos": []}

    cenario["monkeypatch"].setattr(httpx, "get", lambda *a, **k: _R())
    assert _minha_estacao(client).json()["motivo"] == "sem_agente_vivo"


# ── 5. O prazo viaja com o pedido ────────────────────────────────────────


def test_o_prazo_do_token_vai_junto_para_o_outro_portal(
    client: TestClient, cenario
) -> None:
    """
    Sem o prazo, o portal de inventário não tem como saber que o comando morreu:
    o token é opaco do lado de lá, e a validade é configurável aqui (1 min a
    24 h), então nenhum teto adivinhado lá serviria.

    O efeito de não mandar é a máquina desligada acordar horas depois, tentar,
    ser recusada — e a trilha ganhar um ERRO que não é erro nenhum, no lugar
    onde ela é usada como prova.
    """
    from datetime import datetime, timedelta, timezone

    prazo = datetime.now(timezone.utc) + timedelta(minutes=5)
    cenario["monkeypatch"].setattr(
        ci, "create_install_token", lambda **kw: (TOKEN_EMITIDO, "tid-1", prazo)
    )

    assert _pedir(client).status_code == 200
    assert cenario["pedidos"][0]["expira_em"] == prazo


def test_o_prazo_sai_em_iso_no_corpo_da_ponte(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    O `datetime` tem de virar ISO antes de sair — `json=` não serializa objeto
    de data, e a falha apareceria só em produção, no momento do clique.
    """
    from datetime import datetime, timezone

    import httpx

    enviados: List[Dict[str, Any]] = []

    class _R:
        status_code = 200

        def json(self):
            return {}

    def _post(_url, **kw):
        enviados.append(kw.get("json") or {})
        return _R()

    monkeypatch.setattr(httpx, "post", _post)
    monkeypatch.setattr("app.config.INVENT_API_URL", "http://invent-de-teste", raising=False)
    monkeypatch.setattr("app.config.CERT_PORTAL_TOKEN", "segredo", raising=False)

    prazo = datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc)
    m._pedir_instalacao_ao_invent(MAQUINA, TOKEN_EMITIDO, "TI-002", prazo)

    assert enviados[0]["expira_em"] == prazo.isoformat()
    assert isinstance(enviados[0]["expira_em"], str)

    # Sem prazo conhecido o campo vai nulo, e o outro lado volta ao
    # comportamento antigo — esperar na fila até a máquina acordar.
    m._pedir_instalacao_ao_invent(MAQUINA, TOKEN_EMITIDO, None, None)
    assert enviados[1]["expira_em"] is None
