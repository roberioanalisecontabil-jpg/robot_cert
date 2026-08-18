"""Invariantes de empilhamento do CSS.

O painel de notificações ficava atrás dos cards e da tabela, sem possibilidade
de interação. A causa não era o z-index do painel: `.main-content > *` usava
`animation: fadeUp ... both`, e `animation-fill-mode: both` mantém o último
keyframe aplicado para sempre. Esse keyframe contém `transform: translateY(0)`,
e um transform diferente de `none` cria um contexto de empilhamento — cada filho
de .main-content virava um contexto irmão, pintado em ordem de DOM, prendendo o
dropdown atrás dos elementos posteriores.

É um defeito que volta fácil: `both` parece a escolha natural para animação de
entrada, e o efeito colateral só aparece quando algo precisa flutuar por cima.
"""

import re
from pathlib import Path

import pytest

CSS_PATH = Path(__file__).resolve().parent.parent / "static" / "style.css"


@pytest.fixture(scope="module")
def css() -> str:
    """CSS sem comentários — evita casar com trechos explicativos."""
    return re.sub(r"/\*.*?\*/", "", CSS_PATH.read_text(encoding="utf-8"), flags=re.S)


def _z_index(css: str, seletor: str):
    m = re.search(re.escape(seletor) + r"\s*\{[^}]*?z-index:\s*(\d+)", css, flags=re.S)
    return int(m.group(1)) if m else None


def test_nenhuma_animacao_usa_fill_mode_both(css: str) -> None:
    """`both` deixa transform residual e cria contexto de empilhamento."""
    ocorrencias = re.findall(r"animation:[^;]*\bboth\b[^;]*;", css)
    assert not ocorrencias, (
        "animation-fill-mode 'both' deixa o último keyframe aplicado. "
        f"Se o keyframe tiver transform, cria contexto de empilhamento: {ocorrencias}"
    )


def test_entrada_do_conteudo_usa_backwards(css: str) -> None:
    assert re.search(r"\.main-content\s*>\s*\*\s*\{[^}]*animation:[^;]*backwards", css, flags=re.S)


def test_topbar_fica_acima_dos_irmaos(css: str) -> None:
    """Sem position+z-index, o dropdown não escapa do conteúdo da página."""
    bloco = re.search(r"\.topbar-actions\s*\{([^}]*)\}", css, flags=re.S)
    assert bloco, ".topbar-actions não encontrada"
    assert "position: relative" in bloco.group(1)
    assert (_z_index(css, ".topbar-actions") or 0) > 0


def test_topbar_nao_cobre_o_drawer_mobile(css: str) -> None:
    """
    O z-index do topbar precisa ser menor que o do backdrop e o da sidebar,
    senão o menu off-canvas deixaria de cobrir o conteúdo no mobile.
    """
    topbar = _z_index(css, ".topbar-actions")
    backdrop = _z_index(css, ".sidebar-backdrop")
    sidebar = _z_index(css, ".sidebar")
    assert None not in (topbar, backdrop, sidebar)
    assert topbar < backdrop < sidebar, f"topbar={topbar} backdrop={backdrop} sidebar={sidebar}"


def test_topbar_declarada_uma_unica_vez(css: str) -> None:
    """Regra duplicada foi o que escondeu este bug: havia dois blocos concorrentes."""
    assert css.count(".topbar-actions {") == 1


def test_dropdown_de_notificacoes_tem_z_index(css: str) -> None:
    assert (_z_index(css, ".notifications-dropdown") or 0) > 0


def test_chaves_balanceadas(css: str) -> None:
    assert css.count("{") == css.count("}")


def test_reduced_motion_nao_zera_transform_globalmente(css: str) -> None:
    """
    C3 da auditoria: neste projeto transform também é LAYOUT — o drawer mobile
    se esconde com translateX(-100%). Um `transform: none !important` global
    dentro de prefers-reduced-motion deixava a sidebar aberta sobre o conteúdo
    justamente para quem a regra deveria proteger. O bloco pode zerar transform
    apenas em seletores específicos (hover decorativo), nunca no universal.
    """
    m = re.search(r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{(.*)", css, flags=re.S)
    assert m, "bloco prefers-reduced-motion não encontrado"
    # Fecha o bloco da media query contando chaves.
    corpo, nivel = [], 1
    for ch in m.group(1):
        if ch == "{":
            nivel += 1
        elif ch == "}":
            nivel -= 1
            if nivel == 0:
                break
        corpo.append(ch)
    bloco = "".join(corpo)
    universal = re.search(r"(?:^|\})\s*\*\s*,[^{]*\{([^}]*)\}", bloco)
    assert universal, "grupo universal (*, ::before, ::after) não encontrado no bloco"
    assert "transform" not in universal.group(1), (
        "transform no grupo universal de prefers-reduced-motion quebra o drawer mobile"
    )
    # E as durações continuam curtas, não zero: removeToast() depende do
    # transitionend, que não dispara com duration 0s.
    assert "transition-duration: 0.01ms" in universal.group(1)
