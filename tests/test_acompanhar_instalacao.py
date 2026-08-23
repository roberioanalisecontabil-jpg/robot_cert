"""A tela deixa de mentir por omissão sobre o desfecho da instalação.

Até 23/08/2026 ela dizia "Pedido enviado" e nunca mais voltava ao assunto. O
resultado ficava no `install_log` ou na janela do agente — dois lugares onde
quem clicou não está.

O que está guardado aqui:

  * o token NUNCA volta ao navegador; o que volta é o id do registro
  * ninguém acompanha o pedido de outra pessoa
  * falha ao consultar não vira alarme — a tela pergunta isto em laço
  * quando falha, a resposta diz o MOTIVO, não só que falhou
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.cert_installer as ci
import app.main as m
from app import auth

TOKEN_ID = "tid-123"
EMAIL = "op@x.com"


def _h(email: str = EMAIL) -> dict:
    return {"Authorization": f"Bearer {auth.create_access_token({'sub': email, 'role': 'user'})}"}


def _acompanhar(client: TestClient, tid: str = TOKEN_ID, email: str = EMAIL):
    return client.get(f"/api/cert-installer/acompanhar/{tid}", headers=_h(email))


@pytest.fixture
def cadeias(monkeypatch: pytest.MonkeyPatch):
    """Guarda por qual e-mail a trilha foi consultada."""
    consultas: list[dict[str, Any]] = []
    dados: dict[str, list] = {"cadeias": []}

    def _fake(**kw):
        consultas.append(kw)
        return dados["cadeias"]

    monkeypatch.setattr(ci, "cadeias_de_instalacao", _fake)
    return {"consultas": consultas, "dados": dados, "monkeypatch": monkeypatch}


# ── 1. Escopo ────────────────────────────────────────────────────────────


def test_so_enxerga_a_propria_trilha(client: TestClient, cadeias) -> None:
    """
    Um token de instalação é a entrega de uma chave privada. Saber o andamento
    do pedido de outra pessoa já diz demais — quem, quando, para qual máquina.
    """
    _acompanhar(client)
    assert cadeias["consultas"], "não consultou a trilha"
    assert cadeias["consultas"][0]["user_email"] == EMAIL


def test_token_de_outro_dono_nao_aparece(client: TestClient, cadeias) -> None:
    """
    A trilha vem filtrada pelo dono, então o token alheio simplesmente não está
    lá — e a resposta é a mesma de um pedido que ainda não saiu. Distinguir
    diria a quem pergunta que aquele id existe.
    """
    cadeias["dados"]["cadeias"] = [{"token_id": "de-outra-pessoa", "desfecho": "concluido"}]
    assert _acompanhar(client).json()["desfecho"] == "aguardando"


# ── 2. Desfechos ─────────────────────────────────────────────────────────


def test_concluido(client: TestClient, cadeias) -> None:
    cadeias["dados"]["cadeias"] = [
        {"token_id": TOKEN_ID, "desfecho": "concluido", "parou_em": None, "eventos": []}
    ]
    assert _acompanhar(client).json()["desfecho"] == "concluido"


def test_falha_devolve_o_motivo(client: TestClient, cadeias) -> None:
    """
    Sem o motivo a pessoa saberia que falhou e não o que fazer. Ele vem da
    trilha, que recebeu o relato do próprio agente.
    """
    cadeias["dados"]["cadeias"] = [{
        "token_id": TOKEN_ID, "desfecho": "falhou", "parou_em": "REDIMIDO",
        "eventos": [
            {"event": "SOLICITADO", "detail": None},
            {"event": "ERRO", "detail": "Token inválido, expirado ou já utilizado"},
        ],
    }]
    d = _acompanhar(client).json()
    assert d["desfecho"] == "falhou"
    assert "expirado" in d["detalhe"]
    assert d["parou_em"] == "REDIMIDO"


def test_pedido_ainda_sem_desfecho_e_aguardando(client: TestClient, cadeias) -> None:
    """
    `incompleto` é vocabulário da trilha; para quem está olhando a tela, é
    "aguardando". Ela não pode fazer nada diferente sabendo a diferença.
    """
    cadeias["dados"]["cadeias"] = [
        {"token_id": TOKEN_ID, "desfecho": "incompleto", "parou_em": "SOLICITADO", "eventos": []}
    ]
    assert _acompanhar(client).json()["desfecho"] == "aguardando"


# ── 3. A consulta é feita em laço — não pode alarmar ─────────────────────


def test_falha_ao_consultar_nao_vira_erro(client: TestClient, cadeias) -> None:
    """
    A tela pergunta isto a cada 2s. Um 500 faria a pessoa ver um alarme por
    causa de uma consulta que ela nem sabe que existe — e o certificado pode
    ter entrado.
    """
    def _explode(**_kw):
        raise RuntimeError("banco fora do ar")

    cadeias["monkeypatch"].setattr(ci, "cadeias_de_instalacao", _explode)

    r = _acompanhar(client)
    assert r.status_code == 200
    assert r.json()["desfecho"] == "desconhecido"


# ── 4. O token não volta para o navegador ────────────────────────────────


def test_o_prepare_devolve_o_id_do_registro_e_nao_o_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    É o id do REGISTRO que a tela usa para acompanhar. O token em si é a
    entrega da chave privada e não tem o que fazer no navegador.
    """
    monkeypatch.setattr(m, "_user_id_da_sessao", lambda t: "u-op")
    monkeypatch.setattr(m, "_validar_pedido_de_instalacao", lambda *a, **k: None)
    monkeypatch.setattr(ci, "create_install_token", lambda **kw: ("TOKEN-SECRETO", TOKEN_ID, None))
    monkeypatch.setattr(ci, "log_event", lambda **kw: None)
    monkeypatch.setattr("app.config.INVENT_API_URL", "http://x", raising=False)
    monkeypatch.setattr("app.config.CERT_PORTAL_TOKEN", "s", raising=False)
    monkeypatch.setattr(m, "_pedir_instalacao_ao_invent", lambda *a, **k: None)

    r = client.post(
        "/api/cert-installer/prepare",
        json={"certificate_ids": ["c1"], "machine_id": "aa:bb"},
        headers=_h(),
    )
    assert r.status_code == 200, r.text
    assert r.json()["token_id"] == TOKEN_ID
    assert "TOKEN-SECRETO" not in r.text


def test_a_tela_desiste_com_instrucao_em_vez_de_girar_para_sempre() -> None:
    """
    Passado o tempo, a pessoa precisa saber ONDE olhar — não ficar vendo uma
    barrinha. A instalação real levou 37s; um minuto cobre com folga.
    """
    from pathlib import Path

    html = (Path(__file__).resolve().parent.parent / "templates" / "index.html").read_text(
        encoding="utf-8"
    )
    corpo = html[html.index("async function acompanharInstalacao") :]
    corpo = corpo[: corpo.index("\n      }\n")]
    assert "Hardlyze Agent" in corpo, "a desistência tem de dizer onde olhar"
    assert "ACOMPANHAR_TENTATIVAS" in corpo
