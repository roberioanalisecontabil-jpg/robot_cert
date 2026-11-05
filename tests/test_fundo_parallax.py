"""Fundo com parallax (Montanhas, 05/11/2026): todas as telas menos o login."""
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _ler(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


def test_ui_common_carrega_o_fundo():
    assert "/static/fundo-parallax.js?v=" in _ler("static/ui-common.js")


def test_login_nao_carrega_o_fundo():
    login = _ler("templates/login.html")
    assert "ui-common.js" not in login and "fundo-parallax" not in login


def test_fundo_nao_recebe_clique_e_respeita_movimento_reduzido():
    css = _ler("static/fundo-parallax.css")
    assert "pointer-events: none" in css and "prefers-reduced-motion" in css
    assert "prefers-reduced-motion" in _ler("static/fundo-parallax.js")


def test_sem_sol_no_claro():
    css = _ler("static/fundo-parallax.css")
    claro = css.split("html.dark .cg-fundo")[0]
    assert "--fundo-astro: transparent" in claro
