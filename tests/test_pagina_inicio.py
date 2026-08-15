"""Invariantes da página Início (a antiga "Dashboard").

O rótulo mudou em 15/08/2026 para abrir espaço a um Dashboard de verdade — de
análise, não de operação (`docs/PLANO_reorganizacao_portal.md`, etapa 4). Os dois
testes daqui guardam as duas metades da renomeação:

- **o rótulo mudou** onde o usuário lê;
- **o nome interno NÃO mudou** onde mudá-lo custaria dado.

A segunda metade é a que engana. Renomear `cg_per_page_dashboard` junto com o
rótulo parece arrumação — e descarta, sem aviso e sem erro, a preferência de
itens por página de todo mundo que já usou o portal. O `localStorage` é do
navegador do usuário: não há migração, o valor antigo simplesmente deixa de ser
encontrado e a tela volta ao padrão.
"""

import re
from pathlib import Path

from fastapi.testclient import TestClient

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def test_menu_diz_inicio_e_nao_dashboard(client: TestClient) -> None:
    """O item de `/` no menu lateral é "Início"."""
    r = client.get("/")
    assert r.status_code == 200

    nav = re.search(r'<nav class="sidebar-nav">.*?</nav>', r.text, re.DOTALL)
    assert nav, "página sem navegação lateral"
    itens = re.findall(r"<a [^>]*>(.*?)</a>", nav.group(0), re.DOTALL)
    rotulos = [re.sub(r"<[^>]+>", "", i).strip() for i in itens]

    assert "Início" in rotulos, f"rótulos: {rotulos}"
    assert "Dashboard" not in rotulos, (
        "'Dashboard' voltou ao menu — o nome está reservado para a página de "
        "análise da etapa 4, e dois itens com esse nome seriam ambíguos"
    )


def test_chave_de_localstorage_preservada() -> None:
    """
    `cg_per_page_dashboard` não acompanha a renomeação.

    Mudá-la descartaria a preferência de itens por página de todo usuário que já
    abriu o portal — silenciosamente, porque a leitura de uma chave inexistente
    apenas devolve null e a tela cai no padrão. Nome interno e rótulo não
    precisam concordar; aqui, concordar custa caro.
    """
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    assert '"cg_per_page_dashboard"' in html, (
        "a chave de localStorage foi renomeada — isso apaga a preferência "
        "de itens por página dos usuários existentes"
    )
