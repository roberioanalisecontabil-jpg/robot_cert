"""Colunas apertadas no fluidez.css (06/11/2026).

Trilha, SIEG e Computadores: a moldura da tabela rola por dentro, nunca a
página, e a coluna secundária cede primeiro quando a moldura estreita
(@container). A medição foi feita no navegador; aqui fica o que impede a
volta. Spec: docs/superpowers/specs/2026-11-06-fluidez-design.md, seção 6.
"""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
FLUIDEZ = (RAIZ / "static" / "fluidez.css").read_text(encoding="utf-8")


def _bloco(css: str, seletor: str) -> str:
    m = re.search(re.escape(seletor) + r"[^{]*\{([^}]*)\}", css)
    assert m, seletor
    return m.group(1)


def test_fluidez_vale_so_a_partir_de_769():
    assert FLUIDEZ.index("@media (min-width: 769px) {") < FLUIDEZ.index("#aba-trilha .ag-table-scroll")
    assert FLUIDEZ.rstrip().endswith("}  /* @media (min-width: 769px) */")


def test_trilha_sieg_e_computadores_rolam_dentro_da_moldura():
    bloco = _bloco(FLUIDEZ, "#aba-trilha .ag-table-scroll,\n#aba-sieg .ag-table-scroll,\n#painel-computadores .ag-table-scroll")
    assert "overflow-x: auto" in bloco
    assert "visible" not in bloco
    # sem isto o .cg-sr-only do cabeçalho "Ações" escapa e a página rola de lado
    assert "position: relative" in bloco
    assert "container-type: inline-size" in bloco
    for seletor in (".cg-tabela-trilha .ag-table-scroll", ".cg-tabela-comp .ag-table-scroll"):
        assert not re.search(re.escape(seletor) + r"\s*\{[^}]*overflow: visible", FLUIDEZ)


def test_colunas_secundarias_cedem_por_container():
    assert re.search(r"@container \(max-width: \d+px\) \{\s*\.cg-tabela-trilha \.ag-etapas__item", FLUIDEZ)
    # a etapa que falhou nao perde o nome: toque e teclado nao mostram o title
    assert ".cg-tabela-trilha .ag-etapas__item:not(.is-falha) { font-size: 0" in FLUIDEZ
    assert re.search(r"@container \(max-width: \d+px\) \{\s*\.cg-tabela-comp \.cg-col-acoes", FLUIDEZ)
    assert "flex-wrap: nowrap" in _bloco(FLUIDEZ, ".cg-tabela-trilha .ag-etapas")
    msg = _bloco(FLUIDEZ, ".cg-sieg-det > .ag-accordion__topo > span:first-child")
    assert "text-overflow: ellipsis" in msg and "white-space: nowrap" in msg


def test_texto_cortado_tem_title():
    html = (RAIZ / "templates" / "instalador.html").read_text(encoding="utf-8")
    assert '<summary class="ag-accordion__topo"><span title="${esc(l.mensagem || "")}">' in html
    assert '<ol class="ag-etapas" aria-hidden="true" title="${esc(sr)}">' in html


def test_nenhuma_fonte_maior_nas_colunas():
    sec = FLUIDEZ[FLUIDEZ.index("/* 7. Colunas apertadas"):]
    assert set(re.findall(r"font-size:\s*([^;]+);", sec)) == {"0"}  # só o ícone sem rótulo


def test_versao_do_fluidez_nos_templates():
    usam = [p for p in (RAIZ / "templates").glob("*.html") if "/static/fluidez.css" in p.read_text(encoding="utf-8")]
    assert len(usam) == 8
    for p in usam:
        assert "fluidez.css?v=fluidez-2026-11-07" in p.read_text(encoding="utf-8"), p.name
