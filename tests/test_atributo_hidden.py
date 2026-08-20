"""O atributo `hidden` só esconde se o CSS deixar.

`[hidden] { display: none }` vem da folha do navegador e tem especificidade
ZERO: qualquer regra `.foo { display: flex }` a vence, e o atributo passa a não
fazer absolutamente nada. O elemento continua desenhado, o código que o
"escondeu" não dá erro, e só quem olha a tela percebe.

Este projeto remendou isso três vezes, uma classe por vez — `.barra-selecao`,
`.dup-path-tooltip` e os cards do painel. Da quarta a vítima foi o campo
"Senha inicial" do modal de usuários, que aparecia ao EDITAR alguém: havia
`hidden = true` no JS e um comentário explicando o porquê, e a linha nunca teve
efeito. Medido no navegador: `offsetHeight` de 68px com o atributo presente.

A correção é uma regra global com `!important`. Estes testes existem para que
ela não seja removida por parecer exagero — e para dizer, se for, exatamente
quais telas voltam a quebrar.
"""

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
CSS_PATH = RAIZ / "static" / "style.css"
TEMPLATES = RAIZ / "templates"


@pytest.fixture(scope="module")
def css() -> str:
    """CSS sem comentários — a prosa explicativa não é regra."""
    return re.sub(r"/\*.*?\*/", "", CSS_PATH.read_text(encoding="utf-8"), flags=re.S)


def _regras(css: str):
    return re.findall(r"([^{}]+)\{([^}]*)\}", css)


def _esconde_globalmente(css: str) -> bool:
    """Existe `[hidden] { display: none !important }` sem depender de classe?

    O `!important` faz parte da asserção: sem ele a regra empata em
    especificidade com qualquer classe e perde por ordem de declaração — ou
    seja, não resolveria nada.
    """
    for seletores, corpo in _regras(css):
        partes = [p.strip() for p in seletores.split(",")]
        if not any(p == "[hidden]" for p in partes):
            continue
        if re.search(r"display\s*:\s*none\s*!important", corpo):
            return True
    return False


def _classes_com_display(css: str) -> set[str]:
    """Classes cuja regra declara `display` — as que venceriam o `[hidden]`.

    `display: none` não entra: uma classe que já esconde não deixa nada visível.
    """
    out: set[str] = set()
    for seletores, corpo in _regras(css):
        if "[hidden]" in seletores:
            continue
        m = re.search(r"(?<![-\w])display\s*:\s*([\w-]+)", corpo)
        if not m or m.group(1) == "none":
            continue
        out |= set(re.findall(r"\.([A-Za-z_][\w-]*)", seletores))
    return out


def _classes_com_override_proprio(css: str) -> set[str]:
    """Classes que reafirmam `display: none` para o próprio `[hidden]`."""
    out: set[str] = set()
    for seletores, corpo in _regras(css):
        if "[hidden]" not in seletores or not re.search(r"display\s*:\s*none", corpo):
            continue
        for parte in seletores.split(","):
            if "[hidden]" in parte:
                out |= set(re.findall(r"\.([A-Za-z_][\w-]*)", parte))
    return out


def _classes_de(tag: str) -> set[str]:
    m = re.search(r'class\s*=\s*"([^"]*)"', tag)
    return set(m.group(1).split()) if m else set()


def _classes_que_usam_hidden(html: str) -> set[str]:
    """Classes de elementos escondidos por `hidden`, no HTML ou via JS."""
    out: set[str] = set()

    # 1. `hidden` escrito na tag, como atributo booleano — nunca `hidden="..."`,
    #    que em Jinja é outra coisa.
    for tag in re.findall(r"<[a-zA-Z][^>]*>", html):
        if re.search(r"(?<![-\w])hidden(?![-\w=])", tag):
            out |= _classes_de(tag)

    # 2. `getElementById("x").hidden = ...`. É o caso em que o defeito passa
    #    despercebido por mais tempo: na primeira renderização estava certo.
    ids = set(re.findall(r'getElementById\(\s*[\'"]([\w-]+)[\'"]\s*\)\s*\.hidden\b', html))
    for var, elem_id in re.findall(
        r'(\w+)\s*=\s*document\.getElementById\(\s*[\'"]([\w-]+)[\'"]\s*\)', html
    ):
        if re.search(re.escape(var) + r"\.hidden\s*=", html):
            ids.add(elem_id)

    for elem_id in ids:
        m = re.search(r'<[a-zA-Z][^>]*\bid\s*=\s*"' + re.escape(elem_id) + r'"[^>]*>', html)
        if m:
            out |= _classes_de(m.group(0))

    return out


def test_existe_uma_regra_global_de_hidden(css: str) -> None:
    """A causa, travada onde ela mora."""
    assert _esconde_globalmente(css), (
        "Sem `[hidden] { display: none !important }` global, o atributo volta a "
        "perder para qualquer classe que declare `display`."
    )


def test_nenhuma_tela_fica_com_hidden_sem_efeito(css: str) -> None:
    """A consequência, listada por tela.

    Se a regra global sumir, esta falha diz quais elementos passam a ser
    desenhados mesmo marcados como escondidos — em vez de deixar a descoberta
    para quem abrir a página.
    """
    if _esconde_globalmente(css):
        return

    com_display = _classes_com_display(css)
    com_override = _classes_com_override_proprio(css)

    faltando: dict[str, set[str]] = {}
    for tpl in sorted(TEMPLATES.glob("*.html")):
        html = tpl.read_text(encoding="utf-8")
        for cls in _classes_que_usam_hidden(html):
            if cls in com_display and cls not in com_override:
                faltando.setdefault(tpl.name, set()).add(cls)

    assert not faltando, (
        "Elementos marcados com `hidden` que o CSS continua desenhando:\n"
        + "\n".join(f"  {arq}: {sorted(cs)}" for arq, cs in sorted(faltando.items()))
    )


def test_o_campo_de_senha_so_existe_no_cadastro(css: str) -> None:
    """O caso concreto que a varredura encontrou.

    `.modal__campo` é `display: flex`, e o campo "Senha inicial" nasce com
    `hidden` para aparecer apenas em "Novo usuário". Sem a regra global ele é
    desenhado também na edição — onde digitar uma senha nova não faz nada,
    porque o `PUT` sequer envia o campo. A tela oferecia uma ação inexistente e
    respondia "Usuário atualizado".
    """
    html = (TEMPLATES / "usuarios.html").read_text(encoding="utf-8")
    assert re.search(r'id="ed-campo-senha"[^>]*\bhidden\b', html), (
        "O campo de senha precisa nascer escondido: o modal é compartilhado "
        "entre cadastro e edição."
    )
    assert "modal__campo" in _classes_com_display(css)
    assert _esconde_globalmente(css)
