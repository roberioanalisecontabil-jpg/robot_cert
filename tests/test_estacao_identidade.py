"""O `machine_id` fixado pela chave da máquina (plano 2026-11-20-identidade-pela-chave,
Task 2). Na TI-002, em 20/11/2026, o adaptador do WSL (00:15:5d:6d:93:6f) passou à frente
do MAC que o portal conhecia (00:ff:fd:03:61:24) e a coleta levou 403."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from estacao import bandeja, caminhos, chave_maquina, identidade

CONHECIDO = "00:ff:fd:03:61:24"
WSL = "00:15:5d:6d:93:6f"
PLANTADO = "aa:aa:aa:aa:aa:aa"


class _Http:
    def __init__(self, status: int = 200, machine_id: str = CONHECIDO, erro: Exception | None = None) -> None:
        self.status, self.machine_id, self.erro, self.posts = status, machine_id, erro, []

    def post(self, url: str, json: dict | None = None, **_k) -> SimpleNamespace:
        self.posts.append((url, json))
        if self.erro:
            raise self.erro
        return SimpleNamespace(status_code=self.status, json=lambda: {"machine_id": self.machine_id})


_ACLS: list = []  # (nome, concessões) de cada icacls, pela fixture
_FIXAR = identidade.fixar  # o real: o conftest o troca em todos os outros testes


@pytest.fixture(autouse=True)
def maquina(tmp_path, monkeypatch):
    monkeypatch.setattr(identidade, "fixar", _FIXAR)
    monkeypatch.setattr(caminhos, "pasta_maquina", lambda: tmp_path)
    monkeypatch.setattr(chave_maquina, "ler", lambda: "k" * 43)
    monkeypatch.setattr(identidade, "mac_calculado", lambda: WSL)
    monkeypatch.setattr(chave_maquina, "_icacls", lambda alvo, *c: _ACLS.append((alvo.name, c)))
    _ACLS.clear()
    return tmp_path


def _gravar(pasta, texto: str) -> None:
    (pasta / identidade.ARQUIVO).write_text(texto, encoding="utf-8")


def _lido(pasta) -> str:
    return (pasta / identidade.ARQUIVO).read_text(encoding="utf-8").strip()


def test_portal_vence_o_arquivo(maquina) -> None:
    _gravar(maquina, PLANTADO)  # plantado por quem não é administrador, ou de antes
    http = _Http()
    assert identidade.fixar(http) == CONHECIDO == identidade.machine_id() == _lido(maquina)
    url, corpo = http.posts[0]
    assert url.endswith("/api/estacao/identidade") and corpo == {"chave": "k" * 43}


def test_404_mantem_o_arquivo(maquina) -> None:
    _gravar(maquina, PLANTADO)
    assert identidade.fixar(_Http(404)) == PLANTADO == _lido(maquina)


def test_404_sem_arquivo_grava_o_mac(maquina) -> None:
    assert identidade.fixar(_Http(404)) == WSL == _lido(maquina)


def test_portal_fora_mantem_o_arquivo(maquina) -> None:
    _gravar(maquina, PLANTADO)
    assert identidade.fixar(_Http(erro=httpx.ConnectError("fora"))) == PLANTADO == _lido(maquina)


def test_portal_fora_sem_arquivo_grava_o_mac(maquina) -> None:
    assert identidade.fixar(_Http(erro=httpx.ConnectError("fora"))) == WSL == _lido(maquina)


def test_resposta_fora_do_formato_vale_como_portal_fora(maquina) -> None:
    _gravar(maquina, PLANTADO)
    assert identidade.fixar(_Http(machine_id="../../x")) == PLANTADO == _lido(maquina)
    assert identidade.fixar(_Http(503)) == PLANTADO


def test_sem_chave_nao_pergunta_ao_portal(maquina, monkeypatch) -> None:
    monkeypatch.setattr(chave_maquina, "ler", lambda: None)
    http = _Http()
    assert identidade.fixar(http) == WSL and http.posts == []


@pytest.mark.parametrize("texto", ["", "lixo", "00-FF-FD-03-61-24", "00:ff:fd:03:61"])
def test_arquivo_invalido_cai_no_mac(maquina, texto) -> None:
    _gravar(maquina, texto)
    assert identidade.machine_id() == WSL


def test_arquivo_com_quebra_de_linha_vale(maquina) -> None:
    _gravar(maquina, CONHECIDO + "\r\n")
    assert identidade.machine_id() == CONHECIDO


def test_bandeja_usa_a_identidade(maquina) -> None:
    _gravar(maquina, CONHECIDO)
    assert bandeja.machine_id() == CONHECIDO


def test_temporario_plantado_nao_impede_a_gravacao(maquina) -> None:
    """Revisão de 20/11: o SYSTEM gravava por `machine_id.txt.novo`, nome que
    qualquer usuário cria antes em ProgramData (pasta ou link simbólico)."""
    (maquina / (identidade.ARQUIVO + ".novo")).mkdir()
    assert identidade.fixar(_Http()) == CONHECIDO == _lido(maquina)


def test_arquivo_gravado_so_o_system_e_admin_alteram(maquina) -> None:
    identidade.fixar(_Http())
    finais = [c for nome, c in _ACLS if nome == identidade.ARQUIVO]
    assert finais == [("*S-1-5-18:F", "*S-1-5-32-544:F", "*S-1-5-32-545:R")]


def test_sem_mac_nao_grava_unknown(maquina, monkeypatch) -> None:
    """Sem rede no boot o cálculo dá "unknown": gravar isso regravava o arquivo
    a cada rodada (a leitura o ignora). Fica sem arquivo até haver um MAC."""
    monkeypatch.setattr(identidade, "mac_calculado", lambda: "unknown")
    assert identidade.fixar(_Http(404)) == "unknown"
    assert not (maquina / identidade.ARQUIVO).exists()
