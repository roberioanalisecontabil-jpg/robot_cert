"""CertGuard Análise (estacao/): a bandeja de certificados separada do Hardlyze.

Adendo de 14/10/2026 ao ADR 0003. Os testes da conta, da chave e das janelas
vieram do Hardlyze junto com o código. Os da transição (trazer a chave e a conta
do Hardlyze) saíram com ela em 20/11/2026; fica um que prova que as pastas
`InventAgent` não são mais lidas.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from estacao import VERSAO_REPORTADA
from estacao import chave_maquina as ch
from estacao import conta as cc
from estacao.dpapi import proteger
from estacao.janela_login import mensagem_de_falha, validar_campos
from estacao.janela_status import acoes_do_log, montar_estado

PORTAL = "https://certificado.analisegroup.cnt.br"
MAQUINA = "aa:bb:cc:dd:ee:01"

so_windows = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI só no Windows.")


@pytest.fixture
def estacao(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list:
    """ProgramData e perfil de mentira; o icacls é registrado em vez de rodar,
    com o tamanho do arquivo (ou -1, pasta) no instante em que rodaria."""
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "pd"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "perfil"))
    acl: list = []

    def _icacls(alvo: Path, *concessoes: str) -> None:
        alvo = Path(alvo)
        acl.append((alvo.name, alvo.stat().st_size if alvo.is_file() else -1, concessoes))

    monkeypatch.setattr(ch, "_icacls", _icacls)
    return acl


class _Resp:
    def __init__(self, status: int, corpo: Any = None) -> None:
        self.status_code = status
        self._corpo = corpo if corpo is not None else {}
        self.text = json.dumps(self._corpo)

    def json(self) -> Any:
        return self._corpo


class _Portal:
    """O portal, simulado: registra e responde às rotas da estação."""

    def __init__(self) -> None:
        self.chamadas: list = []
        self.autorizacao = "pendente"
        self.tokens: list = []
        self.encerrada = False

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def post(self, url: str, json: dict | None = None, headers: dict | None = None, **_k: Any) -> _Resp:
        self.chamadas.append(("POST", url, json, dict(headers or {})))
        if url.endswith("/api/agent/dispositivos/registrar"):
            if json["password"] != "certa":
                return _Resp(401, {"detail": "E-mail ou senha incorretos."})
            return _Resp(200, {
                "segredo": "seg-123", "email": json["email"], "machine_id": json["machine_id"],
                "autorizacao": "pendente", "mensagem": "Aguardando o administrador autorizar este computador.",
            })
        if url.endswith("/api/estacao/sair"):
            return _Resp(200, {"ok": True})
        return _Resp(404)

    def get(self, url: str, headers: dict | None = None, **_k: Any) -> _Resp:
        self.chamadas.append(("GET", url, None, dict(headers or {})))
        if self.encerrada:
            return _Resp(401, {"detail": "Sessão da bandeja encerrada. Entre de novo."})
        if url.endswith("/api/estacao/situacao"):
            return _Resp(200, {"autorizacao": self.autorizacao})
        if url.endswith("/api/estacao/instalacoes"):
            t, self.tokens = self.tokens, []
            return _Resp(200, {"tokens": t})
        return _Resp(404)


# ── Conta (veio do Hardlyze) ─────────────────────────────────────────────


@so_windows
def test_login_guarda_o_segredo_cifrado_e_nao_a_senha(estacao: list) -> None:
    portal = _Portal()
    r = cc.registrar(portal, PORTAL + "/", "Ana@X.com", "certa", MAQUINA, nome="PC-ANA")
    assert r["autorizacao"] == "pendente" and "administrador" in r["mensagem"]
    bruto = cc.caminho().read_bytes()
    assert b"seg-123" not in bruto and b"certa" not in bruto, "nada em claro no disco"
    assert cc.ler()["portal"] == PORTAL and cc.ler()["email"] == "ana@x.com"
    assert cc.cabecalhos(VERSAO_REPORTADA) == {
        "Content-Type": "application/json", "X-Device-Secret": "seg-123", "X-Agent-Version": VERSAO_REPORTADA,
    }
    assert "CertguardAnalise" in str(cc.caminho())


@so_windows
def test_senha_errada_nao_grava_nada(estacao: list) -> None:
    with pytest.raises(RuntimeError, match="incorretos"):
        cc.registrar(_Portal(), PORTAL, "ana@x.com", "errada", MAQUINA)
    assert not cc.esta_conectado()


@so_windows
def test_situacao_instalacoes_e_sessao_encerrada(estacao: list) -> None:
    portal = _Portal()
    cc.registrar(portal, PORTAL, "ana@x.com", "certa", MAQUINA)
    assert cc.situacao(portal)["autorizacao"] == "pendente"
    portal.autorizacao, portal.tokens = "autorizado", ["tok-1"]
    assert cc.instalacoes_pendentes(portal) == ["tok-1"]
    assert cc.instalacoes_pendentes(portal) == []
    assert all(c[3].get("X-Device-Secret") == "seg-123" for c in portal.chamadas if c[0] == "GET")
    portal.encerrada = True
    with pytest.raises(cc.SessaoEncerrada):
        cc.situacao(portal)
    assert not cc.esta_conectado(), "o portal derrubou: a credencial deixa de valer"
    assert cc.ultimo_dono()["segredo"] == "seg-123", "mas fica como último dono do perfil"


@so_windows
def test_sair_avisa_o_portal_e_encerra(estacao: list) -> None:
    portal = _Portal()
    cc.registrar(portal, PORTAL, "ana@x.com", "certa", MAQUINA)
    cc.sair(portal)
    assert not cc.esta_conectado()
    assert cc.ultimo_dono()["email"] == "ana@x.com"
    assert portal.chamadas[-1][1].endswith("/api/estacao/sair")
    with pytest.raises(cc.NaoConectado):
        cc.cabecalhos()


def test_resgate_leva_a_credencial_da_bandeja() -> None:
    from estacao import instalador_certificado

    enviados = []

    class _Http:
        def post(self, url, json=None, headers=None, timeout=None):
            enviados.append((url, dict(headers or {})))
            return _Resp(403, {"detail": "Token inválido, expirado ou já utilizado"})

    with pytest.raises(RuntimeError, match="Token"):
        instalador_certificado.instalar("tok-1", portal=PORTAL, sessao=_Http(),
                                        cabecalhos={"X-Device-Secret": "seg-123"})
    assert enviados[0][0].endswith("/api/cert-installer/claim")
    assert enviados[0][1]["X-Device-Secret"] == "seg-123"


def test_resgate_sem_portal_nao_tenta_host_nenhum() -> None:
    from estacao import instalador_certificado

    with pytest.raises(instalador_certificado.InstalacaoIndisponivel):
        instalador_certificado.instalar("tok-1", portal="", sessao=object())


# ── Chave da máquina: o instalador prepara ───────────────────────────────


@so_windows
def test_sem_chave_antiga_gera_uma_e_nao_troca_na_reinstalacao(estacao: list) -> None:
    assert ch.ler() is None
    assert ch.preparar() == "gerada"
    chave = ch.ler()
    assert chave and len(chave) >= 43
    assert chave.encode() not in ch.caminho().read_bytes(), "cifrada no disco"
    assert ch.preparar() == "existente" and ch.ler() == chave, "reinstalar não troca a chave"


@so_windows
def test_conteudo_nasce_em_pasta_restrita_e_usuarios_so_leem(estacao: list) -> None:
    ch.preparar()
    (pasta, tam_pasta, conc_pasta), (arquivo, tam, conc) = estacao
    assert tam_pasta == -1 and conc_pasta == ("*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"), \
        "a pasta temporária é restrita ANTES de o conteúdo existir"
    assert arquivo == ch.ARQUIVO and tam > 0
    assert conc == ("*S-1-5-18:F", "*S-1-5-32-544:F", "*S-1-5-32-545:R")
    assert [p.name for p in ch.caminho().parent.iterdir()] == [ch.ARQUIVO], "a pasta temporária some"


@so_windows
def test_arquivo_estranho_no_lugar_da_chave_e_substituido(estacao: list) -> None:
    ch.caminho().parent.mkdir(parents=True)
    ch.caminho().write_bytes(b"plantado")
    assert ch.preparar() == "gerada" and ch.ler()


@so_windows
def test_login_manda_a_chave_quando_ha(estacao: list) -> None:
    ch.preparar()
    portal = _Portal()
    cc.registrar(portal, PORTAL, "ana@x.com", "certa", MAQUINA, chave_maquina=ch.ler())
    assert portal.chamadas[0][2]["chave_maquina"] == ch.ler()
    portal2 = _Portal()
    cc.registrar(portal2, PORTAL, "ana@x.com", "certa", MAQUINA, chave_maquina=None)
    assert "chave_maquina" not in portal2.chamadas[0][2]


# ── Sem transição: o Hardlyze não é mais lido (retirada em 20/11/2026) ───


@so_windows
def test_chave_e_conta_do_hardlyze_nao_sao_mais_lidas(estacao: list, tmp_path: Path) -> None:
    """Uma chave e uma conta válidas do Hardlyze, nos lugares de antes: a chave
    é gerada nova, a bandeja não entra com a conta antiga, e nada é apagado."""
    chave_antiga = tmp_path / "pd" / "InventAgent" / "chave_certificados.dat"
    chave_antiga.parent.mkdir(parents=True)
    chave_antiga.write_bytes(proteger(b"chave-do-hardlyze-" + b"x" * 30, b"invent-agent-chave-certificados-v1",
                                      maquina=True))
    conta_antiga = tmp_path / "perfil" / "InventAgent" / "certificados.dat"
    conta_antiga.parent.mkdir(parents=True)
    dados = {"segredo": "seg-antigo", "portal": PORTAL, "email": "ana@x.com", "machine_id": MAQUINA}
    conta_antiga.write_bytes(proteger(json.dumps(dados).encode(), b"invent-agent-dispositivo-v1"))

    assert ch.preparar() == "gerada"
    assert ch.ler() != "chave-do-hardlyze-" + "x" * 30
    assert not cc.esta_conectado()
    assert chave_antiga.exists() and conta_antiga.exists()


# ── Bandeja ──────────────────────────────────────────────────────────────


def test_machine_id_e_o_mesmo_calculo_do_hardlyze(monkeypatch: pytest.MonkeyPatch) -> None:
    """Primeiro MAC em ordem alfabética, sem o nulo. Outro cálculo faria todo
    computador autorizado virar equipamento novo.

    Desde a 1.5.3 o cálculo é o `mac_calculado`; `bandeja.machine_id()` lê
    antes o machine_id.txt da máquina (test_estacao_identidade), e numa
    estação com a 1.5.3 instalada este teste lia o arquivo real."""
    import psutil

    from estacao import identidade

    def _end(mac, fam=psutil.AF_LINK):
        return SimpleNamespace(family=fam, address=mac)

    monkeypatch.setattr(psutil, "net_if_addrs", lambda: {
        "Ethernet": [_end("BC-24-11-AA-00-02"), _end("10.0.0.5", fam=2)],
        "VPN": [_end("00-FF-12-34-56-78")],
        "Loopback": [_end("00-00-00-00-00-00")],
    })
    assert identidade.mac_calculado() == "00:ff:12:34:56:78"
    monkeypatch.setattr(psutil, "net_if_addrs", lambda: {})
    assert identidade.mac_calculado() == "unknown"


@so_windows
def test_bandeja_autorizada_instala_o_que_o_portal_mandar(estacao: list, monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from estacao import bandeja, instalador_certificado

    portal = _Portal()
    cc.registrar(portal, PORTAL, "ana@x.com", "certa", MAQUINA)
    portal.autorizacao, portal.tokens = "autorizado", ["tok-1"]
    monkeypatch.setattr(httpx, "Client", lambda: portal)
    instalados = []
    monkeypatch.setattr(instalador_certificado, "instalar", lambda token, portal, cabecalhos: (
        instalados.append((token, portal, cabecalhos)) or [{"status": "OK"}]))

    b = bandeja.Bandeja(Path("x.log"))
    b.verificar()
    assert "autorizado" in b.texto and "ana@x.com" in b.texto
    assert instalados == [("tok-1", PORTAL, cc.cabecalhos(VERSAO_REPORTADA))]
    assert all(c[3].get("X-Agent-Version") == VERSAO_REPORTADA for c in portal.chamadas if c[0] == "GET")


@so_windows
def test_bandeja_pendente_nao_busca_instalacao(estacao: list, monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from estacao import bandeja

    portal = _Portal()
    cc.registrar(portal, PORTAL, "ana@x.com", "certa", MAQUINA)
    monkeypatch.setattr(httpx, "Client", lambda: portal)
    b = bandeja.Bandeja(Path("x.log"))
    b.verificar()
    assert "aguardando" in b.texto
    assert not any(c[1].endswith("/instalacoes") for c in portal.chamadas)


# ── Janelas: a parte que decide, sem Tk ──────────────────────────────────


LOG = """2026-10-14 10:00:01,100 - INFO - CertGuard Análise certguard-1.0.0 iniciado.
2026-10-14 10:00:02,200 - WARNING - Portal de certificados indisponível agora: timeout
2026-10-14 10:02:09,500 - INFO - Instalação pelo portal de certificados: 1 ok, 0 falha(s).
2026-10-14 10:03:10,600 - ERROR - Falha ao instalar certificado vindo do portal
    File "C:\\algo\\continuacao_de_traceback.py", line 12, in coisa
"""


def test_status_destaca_a_instalacao_e_ignora_traceback(tmp_path: Path) -> None:
    acoes = acoes_do_log(LOG)
    assert any(a["destaque"] and "1 ok" in a["mensagem"] for a in acoes)
    assert not any("continuacao_de_traceback" in a["mensagem"] for a in acoes)
    assert acoes[-1]["nivel"] == "ERROR"
    log = tmp_path / "bandeja.log"
    log.write_text(LOG, encoding="utf-8")
    e = montar_estado(log, PORTAL, VERSAO_REPORTADA, {"email": "ana@x.com", "machine_id": MAQUINA})
    assert e.logado and e.email == "ana@x.com" and e.maquina == MAQUINA and e.acoes
    assert montar_estado(tmp_path / "nao-existe.log", PORTAL, "v", None).acoes == []


def test_login_valida_so_o_grosseiro_e_traduz_a_falha() -> None:
    assert validar_campos("ana@x.com", "a") is None
    assert "e-mail" in validar_campos("", "a").lower()
    assert "senha" in validar_campos("ana@x.com", "").lower()
    assert mensagem_de_falha(RuntimeError("E-mail ou senha incorretos.")) == "E-mail ou senha incorretos."
    assert "rede" in mensagem_de_falha(RuntimeError("ConnectTimeout")).lower()
