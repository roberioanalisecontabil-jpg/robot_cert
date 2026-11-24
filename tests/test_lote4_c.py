"""Revisão de 22/11/2026, lote 4-C: achados baixos de Carteiras e Acompanhamento."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

import app.rotas.acompanhamento as acomp
import app.rotas.certificados as cert

RAIZ = Path(__file__).resolve().parents[1]
COLAB = (RAIZ / "templates" / "colaborador_certificados.html").read_text(encoding="utf-8")
CERTS_JS = (RAIZ / "static" / "carteiras-certificados.js").read_text(encoding="utf-8")
DOC = "33706943000193"


def _funcao(fonte: str, nome: str) -> str:
    """Corpo de `function nome(` até a próxima função do mesmo nível."""
    ini = fonte.index("function " + nome + "(")
    prox = re.search(r"\n    (async )?function |\n  (async )?function ", fonte[ini + 1:])
    return fonte[ini: ini + 1 + prox.start()] if prox else fonte[ini:]


# ── P10-5: dias restantes no dia de Brasília ─────────────────────────────────

class _Relogio(datetime):
    """22h de 24/11 em Brasília = 01h de 25/11 em UTC."""

    @classmethod
    def now(cls, tz=None):
        agora = datetime(2026, 11, 25, 1, 0, tzinfo=timezone.utc)
        return agora.astimezone(tz) if tz else agora.replace(tzinfo=None)


@pytest.fixture
def vence_amanha_as_11h(monkeypatch: pytest.MonkeyPatch):
    item = {
        "nome": "ANALISE", "display_name": "ANALISE", "status": "ok",
        "not_after": "2026-11-25T14:00:00+00:00",
        "documento_numero": DOC, "documento_formatado": DOC,
        "file_name": "ANALISE.pfx", "path": "F:/CERTIFICADOS/ANALISE.pfx",
        "fingerprint_sha256": "fp-1",
    }
    monkeypatch.setattr(acomp, "load_settings", lambda: object())
    monkeypatch.setattr(cert, "get_latest_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(cert, "_list_certificados_payload", lambda *a, **k: {"itens": [item]})
    monkeypatch.setattr(acomp, "_documentos_ao_alcance", lambda token: None)
    monkeypatch.setattr(acomp, "datetime", _Relogio)


def test_painel_conta_os_dias_no_dia_de_brasilia(vence_amanha_as_11h) -> None:
    [r] = acomp._painel_docs_selecionados([DOC])
    assert r["dias_restantes"] == 1 and r["status"] == "expirando"


def test_opcoes_contam_os_dias_no_dia_de_brasilia(vence_amanha_as_11h) -> None:
    [it] = acomp.colaborador_opcoes_certificados(token=object())["itens"]
    assert it["dias_restantes"] == 1 and it["dias_texto"] == "em 1 dia"


def test_tela_mostra_o_vencimento_no_fuso_de_brasilia() -> None:
    assert COLAB.count('fmtSoData(it.vencimento_certificado, "America/Sao_Paulo")') == 2
    assert 'fmtDataHora(it.vencimento_certificado, "America/Sao_Paulo")' in COLAB


# ── P10-3: salvar a seleção trava o botão e trata erro de rede ───────────────

def test_salvar_selecao_trava_o_botao_e_avisa_erro_de_conexao() -> None:
    corpo = _funcao(COLAB, "salvarSelecao")
    assert 'getElementById("btn-salvar-selecao")' in corpo and ".disabled = true" in corpo
    assert "catch" in corpo and "Erro de conexão" in corpo and "finally" in corpo


def test_marcacao_feita_durante_o_salvamento_continua_pendente() -> None:
    corpo = _funcao(COLAB, "salvarSelecao")
    # Não troca `selecionados` inteiro pelo que o servidor gravou.
    assert "selecionados = new Set((gravado.documentos" not in corpo
    assert "selecaoSalva = " in corpo


# ── P10-4: o painel não depende da aba Escolher ──────────────────────────────

def test_init_nao_espera_a_selecao_antes_do_painel() -> None:
    init = COLAB[COLAB.index("(async function init()"):]
    assert "await carregarSelecao();" not in init
    assert init.index("carregarSelecao()") < init.index("await carregarPainel(true)")


def test_falha_de_rede_cai_no_estado_de_erro() -> None:
    painel = _funcao(COLAB, "carregarPainel")
    assert "catch" in painel and "Erro de conexão" in painel
    assert "catch" in _funcao(COLAB, "carregarSelecao")


# ── P10-6: a aba Escolher não reordena na troca de página ────────────────────

def test_troca_de_pagina_nao_reordena() -> None:
    assert "function linhasSelecao(reordenar)" in COLAB
    assert "if (!reordenar && _ordemSelecao) return _ordemSelecao;" in COLAB
    # Anterior, Seguinte e goToPage paginam a ordem guardada.
    assert "selecaoPagina--; renderSelecao(); }" in COLAB
    assert "selecaoPagina++; renderSelecao(); }" in COLAB
    assert "goToPage: (pn) => { selecaoPagina = pn; renderSelecao(); }" in COLAB
    # Busca, recarga e salvar reordenam.
    assert 'addEventListener("input", () => { selecaoPagina = 1; renderSelecao(true); })' in COLAB
    assert _funcao(COLAB, "carregarSelecao").count("renderSelecao(true)") == 2
    assert "renderSelecao(true)" in _funcao(COLAB, "salvarSelecao")


# ── P5-4: a aba Certificados recarrega ao voltar ────────────────────────────

def test_aba_certificados_recarrega_ao_voltar() -> None:
    iniciar = _funcao(CERTS_JS, "iniciar")
    assert "if (carregou) return;" not in iniciar
    assert "abrir(atual.documento)" in iniciar


def test_mudanca_em_certificados_atualiza_a_aba_pessoas() -> None:
    assert "carregarOperadores()" in _funcao(CERTS_JS, "recarregar")


def test_cache_buster_novo_da_aba_certificados() -> None:
    html = (RAIZ / "templates" / "carteiras.html").read_text(encoding="utf-8")
    assert "/static/carteiras-certificados.js?v=alinhamento-2026-11-23" in html
