"""Invariantes da navegação lateral única (`templates/_sidebar.html`).

Até 15/08/2026 a sidebar era copiada em 8 templates. As 8 cópias eram
equivalentes — mesmo SHA-256 depois de normalizar espaços e o marcador de página
atual —, o que quer dizer que nenhuma tinha divergido *ainda*. O custo era o
próximo item: 8 edições, e bastava uma passar batida para uma página ficar com um
menu diferente das outras, sem nada quebrar.

Estes testes protegem as duas pontas do arranjo novo:

1. **A duplicação não volta.** Uma página nova que traga sua própria `<aside>`
   passa despercebida numa revisão de diff grande — este é o teste que reclama.
2. **A página acesa é a certa.** `pagina_ativa` é uma string solta no contexto da
   rota. Errar a chave, ou esquecê-la, não levanta exceção nenhuma: o menu
   renderiza com nenhum item aceso. É falha silenciosa da mesma família do bug do
   `machine_id` de 08/08 — cada lado correto isoladamente, o elo entre eles
   errado. Por isso a verificação é feita renderizando a rota de verdade, não
   lendo o template.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
PARTIAL = TEMPLATES / "_sidebar.html"

# (rota, chave esperada em pagina_ativa, href que deve acender)
PAGINAS = [
    ("/", "inicio", "/"),
    ("/dashboard", "dashboard", "/dashboard"),
    ("/carteiras", "carteiras", "/carteiras"),
    ("/historico", "historico", "/historico"),
    ("/vencidos", "vencidos", "/vencidos"),
    ("/duplicidades", "duplicidades", "/duplicidades"),
    ("/acompanhamento", "acompanhamento", "/acompanhamento"),
    ("/instalador", "instalador", "/instalador"),
    ("/usuarios", "usuarios", "/usuarios"),
    ("/configuracao", "configuracao", "/configuracao"),
]


def _links_acesos(html: str) -> list[str]:
    """hrefs marcados com class="active" dentro da navegação lateral."""
    nav = re.search(r'<nav class="sidebar-nav">.*?</nav>', html, re.DOTALL)
    assert nav, "a página renderizou sem a navegação lateral"
    return re.findall(r'<a href="([^"]*)"[^>]*class="active"', nav.group(0))


# ──────────────────────────────────────────────────────────────────────────
# 1. A duplicação não volta
# ──────────────────────────────────────────────────────────────────────────

def test_apenas_o_partial_declara_a_navegacao() -> None:
    """Nenhum outro template pode trazer sua própria `<nav class="sidebar-nav">`."""
    reincidentes = [
        f.name
        for f in sorted(TEMPLATES.glob("*.html"))
        if f.name != "_sidebar.html"
        and '<nav class="sidebar-nav">' in f.read_text(encoding="utf-8")
    ]
    assert not reincidentes, (
        f"sidebar duplicada em {reincidentes} — use "
        '{% include "_sidebar.html" %} em vez de copiar o bloco'
    )


def test_paginas_internas_incluem_o_partial() -> None:
    """
    Toda página com `<main class="main-content">` é página interna e precisa do
    menu. O login fica de fora de propósito: quem não entrou não tem para onde
    navegar.
    """
    for f in sorted(TEMPLATES.glob("*.html")):
        if f.name in ("_sidebar.html", "login.html"):
            continue
        html = f.read_text(encoding="utf-8")
        if '<main class="main-content"' not in html:
            continue
        assert '{% include "_sidebar.html" %}' in html, f"{f.name} sem o include"


def test_login_continua_sem_menu() -> None:
    html = (TEMPLATES / "login.html").read_text(encoding="utf-8")
    assert "_sidebar.html" not in html
    assert "<aside" not in html


# ──────────────────────────────────────────────────────────────────────────
# 2. A página acesa é a certa — renderizando as rotas de verdade
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rota,chave,href_aceso", PAGINAS)
def test_rota_acende_exatamente_o_seu_item(
    client: TestClient, rota: str, chave: str, href_aceso: str
) -> None:
    """
    Um item aceso, e o item certo.

    "Exatamente um" é a parte que importa: zero significa `pagina_ativa`
    esquecida ou com a chave errada, e mais de um significa marcador fixo
    sobrevivendo no partial. Os dois passariam por uma inspeção visual rápida.
    """
    r = client.get(rota)
    assert r.status_code == 200, r.text

    acesos = _links_acesos(r.text)
    assert acesos == [href_aceso], (
        f"{rota} (pagina_ativa={chave!r}) acendeu {acesos}, esperado ['{href_aceso}']"
    )


def test_todas_as_rotas_de_pagina_estao_cobertas() -> None:
    """
    O parametrize acima só protege o que está listado nele.

    Uma página nova cuja rota esqueça `pagina_ativa` continuaria passando —
    ninguém a teria acrescentado a PAGINAS. Este teste fecha a porta: varre as
    rotas HTML declaradas na aplicação e exige que cada uma esteja na lista.
    """
    from app.main import app

    rotas_html = {
        r.path
        for r in app.routes
        if getattr(r, "methods", None)
        and "GET" in r.methods
        and getattr(r, "response_class", None) is not None
        and "HTMLResponse" in str(getattr(r, "response_class", ""))
    }
    # O login renderiza HTML e não tem menu — é a única exceção legítima.
    rotas_html.discard("/login")

    faltando = rotas_html - {rota for rota, _, _ in PAGINAS}
    assert not faltando, (
        f"rota(s) de página fora da cobertura: {sorted(faltando)} — "
        "acrescente a PAGINAS e passe pagina_ativa na rota"
    )


def test_partial_nao_tem_marcador_fixo() -> None:
    """
    Todo `class="active"` do partial vive dentro de um `{% if ativa == ... %}`.

    Um marcador fixo que sobrevivesse à extração acenderia o mesmo item em toda
    página — e, como algo acende, o teste de "exatamente um" acima continuaria
    verde na página cujo item é esse.
    """
    texto = PARTIAL.read_text(encoding="utf-8")
    assert texto.count('class="active"') == texto.count("{% if ativa ==")
    assert texto.count('class="active"') == len(PAGINAS)


def test_chaves_do_partial_batem_com_as_rotas() -> None:
    """As chaves aceitas pelo template são exatamente as que as rotas mandam."""
    texto = PARTIAL.read_text(encoding="utf-8")
    do_template = set(re.findall(r'\{% if ativa == "([^"]+)" %\}', texto))
    assert do_template == {chave for _, chave, _ in PAGINAS}
