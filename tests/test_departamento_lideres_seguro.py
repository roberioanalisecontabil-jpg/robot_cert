"""Salvar um departamento não rebaixa gestores sem querer (revisão de
21/11/2026, P7-1). O submit mandava sempre PUT /lideres com o que estivesse
marcado no select múltiplo: um clique sem Ctrl, ou a lista de usuários vazia
(/api/users fora), apagava as lideranças, e o papel de cada gestor voltava a
operador com a carteira vazia, sem confirmação e sem como desfazer na tela."""

from __future__ import annotations

import re
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "templates" / "usuarios.html").read_text(encoding="utf-8")


def _trecho(inicio: str, fim: str) -> str:
    return HTML.split(inicio, 1)[1].split(fim, 1)[0]


def test_abrir_guarda_os_gestores_atuais_e_trava_sem_lista() -> None:
    abrir = _trecho("function abrirDep(id) {", "document.getElementById('btn-novo-departamento')")
    assert "depLideresAntes = new Set(" in abrir
    # Sem a lista de usuários, o select viria vazio: não pode valer como "nenhum gestor".
    assert re.search(r"sel\.disabled\s*=\s*!usersCache\.length", abrir)


def test_salvar_so_manda_os_gestores_quando_mudaram_e_confirma_quem_sai() -> None:
    salvar = _trecho("document.getElementById('form-dep').addEventListener('submit'", "async function apagarDep")
    assert "const mudouLideres =" in salvar and "if (mudouLideres) {" in salvar
    assert "confirmarAcao({" in salvar and "saem" in salvar
    # A confirmação vem antes de qualquer gravação (nome ou gestores).
    assert salvar.index("confirmarAcao({") < salvar.index("await fetch(")
