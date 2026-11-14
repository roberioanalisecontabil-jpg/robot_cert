"""Bandeja 1.3.0: último dono do perfil e conferência de remoção (Frente B).

Spec: docs/superpowers/specs/2026-11-13-carteira-certificados-remocao-uso-design.md,
"Último dono do perfil" e "Perfil sem login na bandeja". Os piores erros aqui
são remover o que o portal não mandou e perder o último dono, o que jogaria o
perfil na regra dos 7 dias sem login.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from estacao import chave_maquina, conferencia, repositorio
from estacao import conta as cc
from estacao.repositorio import Item
from tests.test_estacao import MAQUINA, PORTAL, _Portal, _Resp, estacao, so_windows  # noqa: F401

FP_A, FP_B, FP_C = "a" * 64, "b" * 64, "c" * 64
HOJE = date(2026, 11, 14)


class _Http:
    """O portal da conferência: devolve as respostas na ordem e registra os POSTs."""

    def __init__(self, *respostas: Any) -> None:
        self.respostas = list(respostas)
        self.chamadas: list = []

    def post(self, url: str, json: dict | None = None, headers: dict | None = None, **_k: Any) -> _Resp:
        self.chamadas.append((url, json, dict(headers or {})))
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Repositório de mentira: `itens` é o que o listar devolve; `removidos` registra."""
    estado: dict = {"itens": [Item(FP_A, "A" * 40, "EMPRESA A"), Item(FP_B, "B" * 40, "EMPRESA B")],
                    "removidos": [], "falha": {}}

    def _remover(item: Item) -> tuple[bool, str]:
        estado["removidos"].append(item.sha256)
        erro = estado["falha"].get(item.sha256)
        return (False, erro) if erro else (True, "")

    monkeypatch.setattr(repositorio, "listar", lambda: list(estado["itens"]))
    monkeypatch.setattr(repositorio, "remover", _remover)
    monkeypatch.setattr(chave_maquina, "ler", lambda: "chave-da-maquina")
    conferencia._AVISADO_EM.clear()
    return estado


def _vazia(**extra: Any) -> _Resp:
    return _Resp(200, {"remover": [], "avisos": [], "vencendo": [], "proxima_em": 300, **extra})


def _conferir(http: _Http, avisos: list, pendentes: list | None = None, hoje: date = HOJE) -> list:
    return conferencia.conferir(http, "certguard-1.3.0", avisos.append, hoje, pendentes or [], "aa:bb:cc:dd:ee:99")


# ── Último dono ──────────────────────────────────────────────────────────


@so_windows
def test_401_encerra_e_guarda_ultimo_dono(estacao: list) -> None:
    portal = _Portal()
    cc.registrar(portal, PORTAL, "ana@x.com", "certa", MAQUINA)
    portal.encerrada = True
    with pytest.raises(cc.SessaoEncerrada):
        cc.situacao(portal)
    assert cc.ler() is None and not cc.esta_conectado()
    dono = cc.ultimo_dono()
    assert dono and dono["segredo"] == "seg-123" and dono["portal"] == PORTAL
    assert dono["email"] == "ana@x.com" and dono["machine_id"] == MAQUINA
    with pytest.raises(cc.NaoConectado):
        cc.cabecalhos()


@so_windows
def test_403_tambem_encerra(estacao: list) -> None:
    cc.guardar("seg-1", PORTAL, "ana@x.com", MAQUINA)

    class _Proibido:
        def get(self, *_a: Any, **_k: Any) -> _Resp:
            return _Resp(403, {"detail": "Dispositivo revogado."})

    with pytest.raises(cc.SessaoEncerrada):
        cc.instalacoes_pendentes(_Proibido())
    assert not cc.esta_conectado() and cc.ultimo_dono()["segredo"] == "seg-1"


@so_windows
def test_login_novo_substitui_ultimo_dono(estacao: list) -> None:
    cc.guardar("seg-velho", PORTAL, "ana@x.com", MAQUINA)
    cc.encerrar()
    assert cc.ultimo_dono()["segredo"] == "seg-velho"
    cc.guardar("seg-novo", PORTAL, "bia@x.com", MAQUINA)
    assert cc.ultimo_dono() is None, "conta ativa não é último dono"
    assert cc.ler()["segredo"] == "seg-novo" and cc.ler()["email"] == "bia@x.com"


@so_windows
def test_sair_vira_ultimo_dono(estacao: list) -> None:
    portal = _Portal()
    cc.registrar(portal, PORTAL, "ana@x.com", "certa", MAQUINA)
    cc.sair(portal)
    assert portal.chamadas[-1][1].endswith("/api/estacao/sair")
    assert not cc.esta_conectado() and cc.caminho().is_file()
    assert cc.ultimo_dono()["segredo"] == "seg-123"


# ── Conferência ──────────────────────────────────────────────────────────


@so_windows
def test_conectado_usa_rota_logada(estacao: list, repo: dict) -> None:
    cc.guardar("seg-1", PORTAL, "ana@x.com", MAQUINA)
    http = _Http(_vazia())
    assert _conferir(http, []) == []
    url, corpo, cab = http.chamadas[0]
    assert url == PORTAL + "/api/estacao/conferencia"
    assert cab["X-Device-Secret"] == "seg-1" and cab["X-Agent-Version"] == "certguard-1.3.0"
    assert sorted(corpo["certificados"]) == [FP_A, FP_B]
    assert "\\" in corpo["usuario_windows"]
    assert not {"segredo", "chave", "machine_id"} & set(corpo)


@so_windows
def test_ultimo_dono_manda_segredo_e_chave(estacao: list, repo: dict) -> None:
    cc.guardar("seg-1", "https://outro.portal", "ana@x.com", MAQUINA)
    cc.encerrar()
    http = _Http(_vazia())
    _conferir(http, [])
    url, corpo, cab = http.chamadas[0]
    assert url == "https://outro.portal/api/estacao/conferencia/sem-conta"
    assert corpo["segredo"] == "seg-1" and corpo["chave"] == "chave-da-maquina"
    assert corpo["machine_id"] == MAQUINA, "o do último dono, não o calculado agora"
    assert "X-Device-Secret" not in cab


@so_windows
def test_sem_conta_nem_dono_manda_so_chave(estacao: list, repo: dict) -> None:
    http = _Http(_vazia(avisos=[
        {"fingerprint": FP_A, "documento": "1", "motivo": "perfil sem login na bandeja", "dias": 5, "nome": "A"},
        {"fingerprint": FP_B, "documento": "2", "motivo": "perfil sem login na bandeja", "dias": 7, "nome": "B"},
    ]))
    avisos: list = []
    _conferir(http, avisos)
    url, corpo, _cab = http.chamadas[0]
    assert url == PORTAL + "/api/estacao/conferencia/sem-conta"
    assert corpo["machine_id"] == "aa:bb:cc:dd:ee:99" and corpo["chave"] == "chave-da-maquina"
    assert "segredo" not in corpo or corpo["segredo"] is None
    assert avisos == ["Entre na bandeja do CertGuard. Sem login, os certificados da empresa "
                      "serão retirados deste computador em 7 dias."]


@so_windows
def test_so_remove_o_que_informou_e_ainda_existe(estacao: list, repo: dict) -> None:
    cc.guardar("seg-1", PORTAL, "ana@x.com", MAQUINA)
    http = _Http(_vazia(remover=[
        {"fingerprint": FP_A.upper(), "documento": "1", "motivo": "fora da carteira", "nome": "EMPRESA A"},
        {"fingerprint": FP_C, "documento": "3", "motivo": "fora da carteira", "nome": "EMPRESA C"},
    ]))
    avisos: list = []
    resultados = _conferir(http, avisos)
    assert repo["removidos"] == [FP_A], "FP_C não está no repositório: ignorado"
    assert resultados == [{"fingerprint": FP_A, "ok": True, "erro": ""}]
    assert avisos == ["Certificado EMPRESA A removido: saiu da sua carteira."]


@so_windows
def test_remocao_sem_conta_diz_como_pedir_de_novo(estacao: list, repo: dict) -> None:
    cc.guardar("seg-1", PORTAL, "ana@x.com", MAQUINA)
    cc.encerrar()
    http = _Http(_vazia(remover=[{"fingerprint": FP_B, "documento": "2", "motivo": "x", "nome": "EMPRESA B"}]))
    avisos: list = []
    _conferir(http, avisos)
    assert avisos == ["Certificado EMPRESA B removido: saiu da sua carteira. "
                      "Entre na bandeja e peça de novo no portal, se precisar."]


@so_windows
@pytest.mark.parametrize("resposta", [_Resp(503, {"detail": "fora"}), _Resp(403, {"detail": "chave"}),
                                      _Resp(429, {}), OSError("sem rede")])
def test_portal_fora_nao_remove_e_guarda_pendentes(estacao: list, repo: dict, resposta: Any) -> None:
    cc.guardar("seg-1", PORTAL, "ana@x.com", MAQUINA)
    cc.encerrar()
    pendentes = [{"fingerprint": FP_C, "ok": True, "erro": ""}]
    avisos: list = []
    assert _conferir(_Http(resposta), avisos, pendentes) == pendentes
    assert repo["removidos"] == [] and avisos == []
    assert cc.ultimo_dono()["segredo"] == "seg-1", "403 do sem-conta não mexe na conta"


@so_windows
def test_repositorio_ilegivel_pula_a_rodada(estacao: list, repo: dict) -> None:
    cc.guardar("seg-1", PORTAL, "ana@x.com", MAQUINA)
    repo["itens"] = []
    http = _Http()
    pendentes = [{"fingerprint": FP_C, "ok": False, "erro": "x"}]
    assert _conferir(http, [], pendentes) == pendentes
    assert http.chamadas == [], "lista vazia faria o portal limpar as pendências"


@so_windows
def test_resultado_vai_na_proxima_rodada(estacao: list, repo: dict) -> None:
    cc.guardar("seg-1", PORTAL, "ana@x.com", MAQUINA)
    repo["falha"][FP_B] = "Acesso negado"
    remover = [{"fingerprint": f, "documento": "1", "motivo": "x", "nome": "N"} for f in (FP_A, FP_B)]
    http = _Http(_vazia(remover=remover), _vazia())
    avisos: list = []
    primeira = _conferir(http, avisos)
    assert primeira == [{"fingerprint": FP_A, "ok": True, "erro": ""},
                        {"fingerprint": FP_B, "ok": False, "erro": "Acesso negado"}]
    assert len(avisos) == 1, "só avisa o que deu certo"
    assert http.chamadas[0][1]["resultados"] == []
    assert _conferir(http, avisos, primeira) == []
    assert http.chamadas[1][1]["resultados"] == primeira


@so_windows
def test_aviso_de_vencimento_uma_vez_por_dia(estacao: list, repo: dict) -> None:
    cc.guardar("seg-1", PORTAL, "ana@x.com", MAQUINA)
    vence = _vazia(vencendo=[{"documento": "123", "vence_em": "2026-11-17", "nome": "EMPRESA X"}])
    http = _Http(vence, vence, vence)
    avisos: list = []
    _conferir(http, avisos)
    _conferir(http, avisos)
    assert avisos == ["O acesso ao certificado EMPRESA X vence em 3 dias. Fale com seu gestor."]
    _conferir(http, avisos, hoje=date(2026, 11, 15))
    assert avisos[-1] == "O acesso ao certificado EMPRESA X vence em 2 dias. Fale com seu gestor."


@so_windows
def test_outros_avisos_dizem_motivo_e_dias(estacao: list, repo: dict) -> None:
    cc.guardar("seg-1", PORTAL, "ana@x.com", MAQUINA)
    http = _Http(_vazia(avisos=[{"fingerprint": FP_A, "documento": "1", "motivo": "vínculo recusado",
                                 "dias": 4, "nome": "EMPRESA A"}]))
    avisos: list = []
    _conferir(http, avisos)
    assert len(avisos) == 1 and "EMPRESA A" in avisos[0] and "vínculo recusado" in avisos[0]
    assert "4 dias" in avisos[0]


def test_versao_1_3_0() -> None:
    from estacao import VERSAO, VERSAO_REPORTADA

    assert VERSAO == "1.3.0" and VERSAO_REPORTADA == "certguard-1.3.0"


# ── Laço da bandeja ──────────────────────────────────────────────────────


def test_laco_confere_na_partida_e_a_cada_300_s(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from estacao import bandeja

    relogio = {"t": 1000.0}
    feitas: list = []
    b = bandeja.Bandeja(tmp_path / "x.log")
    monkeypatch.setattr(bandeja.time, "monotonic", lambda: relogio["t"])
    monkeypatch.setattr(b, "verificar", lambda: feitas.append("verificar"))
    monkeypatch.setattr(conferencia, "conferir", lambda *a: feitas.append("conferir") or [])
    monkeypatch.setattr(b, "_machine_id", lambda: MAQUINA)

    def _esperar(segundos: float) -> bool:
        relogio["t"] += segundos
        if relogio["t"] >= 1000.0 + 20 * 16:
            b._parar.set()
        return b._parar.is_set()

    monkeypatch.setattr(b._parar, "wait", _esperar)
    b.laco()
    assert feitas.count("verificar") == 16, "instalações seguem a cada 20 s"
    assert feitas.count("conferir") == 2 and feitas[:2] == ["verificar", "conferir"]


def test_conferir_ocupado_nao_roda_de_novo(tmp_path) -> None:
    from estacao import bandeja

    b = bandeja.Bandeja(tmp_path / "x.log")
    b._conferindo.acquire()
    b.conferir()
    assert b._ultima_conferencia is None
