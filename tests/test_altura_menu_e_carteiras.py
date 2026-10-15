"""Menu lateral e lista de operadores cabem na altura da janela (15/10/2026).

Os dois defeitos eram de CSS e não aparecem em teste de rota: o menu do admin
(13 itens, ~780px) passava do fim da tela num notebook sem jeito de rolar, e
a lista das carteiras nunca rolava por dentro porque a regra base vinha depois
da media query. A medição de verdade foi feita no navegador; aqui fica o que
impede a volta.
"""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"


def _bloco(css: str, seletor: str) -> str:
    m = re.search(re.escape(seletor) + r"\s*\{([^}]*)\}", css)
    assert m, seletor
    return m.group(1)


def test_menu_lateral_rola_por_dentro():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    nav = _bloco(css, "\n.sidebar-nav")
    assert "overflow-y: auto" in nav
    assert "min-height: 0" in nav  # sem isto o flex não deixa encolher e nada rola


def test_balao_do_menu_nao_depende_de_pseudo_elemento():
    # Com o menu rolando, o ::after à direita do item seria cortado.
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert re.search(r"\.sidebar-nav a::before,\s*\.sidebar-nav a::after\s*\{\s*display: none;", css)
    js = (STATIC / "ui-common.js").read_text(encoding="utf-8")
    assert "function initSidebarDicas" in js
    assert js.count("initSidebarDicas();") == 2  # nos dois caminhos de partida


def test_lista_de_operadores_tem_altura_maxima_que_vale():
    css = (STATIC / "aguia-carteiras.css").read_text(encoding="utf-8")
    base = css.index(".cg-op-rolagem { overflow-y: auto; max-height: none; }")
    media = css.index("@media (min-width: 1025px)")
    assert base < media, "a regra base depois da media query anula o max-height"
    assert re.search(r"\.cg-op-rolagem \{ max-height: max\(", css[media:])
