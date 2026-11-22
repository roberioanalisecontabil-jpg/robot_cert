"""Lote 3 da revisão: cargas assíncronas descartam respostas atrasadas.

Sem um contador de pedido, a resposta de um pedido antigo que chega depois
da do pedido novo sobrescreve a tela: a tabela e os filtros visíveis deixam
de bater. O projeto não tem runner de JS, então o teste lê o código: cada
`await` da função tem de ser seguido do descarte antes do próximo `await`.
"""
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

CASOS = [
    ("templates/index.html", "carregarTabela", "_pedidoTabela"),
    ("templates/historico.html", "carregarHistorico", "seqHist"),
    ("templates/dashboard.html", "carregarDashboard", "_geracao"),
    ("templates/instalador.html", "loadSieg", "_seqSieg"),
    ("static/configuracao-remocao.js", "carregarRemocao", "seqRemocao"),
    ("templates/colaborador_certificados.html", "carregarEnviados", "_seqEnviados"),
]


def _corpo(texto, nome):
    m = re.search(r"async function " + nome + r"\s*\([^)]*\)\s*\{", texto)
    assert m, nome
    i, nivel = m.end(), 1
    while nivel:
        nivel += {"{": 1, "}": -1}.get(texto[i], 0)
        i += 1
    return texto[m.end():i]


@pytest.mark.parametrize("arquivo,funcao,contador", CASOS)
def test_carga_descarta_resposta_atrasada(arquivo, funcao, contador):
    texto = (RAIZ / arquivo).read_text(encoding="utf-8")
    assert re.search(r"let " + re.escape(contador) + r"\s*=\s*0", texto), "contador não declarado"
    corpo = _corpo(texto, funcao)
    assert "++" + contador in corpo, "a função não abre um pedido novo"
    guarda = "!== " + contador
    partes = corpo.split("await ")
    assert len(partes) > 1
    for n, trecho in enumerate(partes[1:], 1):
        if partes[n - 1].endswith("throw new Error("):
            # O erro vai para o catch, que também tem de descartar.
            catch = corpo[corpo.index("catch", corpo.index(trecho)):]
            assert guarda in catch.split("}")[0], f"{funcao}: o catch do await nº {n} não descarta"
            continue
        assert guarda in trecho, f"{funcao}: o await nº {n} não descarta resposta atrasada"


def test_remocao_trava_os_botoes_enquanto_carrega():
    corpo = _corpo((RAIZ / "static/configuracao-remocao.js").read_text(encoding="utf-8"), "carregarRemocao")
    antes = corpo.split("await ")[0]
    assert 'btn-remocao-proxima").disabled = true' in antes
    assert 'btn-remocao-anterior").disabled = true' in antes


def test_remocao_erro_zera_ultima_cheia():
    corpo = _corpo((RAIZ / "static/configuracao-remocao.js").read_text(encoding="utf-8"), "carregarRemocao")
    ramo = corpo[corpo.index("if (!r.ok)"):corpo.index("const j = await r.json()")]
    assert "ultimaCheia = false" in ramo
