"""
A credencial do agente na estação.

O que estes testes guardam, e por que cada um importa:

  * o segredo **nunca** toca o disco em claro — e a recusa em degradar é
    testada, não só documentada
  * a senha do portal não sobrevive ao registro
  * revogação no portal apaga o arquivo local, em vez de o agente tentar para
    sempre com um segredo que já não vale
  * o token vive em memória e renova sozinho antes de expirar

O primeiro é o que não dá sintoma se cair: gravar em texto puro mantém tudo
funcionando e some com a garantia inteira.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from agent import identidade

SEGREDO = "segredo-de-dispositivo-com-entropia-suficiente-xyz"
BASE = "https://portal.exemplo"
EMAIL = "ana@x.com"
MAQUINA = "ESTACAO-ANA"

pytestmark = pytest.mark.skipif(
    not identidade.dpapi_disponivel(),
    reason="A credencial do agente usa DPAPI; só existe no Windows.",
)


@pytest.fixture
def perfil(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Perfil de usuário isolado, para não tocar no do desenvolvedor."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path


# ──────────────────────────────────────────────────────────────────────────
# Respostas HTTP falsas
# ──────────────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, status: int, corpo: Optional[Dict[str, Any]] = None) -> None:
        self.status_code = status
        self._corpo = corpo or {}
        self.text = json.dumps(self._corpo)

    def json(self) -> Dict[str, Any]:
        return self._corpo


class _Client:
    """httpx.Client falso: guarda o que foi enviado e devolve o que mandarem."""

    def __init__(self, respostas: Dict[str, Any]) -> None:
        self._respostas = respostas
        self.enviados: list = []

    def post(self, url: str, json: Optional[Dict[str, Any]] = None, **_k: Any) -> _Resp:
        self.enviados.append({"url": url, "json": json})
        for sufixo, resp in self._respostas.items():
            if url.endswith(sufixo):
                return resp(self) if callable(resp) else resp
        raise AssertionError(f"URL inesperada no teste: {url}")


def _client_de_registro(status: int = 200) -> _Client:
    return _Client({
        "/api/agent/dispositivos/registrar": _Resp(
            status,
            {"segredo": SEGREDO, "email": EMAIL, "role": "user",
             "machine_id": MAQUINA, "validade_token_min": 60}
            if status == 200
            else {"detail": "E-mail ou senha incorretos."},
        )
    })


# ──────────────────────────────────────────────────────────────────────────
# 1. O segredo não toca o disco em claro
# ──────────────────────────────────────────────────────────────────────────

def test_o_arquivo_gravado_nao_contem_o_segredo(perfil: Path) -> None:
    """
    O teste que não dá sintoma se cair. Se alguém trocar DPAPI por json.dump
    "para simplificar", tudo continua funcionando e a garantia some.
    """
    destino = identidade.guardar(SEGREDO, BASE, EMAIL, MAQUINA)
    cru = destino.read_bytes()

    assert SEGREDO.encode("utf-8") not in cru
    assert EMAIL.encode("utf-8") not in cru
    # E não é só o segredo: o blob inteiro é opaco.
    assert b"machine_id" not in cru


def test_o_que_foi_guardado_volta_inteiro(perfil: Path) -> None:
    identidade.guardar(SEGREDO, BASE + "/", EMAIL.upper(), MAQUINA)
    lido = identidade.ler()

    assert lido is not None
    assert lido["segredo"] == SEGREDO
    assert lido["email"] == EMAIL          # normalizado
    assert lido["base_url"] == BASE        # sem a barra final
    assert lido["machine_id"] == MAQUINA


def test_blob_corrompido_pede_registro_em_vez_de_estourar(perfil: Path) -> None:
    """
    Perfil restaurado ou máquina trocada: o blob existe e não decifra. O caminho
    dali é a janela de login, não um traceback no agent.log.
    """
    destino = identidade.guardar(SEGREDO, BASE, EMAIL, MAQUINA)
    destino.write_bytes(b"isto nao e um blob dpapi valido")

    assert identidade.ler() is None
    assert identidade.esta_registrado() is False


def test_sem_dpapi_recusa_gravar(perfil: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A recusa em degradar, testada. Sem cofre, não grava — levanta."""
    monkeypatch.setattr(identidade, "dpapi_disponivel", lambda: False)

    with pytest.raises(identidade.SemCofreLocal):
        identidade.guardar(SEGREDO, BASE, EMAIL, MAQUINA)

    assert not identidade.caminho().is_file()


def test_fica_no_perfil_do_usuario(perfil: Path) -> None:
    """
    O segredo É a pessoa: em ProgramData, qualquer conta local teria o poder
    dela no portal. E é no perfil que a fase 2 vai precisar dele.
    """
    destino = identidade.guardar(SEGREDO, BASE, EMAIL, MAQUINA)
    assert str(perfil) in str(destino)


# ──────────────────────────────────────────────────────────────────────────
# 2. Registro
# ──────────────────────────────────────────────────────────────────────────

def test_a_senha_nao_sobrevive_ao_registro(perfil: Path) -> None:
    client = _client_de_registro()
    identidade.registrar(client, BASE, EMAIL, "senha-do-portal-123", MAQUINA)

    # Foi enviada uma vez, ao portal...
    assert client.enviados[0]["json"]["password"] == "senha-do-portal-123"
    # ...e não ficou no disco.
    assert b"senha-do-portal-123" not in identidade.caminho().read_bytes()
    assert identidade.ler()["segredo"] == SEGREDO


def test_registrar_nao_devolve_o_segredo(perfil: Path) -> None:
    """Devolvê-lo convidaria a chamada seguinte a guardá-lo num segundo lugar."""
    out = identidade.registrar(_client_de_registro(), BASE, EMAIL, "x", MAQUINA)
    assert "segredo" not in out
    assert out["machine_id"] == MAQUINA


def test_registro_recusado_propaga_o_motivo(perfil: Path) -> None:
    with pytest.raises(RuntimeError, match="E-mail ou senha incorretos"):
        identidade.registrar(_client_de_registro(401), BASE, EMAIL, "errada", MAQUINA)
    assert identidade.esta_registrado() is False


# ──────────────────────────────────────────────────────────────────────────
# 3. Sessão: o token vive em memória
# ──────────────────────────────────────────────────────────────────────────

def _client_de_token(status: int = 200, validade_min: int = 60) -> _Client:
    return _Client({
        "/api/agent/dispositivos/token": _Resp(
            status,
            {"access_token": "jwt-abc", "role": "user", "machine_id": MAQUINA,
             "validade_token_min": validade_min}
            if status == 200
            else {"detail": "Dispositivo não autorizado."},
        )
    })


def test_sessao_renova_uma_vez_e_reusa(perfil: Path) -> None:
    identidade.guardar(SEGREDO, BASE, EMAIL, MAQUINA)
    client = _client_de_token()
    s = identidade.Sessao(client, BASE)

    assert s.cabecalhos()["Authorization"] == "Bearer jwt-abc"
    s.cabecalhos()
    s.cabecalhos()
    # Uma chamada só: o token vale uma hora, não se pede um por requisição.
    assert len(client.enviados) == 1


def test_sessao_renova_antes_de_expirar(perfil: Path) -> None:
    """
    Renovar no 401 traria a falha para o meio de uma instalação. A folga existe
    para o token nunca morrer em uso.
    """
    identidade.guardar(SEGREDO, BASE, EMAIL, MAQUINA)
    client = _client_de_token(validade_min=10)
    s = identidade.Sessao(client, BASE)
    s.cabecalhos()

    # 10 min de validade menos 5 de folga: aos 6 minutos já tem de renovar,
    # mesmo com o token ainda tecnicamente válido.
    s._expira_em = time.time() - 1
    s.cabecalhos()
    assert len(client.enviados) == 2


def test_o_token_nunca_vai_para_o_disco(perfil: Path) -> None:
    identidade.guardar(SEGREDO, BASE, EMAIL, MAQUINA)
    s = identidade.Sessao(_client_de_token(), BASE)
    s.cabecalhos()

    assert b"jwt-abc" not in identidade.caminho().read_bytes()
    assert identidade.ler().get("access_token") is None


def test_revogado_no_portal_apaga_a_credencial_local(perfil: Path) -> None:
    """
    Manter um segredo que o portal já recusa faz o agente tentar para sempre e
    esconde o motivo de quem for olhar a estação.
    """
    identidade.guardar(SEGREDO, BASE, EMAIL, MAQUINA)
    s = identidade.Sessao(_client_de_token(401), BASE)

    with pytest.raises(identidade.NaoRegistrado):
        s.cabecalhos()

    assert identidade.esta_registrado() is False


def test_erro_passageiro_nao_apaga_a_credencial(perfil: Path) -> None:
    """
    Portal em deploy devolve 503. Apagar aqui obrigaria a pessoa a fazer login
    de novo por causa de uma indisponibilidade de trinta segundos.
    """
    identidade.guardar(SEGREDO, BASE, EMAIL, MAQUINA)
    s = identidade.Sessao(_client_de_token(503), BASE)

    with pytest.raises(RuntimeError):
        s.cabecalhos()

    assert identidade.esta_registrado() is True


def test_sem_registro_diz_o_que_fazer(perfil: Path) -> None:
    s = identidade.Sessao(_client_de_token(), BASE)
    with pytest.raises(identidade.NaoRegistrado, match="login"):
        s.cabecalhos()
