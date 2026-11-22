"""Cada aba de Configuração salva só o que é dela (revisão de 21/11/2026, P8-1).

Salvar Remoção, Pastas, o bloco de e-mail ou o modal do texto montava o corpo do
PUT lendo o DOM das OUTRAS abas: uma edição abandonada (o usuário SMTP digitado
e não salvo) ia junto, e trocar o destino zera a senha guardada — os alertas
paravam em silêncio. Agora os campos que não são da aba vêm do último
/api/settings salvo (_settingsSalvos)."""

from __future__ import annotations

from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "templates" / "configuracao.html").read_text(encoding="utf-8")

PASTAS = ("inp-source", "inp-exp", "inp-machine")
SMTP = ("inp-smtp-host", "inp-smtp-port", "inp-smtp-user", "inp-smtp-from", "chk-smtp-alerts-enabled")


def _trecho(inicio: str, fim: str) -> str:
    return HTML.split(inicio, 1)[1].split(fim, 1)[0]


def _le(trecho: str, ids) -> list:
    return [i for i in ids if f'getElementById("{i}")' in trecho]


def test_remocao_nao_le_as_outras_abas() -> None:
    corpo = _trecho("async function salvarRemocao()", "document.getElementById(\"btn-remocao-salvar\")")
    assert _le(corpo, PASTAS + SMTP) == [] and "corpoBaseSalvo()" in corpo


def test_pastas_nao_le_o_smtp() -> None:
    corpo = _trecho('document.getElementById("btn-save-cfg").addEventListener', "// ── Salvar remoção")
    assert _le(corpo, SMTP) == [] and "inp-smtp-pass" not in corpo and "corpoBaseSalvo()" in corpo


def test_email_nao_le_as_pastas() -> None:
    corpo = _trecho('document.getElementById("btn-save-smtp").addEventListener', "function resultadoTeste(")
    assert _le(corpo, PASTAS) == [] and "corpoBaseSalvo()" in corpo


def test_modal_do_texto_nao_le_as_outras_abas() -> None:
    corpo = _trecho('document.getElementById("form-email").addEventListener("submit"', "dlgEmail.close();")
    assert _le(corpo, PASTAS + SMTP) == [] and "corpoBaseSalvo()" in corpo


def test_o_salvo_e_atualizado_a_cada_leitura_e_gravacao() -> None:
    assert "_settingsSalvos = s;" in _trecho("async function loadSettingsToForm()", "preencherGraph(s);")
