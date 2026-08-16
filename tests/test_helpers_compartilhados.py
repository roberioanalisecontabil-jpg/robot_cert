"""Helpers compartilhados entre `static/ui-common.js` e os templates.

**Escrito depois de um defeito que 500 testes deixaram passar.**

Em 16/08/2026 três telas — `dashboard.html`, `carteiras.html` e os painéis
novos de `instalador.html` — **usavam `esc()` sem que nada a definisse**. A
função estava duplicada em seis outros templates e não existia em
`ui-common.js`. Toda função de render dessas três telas chamava `esc()` e
estourava `ReferenceError` no navegador: as páginas subiram quebradas em
produção.

A suíte não pegou porque **lê o HTML de origem e nunca executa o JavaScript**.
É a limitação que eu já tinha reconhecido em outro teste ("garante a forma, não
o comportamento") — e ela cobrou.

**O alcance deste arquivo é deliberadamente estreito.** Não é um linter de
JavaScript: identificar toda referência indefinida exigiria um parser de
verdade, e tentar isso com expressão regular gera falso positivo em cada
`"1 certificado(s)"` e `var(--token)` dentro de string. O que ele faz é
verificar os helpers que `ui-common.js` publica — que é exatamente a classe do
defeito: página que chama um helper compartilhado que não está lá.
"""

import re
from pathlib import Path
from typing import Set

import pytest

RAIZ = Path(__file__).resolve().parent.parent
UI_COMMON = RAIZ / "static" / "ui-common.js"
TEMPLATES = RAIZ / "templates"


def _paginas():
    """Templates com script próprio. O partial da sidebar não tem."""
    return [
        f for f in sorted(TEMPLATES.glob("*.html"))
        if f.name != "_sidebar.html" and "<script" in f.read_text(encoding="utf-8")
    ]


def _helpers_publicados() -> Set[str]:
    """Funções de topo de `ui-common.js`, sem as privadas (prefixo `_`)."""
    src = UI_COMMON.read_text(encoding="utf-8")
    return {n for n in re.findall(r"^function\s+(\w+)\s*\(", src, re.M) if not n.startswith("_")}


def _script_da_pagina(f: Path) -> str:
    return "\n".join(
        re.findall(r"<script[^>]*>(.*?)</script>", f.read_text(encoding="utf-8"), re.DOTALL)
    )


# ──────────────────────────────────────────────────────────────────────────
# 1. O defeito exato
# ──────────────────────────────────────────────────────────────────────────

def test_esc_existe_em_ui_common() -> None:
    """
    `esc` escapa dado que vem do CN do certificado — controlado por quem gera o
    `.pfx`. A CSP com nonce bloqueia script inline, mas markup injetado ainda
    desfigura a tela, e depender só da CSP é ter uma camada de defesa.
    """
    assert re.search(r"^function esc\(", UI_COMMON.read_text(encoding="utf-8"), re.M)


def test_nenhum_template_redefine_helper_compartilhado() -> None:
    """
    Redefinir local sombreia o compartilhado e as duas versões divergem em
    silêncio — foi assim que `esc` acabou em seis cópias enquanto três telas
    ficavam sem nenhuma.
    """
    publicados = _helpers_publicados()
    reincidentes = []
    for f in _paginas():
        locais = set(re.findall(r"function\s+(\w+)\s*\(", _script_da_pagina(f)))
        for nome in sorted(locais & publicados):
            reincidentes.append(f"{f.name}:{nome}")
    assert not reincidentes, (
        f"helper compartilhado redefinido localmente: {reincidentes} — "
        "use o de ui-common.js ou renomeie o local"
    )


@pytest.mark.parametrize("pagina", [f.name for f in _paginas()])
def test_helper_usado_esta_disponivel(pagina: str) -> None:
    """
    Todo helper de `ui-common.js` chamado pela página tem de estar lá.

    É o teste que teria pegado o defeito de 16/08: `dashboard.html` chamava
    `esc()` 5 vezes, `carteiras.html` 16 e `instalador.html` 22, e nenhuma das
    três tinha a função ao alcance.
    """
    f = TEMPLATES / pagina
    corpo = _script_da_pagina(f)
    publicados = _helpers_publicados()

    usados = {
        n for n in re.findall(r"(?<![.\w$])([a-zA-Z_$][\w$]*)\s*\(", corpo)
        if n in publicados
    }
    locais = set(re.findall(r"function\s+(\w+)\s*\(", corpo))
    indisponiveis = sorted(usados - publicados - locais)
    assert not indisponiveis, f"{pagina} chama {indisponiveis}, que ninguém define"


def test_ui_common_carrega_antes_do_script_da_pagina() -> None:
    """
    Ordem importa: o script inline roda na hora, e um helper ainda não
    carregado é `ReferenceError` — o mesmo sintoma, por outra causa.
    """
    for f in _paginas():
        html = f.read_text(encoding="utf-8")
        pos_comum = html.find("ui-common.js")
        if pos_comum == -1:
            # Só o login não usa nada de ui-common.js.
            assert f.name == "login.html", f"{f.name} não carrega ui-common.js"
            continue

        # O script da página é o primeiro `<script>` SEM `src` — algumas telas
        # carregam o ui-common.js com `nonce` também, e procurar por `<script
        # nonce=` casaria com a própria tag do arquivo externo.
        inline = [
            m.start() for m in re.finditer(r"<script(?![^>]*\ssrc=)[^>]*>", html)
        ]
        assert inline, f"{f.name}: script da página não encontrado"
        assert pos_comum < inline[0], f"{f.name}: ui-common.js depois do script da página"


# ──────────────────────────────────────────────────────────────────────────
# 2. Escape onde o dado é de terceiro
# ──────────────────────────────────────────────────────────────────────────

def test_render_empty_state_escapa_o_que_interpola() -> None:
    """
    Achado M8 da auditoria de 02/08. `showToast` já usava `textContent`;
    `renderEmptyState` montava `innerHTML` com título e descrição crus.
    """
    src = UI_COMMON.read_text(encoding="utf-8")
    bloco = src[src.index("function renderEmptyState") :]
    bloco = bloco[: bloco.index("\n}")]
    for campo in ("title", "description", "actionText"):
        assert f"esc({campo})" in bloco, f"{campo} entra no innerHTML sem escape"


# ──────────────────────────────────────────────────────────────────────────
# 3. Tokens CSS: usar um que não existe falha em silêncio
# ──────────────────────────────────────────────────────────────────────────

def test_templates_so_usam_tokens_que_existem() -> None:
    """
    `var(--x)` sem fallback, com `--x` inexistente, faz o navegador **descartar
    a declaração inteira** — a cor simplesmente não é aplicada, sem erro. Com
    fallback é pior ainda: aplica o fallback e parece funcionar.

    Dois casos reais em 16/08:

    - `.role-gestor` usava `var(--expiring-bg, var(--ok-bg))`. O token nunca
      existiu (o certo é `--warning-bg`), então o badge GESTOR ficava
      **idêntico ao de usuário comum**.
    - `usuarios.html` pintava mensagens de erro com `var(--danger)`, sem
      fallback. O token é `--danger-text`; a declaração era descartada e o erro
      saía na cor normal do texto.
    """
    css = (RAIZ / "static" / "style.css").read_text(encoding="utf-8")
    definidos = set(re.findall(r"(--[a-z0-9-]+)\s*:", css))
    assert definidos, "nenhum token encontrado no style.css"

    faltando = {}
    for f in sorted(TEMPLATES.glob("*.html")):
        usados = set(re.findall(r"var\((--[a-z0-9-]+)", f.read_text(encoding="utf-8")))
        fora = sorted(usados - definidos)
        if fora:
            faltando[f.name] = fora
    assert not faltando, f"tokens usados e nunca definidos: {faltando}"
