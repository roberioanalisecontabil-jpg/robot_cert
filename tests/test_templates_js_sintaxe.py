"""
O JS embutido nos templates precisa ao menos PARSEAR (06/10/2026).

Na Leva C uma linha foi parar dentro de um template literal e a aba Usuários
inteira parou de funcionar ("Unexpected identifier '$'") com a suíte verde:
nenhum teste lia o <script> como JavaScript. Este roda `node --check` em cada
bloco inline, com as expressões Jinja trocadas por `null`. Sem Node na
máquina, pula — não é dependência do portal.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
BLOCO = re.compile(r'<script nonce="\{\{ request\.state\.nonce \}\}">(.*?)</script>', re.S)
JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)

TEMPLATES = sorted((RAIZ / "templates").glob("*.html"))


@pytest.mark.skipif(NODE is None, reason="Node não instalado nesta máquina")
@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_script_inline_parseia(template: Path, tmp_path: Path) -> None:
    blocos = BLOCO.findall(template.read_text(encoding="utf-8"))
    for i, bloco in enumerate(blocos):
        js = tmp_path / f"{template.stem}_{i}.js"
        js.write_text(JINJA.sub("null", bloco), encoding="utf-8")
        r = subprocess.run([NODE, "--check", str(js)], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"{template.name}, bloco {i}:\n{r.stderr}"
