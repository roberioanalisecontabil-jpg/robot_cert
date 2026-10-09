"""O código das rotas do portal, para os testes que varrem TODAS as rotas.

Desde a Frente 3 (09/10/2026) as rotas saem de `app/main.py` para
`app/rotas/*.py`, e a sessão, o alcance e as utilidades para módulos
próprios. Um teste estrutural que lesse só `main.py` passaria a não ver as
rotas que saíram — e passaria por vácuo, sem proteger nada.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List

RAIZ = Path(__file__).resolve().parent.parent


def arquivos() -> List[Path]:
    app = RAIZ / "app"
    return [app / "main.py", app / "sessao.py", app / "alcance.py", app / "comum.py",
            *sorted((app / "rotas").glob("*.py"))]


def texto() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in arquivos())


def arvores() -> List[ast.Module]:
    return [ast.parse(p.read_text(encoding="utf-8")) for p in arquivos()]
