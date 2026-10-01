"""
NOTA 01/10/2026: a secao "Meus computadores" saiu do Inicio (decisao I3 da
revisao de paginas: estacoes sao do Hardlyze). Ficam aqui os testes das badges
e da API /api/agent/dispositivos, que continua existindo.

Painel "Meus computadores" no Início, e o defeito que ele quase trouxe junto.

Ao escrever o painel eu usei `badge--ok`. O CSS define `badge-ok`. O resultado
não é erro nenhum: a `<span>` renderiza como texto cru no meio da tabela, e a
página continua funcionando. É a mesma classe de defeito de
`test_helpers_compartilhados.py` — chamar algo que não está lá —, só que em CSS
em vez de JavaScript, e ainda mais silenciosa: lá o console acusa
`ReferenceError`, aqui não acusa nada.

O primeiro teste é geral de propósito. Não guarda o meu painel: guarda qualquer
badge de qualquer template.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Set

import pytest

RAIZ = Path(__file__).resolve().parent.parent
TEMPLATES = RAIZ / "templates"
CSS = RAIZ / "static" / "style.css"
UI_COMMON = RAIZ / "static" / "ui-common.js"
INICIO = TEMPLATES / "index.html"

# Este padrão já nasceu errado uma vez, e vale registrar como: a primeira versão
# era `badge-[a-z]+(?:-[a-z]+)*`, que exige letra depois do hífen. Contra
# `badge--ok` — o meu erro exato — ela não casa com NADA, e o teste passava
# verde sobre o defeito que existia para pegar. Um teste cego para o seu próprio
# caso é pior que teste nenhum: dá a garantia sem entregá-la.
#
# Agora captura o token inteiro depois de `badge`, qualquer que seja a forma:
#   badge          → a classe base, legítima
#   badge-ok       → precisa existir no CSS
#   badge--ok      → capturada, não existe, acusa
#   badgeStatus    → o `(?![\w])` recusa, é nome de função
#   notif-badge-type → o olhar-para-trás recusa, é outra família e tem CSS próprio
_CLASSE_BADGE = re.compile(r"(?<![\w-])badge(?:-[\w-]*)?(?![\w])")


def _definidas_no_css() -> Set[str]:
    return set(
        re.findall(r"(?<![\w-])\.(badge-[a-z]+(?:-[a-z]+)*)", CSS.read_text(encoding="utf-8"))
    )


def _usadas() -> Dict[str, Set[str]]:
    """Classes derivadas usadas. `badge` sozinha é a base e não precisa de sufixo."""
    fontes = sorted(TEMPLATES.glob("*.html")) + [UI_COMMON]
    usadas: Dict[str, Set[str]] = {}
    for f in fontes:
        for classe in _CLASSE_BADGE.findall(f.read_text(encoding="utf-8")):
            if classe == "badge":
                continue
            usadas.setdefault(classe, set()).add(f.name)
    return usadas


# ──────────────────────────────────────────────────────────────────────────
# 1. O geral: badge usada é badge que existe
# ──────────────────────────────────────────────────────────────────────────

def test_toda_badge_usada_existe_no_css() -> None:
    definidas = _definidas_no_css()
    faltando = {c: sorted(f) for c, f in _usadas().items() if c not in definidas}
    assert not faltando, (
        "Classes de badge usadas sem definição no style.css — renderizam como "
        f"texto cru, sem erro nenhum: {faltando}"
    )


def test_o_css_das_badges_nao_esvaziou() -> None:
    """
    Contraparte do de cima: se alguém apagar as classes do CSS, o teste acima
    passa a comparar dois conjuntos vazios e continua verde.
    """
    assert {"badge-ok", "badge-warning", "badge-bad"} <= _definidas_no_css()


# ──────────────────────────────────────────────────────────────────────────
# 2. O painel
# ──────────────────────────────────────────────────────────────────────────

def _inicio() -> str:
    return INICIO.read_text(encoding="utf-8")


def test_o_painel_nao_e_gateado_por_permissao_de_modulo() -> None:
    """
    Um operador sem permissão nenhuma no menu precisa poder cortar o acesso de
    um computador que não usa mais — a conta que está lá é a dele. Por isso o
    painel mora no Início, e a rota usa `require_auth` puro.
    """
    main = (RAIZ / "app" / "main.py").read_text(encoding="utf-8")
    trecho = main[main.index('@app.get("/api/agent/dispositivos")'):]
    trecho = trecho[: trecho.index("\n@app.")]

    assert "require_auth" in trecho
    assert "require_modulo" not in trecho
    assert "require_admin" not in trecho


# ──────────────────────────────────────────────────────────────────────────
# 3. Versão do agente na estação
# ──────────────────────────────────────────────────────────────────────────

def test_o_servidor_tambem_exige_as_duas_coisas_para_dizer_atrasado() -> None:
    """
    A tela não é a barreira: `listar` decide. Se `desatualizado` virar
    "versão != esperada" sem checar que a versão existe, toda estação muda
    aparece em vermelho — e o JS acima não teria como corrigir.
    """
    from app import agent_devices

    fonte = (RAIZ / "app" / "agent_devices.py").read_text(encoding="utf-8")
    trecho = fonte[fonte.index('item["desatualizado"]'):]
    trecho = trecho[: trecho.index("\n")]

    assert "instalada and esperada" in trecho

    linha_muda = {"versao": "", "visto_em": None, "revogado_em": None}
    assert agent_devices.esta_vivo(linha_muda) is False
