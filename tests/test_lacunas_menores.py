"""Lacunas menores das telas (22/11/2026).

Sem executor de JavaScript no projeto: os testes leem o template e conferem
o trecho que decide o comportamento. (Os prints da wiki por papel estão em
tests/test_wiki.py.)
"""
from __future__ import annotations

import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def _funcao(html: str, nome: str) -> str:
    """O corpo de `async function <nome>()` até a próxima função do mesmo nível."""
    m = re.search(r"\n(\s*)(?:async )?function " + nome + r"\(.*?\n\1\}\n", html, re.S)
    assert m, nome
    return m.group(0)


def test_previa_do_expurgo_so_pede_retencao_quando_falta_retencao() -> None:
    """Com a contagem falhando (motivo "falha ao contar os registros"), o
    conselho de definir uma retenção mandava a pessoa mexer no que estava certo."""
    corpo = _funcao((TEMPLATES / "instalador.html").read_text(encoding="utf-8"), "abrirExpurgo")
    assert re.search(r"d\.retencao_dias\s*\?[^;]*Defina uma retenção em dias e salve antes", corpo, re.S)


def test_avisos_enviados_em_horario_de_brasilia() -> None:
    html = (TEMPLATES / "colaborador_certificados.html").read_text(encoding="utf-8")
    assert 'fmtDataHora(it.enviado_em, "America/Sao_Paulo")' in html
    assert "fmtDataHora(it.enviado_em))" not in html


def test_aba_sieg_avisa_quando_a_lista_foi_cortada() -> None:
    corpo = _funcao((TEMPLATES / "instalador.html").read_text(encoding="utf-8"), "loadSieg")
    assert re.search(r"d\.total\s*>\s*itens\.length", corpo)
    assert '"Mostrando "' in corpo
