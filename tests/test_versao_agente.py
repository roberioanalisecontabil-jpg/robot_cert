"""
A versão do agente vive em dois lugares que não conversam.

`agent/__init__.py` é a fonte que o código lê (e que a janela de status
exibe); `agent_setup.iss` declara `AppVersion`, que é o que o Windows mostra
em "Aplicativos instalados" e o que o Inno usa para decidir atualização. O
Inno não consegue importar Python, então a duplicação é inevitável — o que
este teste evita é que ela vire divergência.

O modo de falha é silencioso e caro: a janela diria 1.1.0 enquanto o Painel de
Controle diz 1.0.1, e a pergunta "qual versão está instalada nesta máquina?"
passaria a ter duas respostas — justamente durante um diagnóstico.
"""

import re
from pathlib import Path

import agent

RAIZ = Path(__file__).resolve().parents[1]


def test_versao_do_pacote_e_do_instalador_batem() -> None:
    iss = (RAIZ / "agent_setup.iss").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^AppVersion=(.+)$", iss, re.MULTILINE)

    assert m, "AppVersion não encontrada em agent_setup.iss"
    assert m.group(1).strip() == agent.__version__, (
        f"agent_setup.iss diz AppVersion={m.group(1).strip()} mas "
        f"agent.__version__ é {agent.__version__} — atualize os dois"
    )


def test_versao_tem_formato_utilizavel() -> None:
    """O Inno recusa AppVersion fora de x.y[.z]; falhar aqui é melhor que no build."""
    assert re.fullmatch(r"\d+\.\d+(\.\d+)?", agent.__version__), agent.__version__
