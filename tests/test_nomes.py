"""`nome_exibicao` e `nome_pessoa`: tudo em maiúsculas (decisão de 30/09/2026).

Até então o módulo fazia title case por palavra. O usuário pediu caixa alta
nas listas de certificados e nos nomes de pessoas, e o dado de pessoa passou
a ser gravado assim no cadastro, na edição e na importação."""

from __future__ import annotations

import pytest

from app.nomes import nome_exibicao, nome_pessoa


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("SUPERMERCADO ECONOMICO UNIAO LTDA", "SUPERMERCADO ECONOMICO UNIAO LTDA"),
        ("Supermercado Economico Uniao Ltda", "SUPERMERCADO ECONOMICO UNIAO LTDA"),
        ("64 779 321 nilson batista neto", "64 779 321 NILSON BATISTA NETO"),
        ("Clínica São Lucas Ltda", "CLÍNICA SÃO LUCAS LTDA"),
        ("maria-jose d'avila", "MARIA-JOSE D'AVILA"),
    ],
)
def test_sobe_para_maiusculas(entrada: str, esperado: str) -> None:
    assert nome_exibicao(entrada) == esperado


def test_vazio_e_none() -> None:
    assert nome_exibicao("") == ""
    assert nome_exibicao(None) == ""


def test_nome_pessoa_em_maiusculas_e_sem_espacos_nas_pontas() -> None:
    assert nome_pessoa("irla") == "IRLA"
    assert nome_pessoa("  Beatriz Vitoria Melo da Silva ") == "BEATRIZ VITORIA MELO DA SILVA"
    assert nome_pessoa("KELSEN") == "KELSEN"
    assert nome_pessoa(None) == ""
