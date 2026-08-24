"""A identidade por dispositivo está DORMENTE — e isso é um fato, não um bug.

Estes testes prendem o que foi apurado em 24/08/2026, para que a nota em
`app/agent_devices.py` e `agent/identidade.py` não vire ficção sem ninguém ver.

── O achado ──────────────────────────────────────────────────────────────

A credencial do dispositivo é gravada em `%LOCALAPPDATA%`, cifrada com **DPAPI
de usuário**. Quem faz todas as chamadas autenticadas do agente — `/api/ingest`,
upload de PFX, configurações — é o **serviço Windows, como LocalSystem**, que
não decifra o blob de outra conta. A bandeja, que alcançaria o arquivo, não faz
chamada autenticada nenhuma além do próprio registro.

Logo: fazer o login hoje grava um segredo que nada lê. `_headers()` continua
mandando `X-API-Key`.

── Por que travar isso num teste ─────────────────────────────────────────

Porque a correção parece de uma linha. Alguém que abra `_headers()` e veja a
chave compartilhada vai querer trocá-la pela credencial do dispositivo — e o
resultado seria o agente do ANALISESRV parar de autenticar, em silêncio, porque
o serviço não consegue ler o arquivo. O sintoma chegaria como 401 no ingest, e
o cofre pararia de ser alimentado.

**Estes testes devem ser APAGADOS quando a credencial de MÁQUINA existir** — a
que vive em `ProgramData` e o serviço alcança. Eles existem para essa troca ser
uma decisão, e não um efeito colateral de quem passou por perto.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _fonte_do_agente() -> str:
    return (RAIZ / "agent" / "run_agent.py").read_text(encoding="utf-8")


def test_headers_do_agente_ainda_usa_a_chave_compartilhada() -> None:
    """
    Trocar por `identidade` aqui derruba o ingest: quem chama é LocalSystem.

    Se este teste falhou porque você fez a credencial de MÁQUINA, apague-o —
    ele cumpriu a função. Se falhou porque você trocou pela credencial da
    PESSOA, leia a nota em `agent/identidade.py`: não vai funcionar no serviço.
    """
    fonte = _fonte_do_agente()
    inicio = fonte.index("def _headers()")
    corpo = fonte[inicio : fonte.index("\n    _start_tray()", inicio)]

    assert "X-API-Key" in corpo, (
        "_headers() deixou de mandar X-API-Key. Se foi para usar a credencial do "
        "dispositivo, o serviço (LocalSystem) não consegue lê-la — ver a nota em "
        "agent/identidade.py."
    )
    assert "identidade" not in corpo, (
        "_headers() passou a ler a identidade do dispositivo. Ela mora no perfil "
        "do usuário, cifrada com DPAPI, e quem chama isto é o serviço."
    )


def test_a_sessao_de_dispositivo_nao_tem_consumidor_no_agente() -> None:
    """
    `identidade.Sessao` troca o segredo por JWT curto. Ninguém a instancia.

    Documentado num teste porque "não tem consumidor" é a única razão pela qual
    a tabela estar vazia em produção NÃO é defeito — e é uma afirmação que
    envelhece sozinha se ninguém a conferir.
    """
    fonte = _fonte_do_agente()
    arvore = ast.parse(fonte)

    usos = [
        no
        for no in ast.walk(arvore)
        if isinstance(no, ast.Attribute) and no.attr == "Sessao"
    ]
    assert not usos, (
        "alguém passou a usar identidade.Sessao no agente; a nota sobre a "
        "identidade dormente em app/agent_devices.py precisa ser reescrita"
    )


def test_o_registro_continua_possivel_pela_bandeja() -> None:
    """
    Dormente não é removido. O registro em si funciona, e o item de menu fica.

    Se a fase 2 voltar — a pessoa agindo pelo agente na sessão dela — é por aqui
    que ela entra. Tirar o menu tornaria a volta mais cara do que precisa.
    """
    fonte = _fonte_do_agente()
    assert "Entrar no portal" in fonte
    assert "identidade.registrar(" in fonte


def test_a_credencial_mora_no_perfil_do_usuario() -> None:
    """
    É esta escolha que a torna inalcançável pelo serviço — e ela está certa:
    o segredo É a pessoa, e em ProgramData qualquer conta local o leria.

    O teste existe para amarrar a causa ao efeito. Sem ele, alguém "conserta" o
    caminho movendo o arquivo para ProgramData, o serviço passa a ler, e a
    credencial da pessoa vira credencial de máquina sem ninguém decidir isso.
    """
    from agent import identidade

    fonte = inspect.getsource(identidade.caminho)
    assert "LOCALAPPDATA" in fonte
    assert "ProgramData" not in fonte, (
        "a credencial da PESSOA foi movida para um diretório da MÁQUINA; "
        "isso a expõe a qualquer conta local — ver o cabeçalho de identidade.py"
    )


def test_a_nota_sobre_o_estado_dormente_continua_no_lugar() -> None:
    """
    Os dois módulos precisam carregar o achado. Quem chega a um deles não
    necessariamente passa pelo outro, e a conclusão só faz sentido inteira.
    """
    servidor = (RAIZ / "app" / "agent_devices.py").read_text(encoding="utf-8")
    agente = (RAIZ / "agent" / "identidade.py").read_text(encoding="utf-8")

    assert "DORMENTE" in servidor
    assert "LocalSystem" in servidor and "LocalSystem" in agente
    assert "ProgramData" in servidor, "falta dizer o que revive o módulo"
