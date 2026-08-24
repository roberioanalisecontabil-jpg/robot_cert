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

from contextlib import contextmanager
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
    barrinha.
    """
    corpo = _corpo_do_acompanhamento()
    assert "Hardlyze Agent" in corpo, "a desistência tem de dizer onde olhar"


# ── 5. Máquina desligada = token morto ───────────────────────────────────
#
# O token vale minutos e o comando espera na fila. Quem clica e sai para
# almoçar volta e encontra `failed`, sem explicação. E entre o prazo acabar e a
# máquina acordar, o pedido já está morto enquanto a tela ainda diz
# "aguardando" — afirmando andamento onde não há mais nenhum.


class _FakeTabela:
    """Só o suficiente para `prazo_do_token`: select/eq/limit/execute."""

    def __init__(self, linhas: list[dict]) -> None:
        self._linhas = linhas
        self._filtros: list[tuple[str, Any]] = []

    def select(self, *_a, **_k):
        return self

    def eq(self, campo, valor):
        self._filtros.append((campo, valor))
        return self

    def limit(self, _n):
        return self

    def execute(self):
        casadas = [
            dict(linha)
            for linha in self._linhas
            if all(linha.get(campo) == valor for campo, valor in self._filtros)
        ]

        class _R:
            data = casadas

        return _R()


class _FakeSupabase:
    def __init__(self, linhas: list[dict]) -> None:
        self._linhas = linhas

    def table(self, _nome):
        return _FakeTabela(self._linhas)


@contextmanager
def _com_supabase(fake):
    original = ci._supabase
    ci._supabase = lambda: fake
    try:
        yield
    finally:
        ci._supabase = original


def _corpo_do_acompanhamento() -> str:
    from pathlib import Path

    html = (Path(__file__).resolve().parent.parent / "templates" / "index.html").read_text(
        encoding="utf-8"
    )
    corpo = html[html.index("async function acompanharInstalacao") :]
    return corpo[: corpo.index("\n      }\n")]


@pytest.fixture
def prazo(monkeypatch: pytest.MonkeyPatch):
    """Controla o que `prazo_do_token` devolve, sem ir ao banco."""
    estado: dict[str, Any] = {"valor": None}
    consultas: list[tuple] = []

    def _fake(token_id: str, user_email: str):
        consultas.append((token_id, user_email))
        return estado["valor"]

    monkeypatch.setattr(ci, "prazo_do_token", _fake)
    return {"estado": estado, "consultas": consultas}


def _vencido(consumido: str | None = None) -> dict:
    return {
        "expires_at": "2026-08-24T10:00:00Z",
        "consumed_at": consumido,
        "expirado": True,
    }


def _no_prazo() -> dict:
    return {"expires_at": "2099-01-01T00:00:00Z", "consumed_at": None, "expirado": False}


def test_prazo_vencido_sem_a_maquina_ter_tocado_no_pedido(
    client: TestClient, cadeias, prazo
) -> None:
    """
    O caso exato da máquina desligada: nenhum evento na trilha, prazo vencido.

    Antes isto respondia `aguardando` para sempre — a tela afirmava andamento
    de um pedido que já não existia.
    """
    cadeias["dados"]["cadeias"] = []
    prazo["estado"]["valor"] = _vencido()

    assert _acompanhar(client).json()["desfecho"] == "expirado"


def test_falha_depois_do_prazo_se_chama_expirado(client: TestClient, cadeias, prazo) -> None:
    """
    A máquina acorda tarde, tenta, e o portal recusa o token. A trilha registra
    `falhou` com "Token inválido, expirado ou já utilizado".

    Dizer isso à pessoa manda procurar defeito onde não há: o motivo verdadeiro
    é o prazo, e a ação é ligar a máquina e pedir de novo.
    """
    cadeias["dados"]["cadeias"] = [{
        "token_id": TOKEN_ID, "desfecho": "falhou", "parou_em": "SOLICITADO",
        "eventos": [{"event": "ERRO", "detail": "Token inválido, expirado ou já utilizado"}],
    }]
    prazo["estado"]["valor"] = _vencido()

    assert _acompanhar(client).json()["desfecho"] == "expirado"


def test_instalacao_concluida_nunca_vira_expirada(client: TestClient, cadeias, prazo) -> None:
    """
    O teste que impede a correção de virar defeito.

    O token é consumido no resgate e o prazo passa logo depois — se `expirado`
    ganhasse de `concluido`, a pessoa veria "expirou" com o certificado JÁ
    instalado. Sucesso apresentado como falha é pior do que a falha original:
    manda desfazer o que deu certo.
    """
    cadeias["dados"]["cadeias"] = [
        {"token_id": TOKEN_ID, "desfecho": "concluido", "parou_em": None, "eventos": []}
    ]
    prazo["estado"]["valor"] = _vencido(consumido="2026-08-24T09:59:00Z")

    assert _acompanhar(client).json()["desfecho"] == "concluido"


def test_token_ja_consumido_nao_conta_como_expirado(
    client: TestClient, cadeias, prazo
) -> None:
    """
    Consumido é instalação em curso, não pedido morto: o agente já resgatou e
    está importando. Chamar de expirado cortaria o acompanhamento no meio.
    """
    cadeias["dados"]["cadeias"] = [
        {"token_id": TOKEN_ID, "desfecho": "incompleto", "parou_em": "REDIMIDO", "eventos": []}
    ]
    prazo["estado"]["valor"] = _vencido(consumido="2026-08-24T09:59:00Z")

    assert _acompanhar(client).json()["desfecho"] == "aguardando"


def test_dentro_do_prazo_segue_aguardando(client: TestClient, cadeias, prazo) -> None:
    cadeias["dados"]["cadeias"] = []
    prazo["estado"]["valor"] = _no_prazo()

    assert _acompanhar(client).json()["desfecho"] == "aguardando"


def test_o_prazo_e_consultado_pelo_dono(client: TestClient, cadeias, prazo) -> None:
    """
    Mesmo escopo da trilha. Sem o filtro por e-mail, um id alheio responderia
    sobre o pedido de outra pessoa — quando, para qual máquina.
    """
    _acompanhar(client)
    assert prazo["consultas"] == [(TOKEN_ID, EMAIL)]


def test_a_resposta_carrega_o_prazo_para_a_tela_se_pautar(
    client: TestClient, cadeias, prazo
) -> None:
    """
    Sem isto a tela desistia num número de tentativas escolhido a dedo — 60s,
    menor que a validade do token. Ela dizia "não confirmou" enquanto o pedido
    ainda estava de pé por mais quatro minutos.
    """
    cadeias["dados"]["cadeias"] = []
    prazo["estado"]["valor"] = _no_prazo()

    assert _acompanhar(client).json()["expira_em"] == "2099-01-01T00:00:00Z"


def test_sem_prazo_conhecido_a_resposta_nao_quebra(client: TestClient, cadeias, prazo) -> None:
    """A consulta do prazo pode falhar; ela não pode derrubar o acompanhamento."""
    cadeias["dados"]["cadeias"] = []
    prazo["estado"]["valor"] = None

    d = _acompanhar(client).json()
    assert d["desfecho"] == "aguardando"
    assert d["expira_em"] is None


def test_falha_ao_consultar_a_trilha_ainda_devolve_o_prazo(
    client: TestClient, cadeias, prazo
) -> None:
    """`desconhecido` não pode custar o prazo — é ele que faz a tela parar."""
    def _explode(**_kw):
        raise RuntimeError("banco fora do ar")

    cadeias["monkeypatch"].setattr(ci, "cadeias_de_instalacao", _explode)
    prazo["estado"]["valor"] = _no_prazo()

    d = _acompanhar(client).json()
    assert d["desfecho"] == "desconhecido"
    assert d["expira_em"] == "2099-01-01T00:00:00Z"


# ── 6. A tela se pauta pelo prazo, e não por um número de voltas ─────────


def test_a_tela_espera_ate_o_prazo_e_nao_um_minuto_fixo() -> None:
    """
    O laço tem de terminar no prazo do pedido. Um teto em número de tentativas
    volta a desistir antes da hora assim que alguém mexer no intervalo.
    """
    corpo = _corpo_do_acompanhamento()
    assert "ACOMPANHAR_TENTATIVAS" not in corpo, "voltou a contar tentativas em vez de prazo"
    assert "expira_em" in corpo, "a tela ignora o prazo que o portal manda"
    assert "limite" in corpo


def test_a_tela_tem_desfecho_proprio_para_expirado() -> None:
    """
    "Falhou" mandaria procurar defeito no certificado. Aqui existe algo a
    fazer, e a mensagem tem de dizer o quê.
    """
    corpo = _corpo_do_acompanhamento()
    assert '=== "expirado"' in corpo
    assert "expirou" in corpo.lower()


def test_prazo_do_token_filtra_pelo_dono() -> None:
    """
    O filtro por e-mail é a barreira, e ele mora na consulta — não na rota.

    Aqui a linha existe e o prazo está vencido; se o filtro sumisse, o teste
    passaria a devolver dados de outra pessoa e ninguém notaria pela rota, que
    entrega a mesma resposta de "ainda aguardando" nos dois casos.
    """
    linha = {
        "id": TOKEN_ID,
        "user_email": "dono@x.com",
        "expires_at": "2020-01-01T00:00:00+00:00",
        "consumed_at": None,
    }
    with _com_supabase(_FakeSupabase([linha])):
        assert ci.prazo_do_token(TOKEN_ID, "dono@x.com")["expirado"] is True
        assert ci.prazo_do_token(TOKEN_ID, "OUTRA@x.com") is None


def test_prazo_sem_fuso_e_lido_como_utc() -> None:
    """
    O banco grava em UTC. Uma leitura ingênua compararia contra o relógio local
    e daria o prazo por vencido três horas antes — ou por vencer três horas
    depois, que é o lado que deixa a pessoa esperando por um pedido morto.
    """
    from datetime import datetime, timedelta, timezone

    futuro = (datetime.now(timezone.utc) + timedelta(minutes=5)).replace(tzinfo=None)
    linha = {
        "id": TOKEN_ID,
        "user_email": EMAIL,
        "expires_at": futuro.isoformat(),  # sem sufixo de fuso, como o Postgres devolve
        "consumed_at": None,
    }
    with _com_supabase(_FakeSupabase([linha])):
        assert ci.prazo_do_token(TOKEN_ID, EMAIL)["expirado"] is False


def test_prazo_ilegivel_nao_declara_expirado() -> None:
    """
    Data que não converte vira "não sei", e não "acabou". Declarar expirado por
    não conseguir ler cortaria uma instalação em curso por causa de um defeito
    de formato.
    """
    linha = {"id": TOKEN_ID, "user_email": EMAIL, "expires_at": "ontem", "consumed_at": None}
    with _com_supabase(_FakeSupabase([linha])):
        assert ci.prazo_do_token(TOKEN_ID, EMAIL)["expirado"] is False


def test_a_tela_da_folga_depois_do_prazo() -> None:
    """
    O agente pode resgatar no último segundo e a trilha ainda estar a caminho.
    Desistir exatamente no minuto do prazo chamaria de expirada uma instalação
    que deu certo — o mesmo erro de sinal do teste `nunca_vira_expirada`.
    """
    corpo = _corpo_do_acompanhamento()
    assert "ACOMPANHAR_FOLGA_MS" in corpo
