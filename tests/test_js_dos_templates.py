"""O JavaScript embutido nos templates precisa compilar.

Em 21/08 a página /duplicidades não renderizava **nada**. A causa estava no ar
desde 17/08: um comentário HTML dentro de uma template literal, com crases em
volta de `tabindex="0"`.

    return `
      <!-- `tabindex="0"` põe a linha na ordem de Tab... -->
      <tr ...>`

Crase dentro de template literal **fecha a string**. O `<script>` inteiro
deixava de compilar, e o sintoma era a tela em branco — sem erro visível para
quem só abre a página, e sem relação aparente com um comentário.

Nenhum teste pegava porque todos os 800 testam o SERVIDOR: o HTML era servido
com status 200 e o conteúdo certo. O que estava quebrado só existia depois,
no navegador.

Este teste compila o JS de cada template com `node --check`. Quatro dias de
página morta é o custo de não ter isto.
"""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
NODE = shutil.which("node")

# Jinja dentro do JS não é JavaScript. Trocado por um literal do mesmo "tipo"
# para o parser seguir: o que se quer verificar é a sintaxe do JS em volta.
RE_JINJA_EXPR = re.compile(r"\{\{.*?\}\}", re.S)
RE_JINJA_TAG = re.compile(r"\{%.*?%\}", re.S)
RE_SCRIPT = re.compile(
    r"<script\b(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I
)


def _scripts_de(html: str):
    for m in RE_SCRIPT.finditer(html):
        corpo = m.group(1)
        if not corpo.strip():
            continue
        linha = html[: m.start()].count("\n") + 1
        limpo = RE_JINJA_EXPR.sub('"JINJA"', corpo)
        limpo = RE_JINJA_TAG.sub("", limpo)
        yield linha, limpo


@pytest.mark.skipif(NODE is None, reason="node não está no PATH")
@pytest.mark.parametrize(
    "template", sorted(p.name for p in TEMPLATES.glob("*.html"))
)
def test_o_javascript_do_template_compila(template: str) -> None:
    html = (TEMPLATES / template).read_text(encoding="utf-8")
    for linha, js in _scripts_de(html):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".js", delete=False, encoding="utf-8"
        ) as f:
            f.write(js)
            caminho = f.name
        try:
            r = subprocess.run(
                [NODE, "--check", caminho], capture_output=True, text=True, timeout=30
            )
        finally:
            Path(caminho).unlink(missing_ok=True)

        assert r.returncode == 0, (
            f"{template}: o <script> que começa na linha {linha} não compila.\n"
            f"A página renderiza em branco no navegador e o servidor não acusa nada.\n"
            f"{r.stderr[:600]}"
        )


@pytest.mark.skipif(NODE is None, reason="node não está no PATH")
def test_nenhum_comentario_html_dentro_de_template_literal() -> None:
    """A forma exata do defeito de 17/08, travada por si.

    O `node --check` acima já pega o caso com crase. Este pega o padrão ANTES
    de ele ter crase: comentário HTML dentro de uma template literal é uma
    armadilha esperando alguém escrever `código` no meio dele — e é justamente
    onde a voz deste projeto (que explica o porquê de tudo) leva a mão.
    """
    achados = []
    for p in sorted(TEMPLATES.glob("*.html")):
        html = p.read_text(encoding="utf-8")
        for linha, js in _scripts_de(html):
            # Template literals do script, com o comentário HTML dentro.
            for m in re.finditer(r"`[^`]*<!--.*?-->[^`]*`", js, re.S):
                achados.append(
                    f"{p.name}: <script> da linha {linha}, "
                    f"trecho {m.group(0)[:60]!r}"
                )
    assert not achados, (
        "Comentário HTML dentro de template literal — escreva-o como comentário "
        "de JS, acima do `return`:\n  " + "\n  ".join(achados)
    )
