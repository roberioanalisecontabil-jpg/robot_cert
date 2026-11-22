"""Troca rápida de pessoa em Carteiras > Pessoas (revisão de 21/11/2026, P5-2).

carregarCarteira e carregarHistorico gravavam o estado sem conferir se a pessoa
ainda era a mesma: clicar em A e logo em B, com a resposta de A atrasada,
mostrava a carteira de A sob o nome de B, e Atribuir/Retirar iam para B.
removerVarios relia _selecionado.id a cada volta do laço."""

from __future__ import annotations

import re
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "templates" / "carteiras.html").read_text(encoding="utf-8")


def _funcao(nome: str) -> str:
    ini = HTML.index(f"async function {nome}(")
    prox = re.search(r"\n    (async )?function ", HTML[ini + 10:])
    return HTML[ini: ini + 10 + prox.start()]


def test_cargas_descartam_resposta_de_outra_pessoa() -> None:
    for nome in ("carregarCarteira", "carregarHistorico"):
        f = _funcao(nome)
        assert "const alvo = _selecionado && _selecionado.id;" in f, nome
        # Depois de cada await e no catch: resposta de outra pessoa não pinta a tela.
        assert f.count("if (!_selecionado || _selecionado.id !== alvo) return;") >= 3, nome


def test_retirar_em_lote_fixa_a_pessoa_antes_do_laco() -> None:
    f = _funcao("removerVarios")
    laco = f[f.index("for (const doc of documentos)"):]
    assert "const alvo = _selecionado.id;" in f[:f.index("for (const doc of documentos)")]
    assert "_selecionado.id" not in laco.split("msg(")[0]
