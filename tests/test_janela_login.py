"""
Janela de login do agente — a parte que decide, testada sem Tk.

Mesmo alcance de `test_janela_status.py`: o desenho não é testado aqui (exigiria
Windows com desktop), mas as duas funções que decidem alguma coisa são. As duas
erram em silêncio se ninguém as guardar — uma validação esperta demais recusa
credencial boa, e uma mensagem genérica deixa a pessoa sem saber o que fazer.
"""

from __future__ import annotations

import pytest

from agent.janela_login import mensagem_de_falha, validar_campos


# ──────────────────────────────────────────────────────────────────────────
# 1. Validação local: só o que dá para saber sem o portal
# ──────────────────────────────────────────────────────────────────────────

def test_campos_preenchidos_passam() -> None:
    assert validar_campos("ana@x.com", "qualquer-coisa") is None


@pytest.mark.parametrize(
    "email, senha, pedaco",
    [
        ("", "senha", "e-mail"),
        ("   ", "senha", "e-mail"),
        ("ana", "senha", "completo"),
        ("ana@", "senha", "completo"),
        ("ana@x.com", "", "senha"),
    ],
)
def test_falta_de_preenchimento_e_recusada(email: str, senha: str, pedaco: str) -> None:
    problema = validar_campos(email, senha)
    assert problema is not None
    assert pedaco in problema.lower()


def test_senha_curta_nao_e_recusada_aqui() -> None:
    """
    A regra de senha é do portal. Duplicá-la faria a janela recusar uma senha
    que o servidor aceita — e a pessoa ficaria sem saída com a credencial certa
    em mãos.
    """
    assert validar_campos("ana@x.com", "a") is None


def test_email_incomum_mas_valido_passa() -> None:
    """
    Uma expressão esperta recusaria endereços que o portal aceita. Quem decide
    se a conta existe é o servidor.
    """
    for email in ("a+tag@x.com.br", "nome.sobrenome@sub.dominio.io", "x@y.z"):
        assert validar_campos(email, "senha") is None, email


# ──────────────────────────────────────────────────────────────────────────
# 2. Mensagens: cada uma tem de terminar numa ação
# ──────────────────────────────────────────────────────────────────────────

def test_senha_errada_diz_o_que_corrigir() -> None:
    m = mensagem_de_falha(RuntimeError("E-mail ou senha incorretos."))
    assert "incorreto" in m.lower()


def test_senha_provisoria_manda_para_o_portal() -> None:
    m = mensagem_de_falha(
        RuntimeError("Troque a senha no portal antes de registrar o agente.")
    )
    assert "provisória" in m.lower() or "provisoria" in m.lower()
    assert "portal" in m.lower()


def test_conta_desativada_manda_procurar_o_admin() -> None:
    m = mensagem_de_falha(RuntimeError("Usuário desativado. Procure um administrador."))
    assert "administrador" in m.lower()


def test_falha_de_rede_nao_vira_senha_errada() -> None:
    """
    O erro que mais confunde: portal fora do ar mostrado como credencial
    inválida faz a pessoa trocar a senha à toa.
    """
    for bruto in ("timeout", "Falha ao renovar o acesso (503).", "connect error"):
        m = mensagem_de_falha(RuntimeError(bruto))
        assert "rede" in m.lower() or "portal" in m.lower()
        assert "incorret" not in m.lower()


def test_falha_do_cofre_local_e_nomeada() -> None:
    m = mensagem_de_falha(RuntimeError("CryptProtectData falhou (5)."))
    assert "windows" in m.lower()


def test_erro_desconhecido_nao_vira_texto_vazio() -> None:
    assert mensagem_de_falha(RuntimeError("")).strip() != ""
    assert mensagem_de_falha(RuntimeError("bizarrice inesperada")).strip() != ""


# ──────────────────────────────────────────────────────────────────────────
# 3. A ligação com o run_agent
# ──────────────────────────────────────────────────────────────────────────

def test_o_registro_nao_usa_o_client_do_laco() -> None:
    """
    Defeito encontrado ao ligar a janela, e que nenhum teste de comportamento
    pegaria.

    `_abrir_login` vive perto do topo de `main()`, mas o `client` do laço só
    nasce no `with _novo_http_client()`, muito abaixo — e em `tray_only` a
    função RETORNA antes disso. Capturá-lo daria `NameError` dentro da thread
    da janela, engolido pelo `except` de quem chamou: o botão "Entrar" não faria
    nada, sem erro visível, exatamente no modo que roda na estação do
    colaborador.

    Estático de propósito: exercitar isto de verdade exigiria subir o agente com
    bandeja, e o defeito é de ESCOPO — visível na árvore sintática.
    """
    import ast
    from pathlib import Path

    fonte = (Path(__file__).resolve().parent.parent / "agent" / "run_agent.py")
    arvore = ast.parse(fonte.read_text(encoding="utf-8"))

    alvo = next(
        (
            n for n in ast.walk(arvore)
            if isinstance(n, ast.FunctionDef) and n.name == "_abrir_login"
        ),
        None,
    )
    assert alvo is not None, "_abrir_login sumiu de run_agent.py"

    lidos = {
        n.id for n in ast.walk(alvo)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    }
    assert "client" not in lidos, (
        "_abrir_login voltou a capturar o `client` do laço principal, que não "
        "existe em tray_only — crie um cliente próprio com _novo_http_client()."
    )


def test_o_envio_passa_a_senha_por_parametro() -> None:
    """
    Defeito que passou por dois projetos, e que só o linter pegou.

    A primeira versão chamava `ao_registrar(email, senha)` e, num `finally`,
    fazia `del senha` — para não deixar a senha pendurada na variável de fecho.
    Em Python, `del x` dentro de uma função torna `x` LOCAL dela: a leitura na
    primeira linha passava a estourar `UnboundLocalError` ANTES de chegar ao
    portal. O `except BaseException` engolia, e a tela dizia "Não foi possível
    registrar este computador".

    **O botão Entrar nunca teria funcionado**, e a mensagem apontava para o
    lugar errado — rede ou credencial, quando o defeito era de escopo.

    Os testes de comportamento não pegavam: só `validar_campos` e
    `mensagem_de_falha` eram exercitadas, porque o resto exige Tk. Este é
    estático pelo mesmo motivo.
    """
    import ast
    import inspect

    from agent import janela_login

    # `_rodar_janela` é função de módulo: a fonte já vem na coluna 0.
    arvore = ast.parse(inspect.getsource(janela_login._rodar_janela))

    trabalho = next(
        (
            n for n in ast.walk(arvore)
            if isinstance(n, ast.FunctionDef) and n.name == "_trabalho"
        ),
        None,
    )
    assert trabalho is not None, "_trabalho sumiu de janela_login"

    assert {a.arg for a in trabalho.args.args}, (
        "_trabalho voltou a ler a senha do fecho. Passe-a como PARÂMETRO: com "
        "`del` ela vira local e a chamada anterior estoura UnboundLocalError."
    )
    assert "del " not in ast.unparse(trabalho), (
        "`del` sobre a senha torna o nome local e quebra a leitura anterior"
    )
