"""
Lote 4 (revisão de código), parte A: Início, Histórico e Duplicidades.

Cada teste foi escrito antes da correção e falhava no código anterior.
As telas não têm executor de JS: os testes de front leem o HTML/JS.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.rotas.certificados as cert
from app import db_pg
from tests.test_seguranca_lote4 import ADMIN, _h, banco  # noqa: F401

RAIZ = Path(__file__).resolve().parents[1]


def _ler(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


def _funcao_js(src: str, inicio: str) -> str:
    """Corpo aproximado de uma função: do cabeçalho até a próxima linha `}` no mesmo recuo."""
    i = src.index(inicio)
    recuo = src.rfind("\n", 0, i) + 1
    fim = src.index("\n" + src[recuo:i] + "}", i)
    return src[i:fim]


# ── P1-2: instalabilidade não fica presa no cache depois de uma falha ──────

def test_instalabilidade_reconsulta_depois_de_falha_e_no_atualizar() -> None:
    html = _ler("templates/index.html")
    corpo = _funcao_js(html, "async function carregarInstalabilidade(")
    catch = corpo[corpo.index("} catch (e) {"):]
    assert "_instalMachineId = null" in catch
    i = html.index('getElementById("btn-refresh").addEventListener')
    assert "_instalMachineId = null" in html[i:html.index("});", i)]


# ── P1-6: vencido pela data não é instalável ───────────────────────────────

def test_inicio_estado_de_respeita_vencido_pela_data() -> None:
    corpo = _funcao_js(_ler("templates/index.html"), "function estadoDe(it)")
    assert "it._isExpiredByDate" in corpo


# ── P1-4 / P3-4: datas no fuso local, como o modal e a Custódia ────────────

@pytest.mark.parametrize("tela", ["templates/index.html", "templates/historico.html"])
def test_datas_da_lista_nao_sao_formatadas_em_utc(tela: str) -> None:
    assert not re.search(r"timeZone:\s*[\"']UTC[\"']", _ler(tela))


# ── P1-3: vencido há menos de 24 h não é "vence hoje" ──────────────────────

def test_validade_decide_pelo_instante_antes_de_arredondar() -> None:
    corpo = _funcao_js(_ler("static/detalhes-certificado.js"), "function validadeTexto(it)")
    assert "ms < 0" in corpo
    assert corpo.index("if (ms < 0)") < corpo.index("Math.ceil(ms")


# ── P1-5: busca por dígitos não casa com a data do vencimento ──────────────

def test_busca_do_inicio_nao_casa_com_a_data() -> None:
    row = {"nome": "PADARIA X", "documento_numero": "11222333000144",
           "documento_formatado": "11.222.333/0001-44", "not_after": "2026-12-31T23:59:59+00:00"}
    assert not cert._dashboard_busca_match(row, "1231")
    assert not cert._dashboard_busca_match(row, "2026-12")
    assert cert._dashboard_busca_match(row, "112223")


# ── P3-6: busca da exportação igual à do ILIKE (sem datas) ─────────────────

def test_busca_do_historico_nao_casa_com_datas() -> None:
    itens = [{"nome_publico": "ALFA", "nome": "ALFA", "documento": "11111111000191",
              "ultima_data_registrada": "2027-01-05T10:00:00+00:00", "vencimento_certificado": "2027-06-01"}]
    assert cert._historico_filtrar_busca(itens, "2027") == []
    assert cert._historico_filtrar_busca(itens, "alfa") == itens


# ── P3-5: erro SQL qualquer em cert_history é 500, não fallback ────────────

def test_coluna_ausente_em_cert_history_da_500(client: TestClient, banco, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    def _quebra(_sb):
        raise db_pg.DbError('column "ausente_desde" does not exist\nLINE 1: ... FROM "cert_history"', code="42703")

    monkeypatch.setattr(cert, "_cert_history_fetch_all", _quebra)
    r = client.get("/api/certificados/historico?todas_filtradas=true", headers=_h(*ADMIN))
    assert r.status_code == 500, r.text


# ── P4-1: cópia repetida não esconde o renovado de "Mesmo CPF/CNPJ" ────────

def test_copia_repetida_nao_esconde_o_renovado() -> None:
    doc = "11222333000144"
    rows = [
        {"nome_publico": "A", "nome": "X", "documento_numero": doc, "status": "ok", "fingerprint_sha256": "a" * 64},
        {"nome_publico": "A2", "nome": "X", "documento_numero": doc, "status": "ok", "fingerprint_sha256": "a" * 64},
        {"nome_publico": "B", "nome": "X", "documento_numero": doc, "status": "ok", "fingerprint_sha256": "b" * 64},
    ]
    gd, _gn, gci = cert._agrupar_duplicidades(rows)
    assert len(gci) == 1
    assert [g["documento_digitos"] for g in gd] == [doc]
    assert len(gd[0]["itens"]) == 2


# ── P4-3: carteira vazia não vira "o agente não enviou o inventário" ───────

def test_duplicidades_trata_alcance_vazio() -> None:
    html = _ler("templates/duplicidades.html")
    assert "j.alcance_vazio" in html and "Sua carteira está vazia" in html
    assert html.index("j.alcance_vazio") < html.index("if (!total)")
