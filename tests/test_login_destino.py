"""Para onde o login manda depois de entrar (auditoria de 10/10/2026).

`destinoAposLogin` validava o `?next=` com uma regex que recusava `//host` mas
aceitava `/\\host`. O parser de URL do navegador trata a barra invertida como
barra em http(s), então `/\\evil.example` virava `//evil.example` — e o portal
mandava a pessoa para outro site, sozinho, se ela já tivesse sessão
(achado robot_cert/templates/login.html:destinoAposLogin:backslash-open-redirect).

O teste roda a função DO TEMPLATE no Node, que usa o mesmo parser de URL do
navegador (WHATWG). Testar uma cópia da regex em Python provaria a cópia.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

LOGIN = Path(__file__).resolve().parent.parent / "templates" / "login.html"
NODE = shutil.which("node")


def _funcao() -> str:
    html = LOGIN.read_text(encoding="utf-8")
    m = re.search(r"function destinoAposLogin\(\) \{.*?\n        \}\n", html, re.S)
    assert m, "destinoAposLogin não encontrada no login.html"
    return m.group(0)


def _destinos(nexts):
    script = (
        "const location = { origin: 'https://certificado.exemplo', search: '' };\n"
        + _funcao()
        + "const saida = [];\n"
        + f"for (const n of {json.dumps(nexts)}) {{\n"
        + "  location.search = '?' + new URLSearchParams({ next: n }).toString();\n"
        + "  saida.push(destinoAposLogin());\n"
        + "}\n"
        + "console.log(JSON.stringify(saida));\n"
    )
    r = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(NODE is None, reason="node não está no PATH")
def test_next_para_fora_do_portal_vai_para_o_inicio() -> None:
    fora = ["/\\evil.example", "/\\/evil.example", "//evil.example", "https://evil.example/",
            "\\\\evil.example", "javascript:alert(1)", " /\\evil.example",
            # Auditoria run-2 (12/10/2026): o caminho normalizado de "/.//host"
            # é "//host" — a origem confere, mas o texto devolvido é um URL
            # sem esquema que leva para fora.
            "/.//evil.example", "/..//evil.example", "/.\\/evil.example", "/./\\evil.example"]
    assert _destinos(fora) == ["/"] * len(fora)


@pytest.mark.skipif(NODE is None, reason="node não está no PATH")
def test_next_do_proprio_portal_e_preservado() -> None:
    dentro = ["/carteiras?operador=x#lista", "/instalador?aba=trilha", "/"]
    assert _destinos(dentro) == dentro


@pytest.mark.skipif(NODE is None, reason="node não está no PATH")
def test_next_para_o_proprio_login_vai_para_o_inicio() -> None:
    assert _destinos(["/login", "/login?next=/x"]) == ["/", "/"]
