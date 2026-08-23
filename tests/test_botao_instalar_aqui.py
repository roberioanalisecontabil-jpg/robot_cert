"""O botão "Instalar nesta máquina" no Início.

Mesmo alcance dos outros testes de template deste projeto: a suíte lê o HTML e
não executa o JavaScript, então o que dá para guardar é a FORMA — e é onde a
regressão provável mora, porque quem reescreve a barra de seleção esquece de
levar junto uma regra que não está à vista.

O que está guardado:

  * o botão nasce escondido: quem não tem agente não pode vê-lo piscar
  * baixar o .exe NÃO sai — é a saída de quem não tem agente
  * o teto de certificados vale para os dois caminhos
  * falha ao consultar a estação degrada em silêncio, não alarma
  * a mensagem promete o que aconteceu, não o que ainda vai acontecer
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
INICIO = (RAIZ / "templates" / "index.html").read_text(encoding="utf-8")


def _funcao(nome: str) -> str:
    i = INICIO.index(f"function {nome}(")
    return INICIO[i : INICIO.index("\n      }", i)]


def test_o_botao_nasce_escondido() -> None:
    """
    Quem não tem agente nunca deve vê-lo. Nascer visível e sumir depois faria
    a barra piscar em toda carga — e ofereceria, por um instante, um caminho
    que não existe para aquela pessoa.
    """
    tag = INICIO[INICIO.index('id="btnInstalarAqui"') :]
    tag = tag[: tag.index(">")]
    assert "hidden" in tag


def test_o_download_do_exe_saiu_de_vez() -> None:
    """
    Este teste afirmava o CONTRÁRIO até 23/08/2026: que o botão de baixar devia
    ficar como caminho de exceção.

    O argumento era "máquina sem agente não recebe comando, e o .exe é como o
    agente chega na primeira vez". **Estava errado**: o agente chega pelo
    instalador do Hardlyze, distribuído por fora — o .exe de certificado nunca
    foi o caminho de instalação do agente.

    Sem esse furo, sobra a razão de remover: dois caminhos para emitir token de
    instalação são duas superfícies para a entrega de uma chave privada, e o
    menos usado é o menos observado.
    """
    assert "btnBaixarSel" not in INICIO
    assert "preparar-download" not in INICIO
    assert "baixarSelecionados" not in INICIO


def test_quem_nao_tem_agente_recebe_instrucao_e_nao_silencio() -> None:
    """
    Antes, sem agente, a pessoa caía no download. Sem ele, um botão escondido e
    mais nada deixaria a tela muda — e ela não teria como saber o que fazer.
    """
    assert 'id="semAgente"' in INICIO
    assert "Hardlyze Agent" in INICIO


def test_o_teto_de_certificados_desabilita_o_botao() -> None:
    """
    O limite é do servidor. Deixar o botão habilitado convidaria a um 422 que a
    tela já sabia evitar.
    """
    assert 'document.getElementById("btnInstalarAqui").disabled = excedeu' in INICIO


def test_falha_ao_consultar_a_estacao_nao_alarma() -> None:
    """
    Sem agente a pessoa usa o download, que é o que ela já fazia. Um toast de
    erro assustaria por causa de um caminho opcional que ela talvez nem use.
    """
    corpo = _funcao("carregarMinhaEstacao")
    captura = corpo[corpo.index("catch") :]
    assert "showToast" not in captura
    assert "_estacao = null" in captura


def test_a_mensagem_nao_promete_instalacao_concluida() -> None:
    """
    Quem instala é o agente, em segundos. Dizer "instalado" faria a pessoa
    achar que falhou quando o certificado demorasse dez segundos — e conferir
    no navegador algo que ainda não chegou lá.
    """
    corpo = _funcao("instalarNaEstacao")
    sucesso = re.search(r'showToast\(\s*"([^"]+)"', corpo)
    assert sucesso, "sumiu o aviso de sucesso"
    texto = sucesso.group(1).lower()
    assert "enviado" in texto
    assert "instalado" not in texto


def test_manda_a_maquina_junto_do_pedido() -> None:
    """Sem `machine_id` o servidor recusa com 400 — e a tela sabe qual é."""
    corpo = _funcao("instalarNaEstacao")
    assert "machine_id: _estacao.machine_id" in corpo
    assert "/api/cert-installer/prepare" in corpo


def test_a_selecao_e_limpa_so_depois_do_sucesso() -> None:
    """
    Limpar antes perderia a escolha da pessoa se o pedido falhasse — e ela
    teria de remarcar tudo para tentar de novo.
    """
    corpo = _funcao("instalarNaEstacao")
    assert corpo.index("showToast") < corpo.index("_selecao.clear()")
    catch = corpo[corpo.index("} catch") :]
    assert "_selecao.clear()" not in catch
