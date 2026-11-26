"""Lote 4-b da revisão (22/11/2026): achados P6-3, P6-4 e P6-6 do Instalador."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.settings_state as ss
from app import cert_installer
from app import entrada as pe
from app.rotas import instalador
from tests.test_seguranca_lote1 import _Fake

RAIZ = Path(__file__).resolve().parents[1]
ERRO_BANCO = 'LINE 1: SELECT * FROM "cert_pfx_store"'


def _funcao_js(nome: str) -> str:
    # Movimentos foi do Instalador para a Auditoria em 26/11/2026.
    js = (RAIZ / "static" / "auditoria.js").read_text(encoding="utf-8")
    ini = js.index(f"async function {nome}(")
    return js[ini: js.index("\n  }\n", ini)]


# ── P6-3: Movimentos corta em `limite` e precisa dizer que cortou ─────────

def test_p6_3_listar_avisa_quando_o_limite_corta_os_eventos(monkeypatch: pytest.MonkeyPatch) -> None:
    agora = datetime.now(timezone.utc)
    linhas = [
        {"id": i, "resultado": "movido", "quando": (agora - timedelta(minutes=i)).isoformat(), "resolvido_em": None}
        for i in range(501)
    ]
    monkeypatch.setattr(pe, "_banco", lambda: _Fake({pe.TABELA: linhas}))
    assert pe.listar(dias=365, limite=500)["truncado"] is True
    assert pe.listar(dias=365, limite=1000)["truncado"] is False


def test_p6_3_tela_de_movimentos_diz_que_a_lista_foi_cortada() -> None:
    js = _funcao_js("loadEntrada")
    assert "data.truncado" in js
    assert "reduza o período" in js


# ── P6-4: falha em /api/settings não pode acusar pasta não configurada ────

def test_p6_4_alerta_de_pasta_so_muda_quando_settings_respondeu() -> None:
    js = _funcao_js("loadEntrada")
    assert re.search(r"if \(cfg\.ok\) \{[^}]*entradaSemPasta\"\)\.hidden", js), (
        "o alerta 'pasta não configurada' só pode ser ajustado dentro do ramo cfg.ok"
    )


# ── P6-6: o texto cru do erro do banco não vai ao navegador ───────────────

def test_p6_6_diagnostico_nao_devolve_o_erro_do_banco(monkeypatch: pytest.MonkeyPatch) -> None:
    def falha():
        raise RuntimeError(ERRO_BANCO)

    monkeypatch.setattr(cert_installer, "diagnostico_do_cofre", falha)
    out = instalador.diagnostico_do_instalador()
    assert "LINE 1" not in repr(out)
    assert out["cofre"]["erro"]


def test_p6_6_previa_do_expurgo_nao_devolve_o_erro_do_banco(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Quebra:
        def table(self, _nome):
            raise RuntimeError(ERRO_BANCO)

    monkeypatch.setattr(instalador, "load_settings", lambda: SimpleNamespace(trilha_retencao_dias=30))
    monkeypatch.setattr(ss, "_banco", lambda: _Quebra())
    out = instalador.previa_do_expurgo()
    assert "LINE 1" not in repr(out)
    assert out["executado"] is False and out["motivo"]
