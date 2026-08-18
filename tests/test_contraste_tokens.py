"""Contraste WCAG dos tokens de cor, nos dois temas.

A auditoria de 02/08 calculou contraste por luminância relativa e corrigiu os
pares de status (--ok-text etc.), mas os números ficaram em COMENTÁRIOS do
style.css — nada os conferia. Foi assim que três pares do tema escuro chegaram
a 18/08 reprovando sem sintoma: --text-muted sobre --surface (4.27:1), texto
branco sobre --sidebar-active-bg (3.65:1) e --accent usado como texto (3.82:1).
O escuro não é inversão do claro: um token pode passar num tema e reprovar no
outro, e a suíte lê o CSS sem nunca renderizar, então só um cálculo aqui pega.

Dois guardas:

1. Os pares fg/bg que EXISTEM no CSS (texto exige 4.5:1; elemento gráfico,
   3:1). A lista é dos usos reais — não é proibido um token "fraco" existir,
   é proibido usá-lo onde reprova.
2. Os dois blocos escuros (`:root[data-theme="dark"]` e o de
   `prefers-color-scheme`) declaram os MESMOS tokens com os MESMOS valores.
   O comentário "MANTER SINCRONIZADO" era a única trava; divergência não dá
   sintoma em quem escolheu tema explícito, só em quem segue o sistema.

Fundos tonais do escuro são rgba sobre --surface; o cálculo compõe o alpha
antes de medir, como o navegador faz.
"""

import re
from pathlib import Path

import pytest

CSS_PATH = Path(__file__).resolve().parent.parent / "static" / "style.css"


def _sem_comentarios(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _bloco(css: str, inicio: str) -> str:
    """Corpo do bloco de tokens que começa em `inicio` (sem blocos aninhados)."""
    m = re.search(re.escape(inicio) + r"\s*\{(.*?)\}", css, flags=re.S)
    assert m, f"bloco não encontrado: {inicio}"
    return m.group(1)


def _tokens(corpo: str) -> dict:
    return dict(re.findall(r"(--[\w-]+):\s*([^;]+);", corpo))


@pytest.fixture(scope="module")
def css() -> str:
    return _sem_comentarios(CSS_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def claro(css: str) -> dict:
    return _tokens(_bloco(css, ":root"))


@pytest.fixture(scope="module")
def escuro(css: str, claro: dict) -> dict:
    # Token não redefinido no escuro herda o do claro (ex.: --accent-solid).
    return {**claro, **_tokens(_bloco(css, ':root[data-theme="dark"]'))}


def _cor(valor: str):
    """(r, g, b, a) a partir de #hex ou rgba(). Ignora o que não for cor."""
    valor = valor.strip()
    m = re.fullmatch(r"#([0-9a-fA-F]{6})", valor)
    if m:
        h = m.group(1)
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4)) + (1.0,)
    m = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)", valor)
    if m:
        r, g, b = (int(m.group(i)) for i in (1, 2, 3))
        return (r, g, b, float(m.group(4) or 1.0))
    return None


def _compor(fg, base):
    a = fg[3]
    return tuple(round(f * a + b * (1 - a)) for f, b in zip(fg[:3], base[:3])) + (1.0,)


def _luminancia(rgb) -> float:
    def canal(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (canal(v) for v in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contraste(fg, bg) -> float:
    l1, l2 = sorted((_luminancia(fg), _luminancia(bg)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


BRANCO = (255, 255, 255, 1.0)

# (fg, bg, mínimo, onde se usa). Fundos tonais compõem sobre --surface.
# 4.5:1 = texto (WCAG 1.4.3); 3:1 = componente/gráfico (WCAG 1.4.11).
PARES = [
    ("--text", "--bg", 4.5, "corpo da página"),
    ("--text", "--surface", 4.5, "cards e tabelas"),
    ("--text-muted", "--bg", 4.5, "subtítulos de página"),
    ("--text-muted", "--surface", 4.5, "th, hints, células secundárias"),
    ("--ok-text", "--ok-bg", 4.5, ".badge-ok, .msg-ok"),
    ("--warning-text", "--warning-bg", 4.5, ".badge-warning, .cg-banner--warning"),
    ("--expired-text", "--expired-bg", 4.5, ".badge-expired, button.danger"),
    ("--danger-text", "--surface", 4.5, "mensagens de erro sobre card"),
    ("--fora-padrao-text", "--fora-padrao-bg", 4.5, "badge fora do padrão"),
    ("--sidebar-text", "--sidebar-bg", 4.5, "itens da sidebar"),
    ("--sidebar-danger", "--sidebar-bg", 4.5, "botão Sair"),
    ("--sidebar-text-active", "--sidebar-active-bg", 4.5, "item ativo da sidebar"),
    ("--accent-text", "--surface", 4.5, ".doc-type-label, .aba.ativa, links"),
    ("--accent-text", "--total-bg", 4.5, ".cg-page-link--current, .notif-sync-mode"),
    (BRANCO, "--accent-solid", 4.5, "button.primary, .skip-to-content, .login-btn"),
    (BRANCO, "--accent-hover", 4.5, "button.primary:hover"),
    ("--accent", "--surface", 3.0, "anel de foco, .toast-info .toast-icon"),
    ("--total", "--total-bg", 3.0, ".card-total .card-icon"),
]


def _resolver(tema: dict, ref):
    if isinstance(ref, tuple):
        return ref
    assert ref in tema, f"token ausente: {ref}"
    cor = _cor(tema[ref])
    assert cor, f"valor de {ref} não é cor parseável: {tema[ref]!r}"
    return cor


@pytest.mark.parametrize("fg_ref, bg_ref, minimo, onde", PARES)
def test_contraste_no_tema_claro(claro, fg_ref, bg_ref, minimo, onde):
    fg = _resolver(claro, fg_ref)
    bg = _compor(_resolver(claro, bg_ref), _resolver(claro, "--surface"))
    r = _contraste(fg, bg)
    assert r >= minimo, f"[claro] {fg_ref} sobre {bg_ref} ({onde}): {r:.2f}:1 < {minimo}:1"


@pytest.mark.parametrize("fg_ref, bg_ref, minimo, onde", PARES)
def test_contraste_no_tema_escuro(escuro, fg_ref, bg_ref, minimo, onde):
    fg = _resolver(escuro, fg_ref)
    bg = _compor(_resolver(escuro, bg_ref), _resolver(escuro, "--surface"))
    r = _contraste(fg, bg)
    assert r >= minimo, f"[escuro] {fg_ref} sobre {bg_ref} ({onde}): {r:.2f}:1 < {minimo}:1"


def test_blocos_escuros_identicos(css):
    """O bloco de tema explícito e o de preferência do sistema são o MESMO tema."""
    explicito = _tokens(_bloco(css, ':root[data-theme="dark"]'))
    media = re.search(
        r"@media\s*\(prefers-color-scheme:\s*dark\)\s*\{\s*"
        r':root:not\(\[data-theme="light"\]\)\s*\{(.*?)\}',
        css,
        flags=re.S,
    )
    assert media, "bloco do prefers-color-scheme não encontrado"
    sistema = _tokens(media.group(1))
    normal = lambda d: {k: re.sub(r"\s+", " ", v.strip()) for k, v in d.items()}
    assert normal(explicito) == normal(sistema)
