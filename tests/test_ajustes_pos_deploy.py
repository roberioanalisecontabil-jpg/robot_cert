"""
Dois ajustes pedidos depois do deploy dos lotes 7 a 9 (29/09/2026).

1. O portal recusava com 403 um `machine_id` declarado diferente do da
   credencial de máquina (lote 2, `ERRO_MAQUINA_DIVERGENTE`) SEM escrever nada
   no log. No ANALISESRV a credencial fora provisionada com o nome do arquivo
   de exemplo e o agente declarava outro: o inventário parou e levou três
   rodadas de sondas para achar a causa, porque o log não dizia.

2. O agente informava "Cofre sincronizado: 483 de 477 certificados
   autorizados": contava ARQUIVOS enviados contra CERTIFICADOS autorizados. O
   mesmo certificado em duas pastas (duplicata) era contado duas vezes.

Escritos antes da correção; falhavam em 65f1dcc.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi import HTTPException

import app.main as m
from agent.installer_client import upload_pfx_files
from app import auth
from app.cert_scanner import CertInfo, CertStatus

RAIZ = Path(__file__).resolve().parents[1]


# ── 1. Divergência de machine_id vai para o log ────────────────────────────

def test_machine_id_divergente_e_recusado_e_registrado(caplog) -> None:
    token = auth.TokenData(email="agent@internal", role="agent", machine_id="analisesrv")
    with caplog.at_level(logging.WARNING):
        with pytest.raises(HTTPException) as e:
            m._machine_da_credencial(token, "meu_servidor_windows")
    assert e.value.status_code == 403
    texto = caplog.text.lower()
    assert "analisesrv" in texto and "meu_servidor_windows" in texto, "o log tem de dizer os dois nomes"
    assert "diverg" in texto


def test_sem_identidade_quando_exigida_tambem_e_registrado(caplog) -> None:
    token = auth.TokenData(email="agent@internal", role="agent")  # chave compartilhada
    with caplog.at_level(logging.WARNING):
        with pytest.raises(HTTPException):
            m._machine_da_credencial(token, "srv-01", exigir_identidade=True)
    assert "srv-01" in caplog.text and "identidade" in caplog.text.lower()


def test_machine_id_igual_nao_gera_aviso(caplog) -> None:
    token = auth.TokenData(email="agent@internal", role="agent", machine_id="analisesrv")
    with caplog.at_level(logging.WARNING):
        assert m._machine_da_credencial(token, "ANALISESRV") == "ANALISESRV"
    assert "diverg" not in caplog.text.lower()


# ── 2. Contagem do cofre por certificado, não por arquivo ──────────────────

class _Resp:
    status_code = 200
    text = ""


class _Client:
    def __init__(self) -> None:
        self.posts = 0

    def post(self, *a, **k):
        self.posts += 1
        return _Resp()


def _cert(tmp_path: Path, nome: str, fp: str) -> CertInfo:
    p = tmp_path / nome
    p.write_bytes(b"\x30\x82pfx")
    return CertInfo(path=p, file_name=nome, display_name=nome, status=CertStatus.OK,
                    fingerprint_sha256=fp, password_from_name="x")


def test_duplicata_conta_uma_vez_e_o_log_diz_quantos_arquivos(tmp_path: Path, monkeypatch, caplog) -> None:
    import agent.installer_client as ic

    monkeypatch.setattr(ic, "_buscar_fingerprints_autorizados", lambda *a, **k: {"f1", "f2"})
    (tmp_path / "sub").mkdir()
    itens = [
        _cert(tmp_path, "a.pfx", "f1"),
        _cert(tmp_path / "sub", "a-copia.pfx", "f1"),   # o mesmo certificado noutra pasta
        _cert(tmp_path, "b.pfx", "f2"),
        _cert(tmp_path, "nao-autorizado.pfx", "f9"),
    ]
    cliente = _Client()
    with caplog.at_level(logging.INFO):
        upload_pfx_files(cliente, "https://p", {}, "ANALISESRV", itens)
    assert cliente.posts == 3, "as duas cópias do mesmo certificado vão ao cofre (upsert), o não autorizado não"
    assert "2 de 2 certificados autorizados" in caplog.text
    assert "3 arquivos" in caplog.text and "1 duplicado" in caplog.text
    assert "3 de 2" not in caplog.text


# ── 3. O instalador não pode trocar a conta do serviço em silêncio ──────────
#
# 29/09/2026: o instalador da 1.4.0 remove e recria o serviço, e a página
# "Conta do serviço" vem em branco. Em branco = LocalSystem, que não alcança
# o compartilhamento de rede da pasta de origem. O serviço subiu, conectou ao
# portal e parou antes do watchdog, sem erro no log. Agora o instalador lê a
# conta atual (`sc qc`), a mostra na página, exige a senha para mantê-la e
# pede confirmação explícita para trocar por LocalSystem.

def test_instalador_le_a_conta_atual_e_exige_a_senha_para_mantê_la() -> None:
    iss = (RAIZ / "agent_setup.iss").read_text(encoding="utf-8", errors="replace")
    assert "SERVICE_START_NAME" in iss, "precisa ler a conta atual com sc qc"
    assert "function NextButtonClick" in iss, "a pagina da conta precisa validar antes de avancar"
    assert "Deixe ambos em branco para usar LocalSystem (padrao)" not in iss
    assert "LocalSystem" in iss and "rede" in iss.lower()
    assert "AppVersion=1.7.0" in iss
