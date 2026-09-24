"""`nome_exibicao`: caixa alta da origem vira nome legível, sem inventar."""

from __future__ import annotations

import pytest

from app.nomes import nome_exibicao


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("SUPERMERCADO ECONOMICO UNIAO LTDA", "Supermercado Economico Uniao LTDA"),
        ("A DE CASTRO DANIEL SERVICOS LTDA", "A de Castro Daniel Servicos LTDA"),
        ("64 779 321 NILSON BATISTA NETO", "64 779 321 Nilson Batista Neto"),
        ("JOAO DA SILVA ME", "Joao da Silva ME"),
        ("ACO BOMPRECO COMERCIAL S/A", "Aco Bompreco Comercial S/A"),
        ("BANCO S.A.", "Banco S.A."),
        ("CLINICA MELO EIRELI - EPP", "Clinica Melo EIRELI - EPP"),
        ("MARIA-JOSE D'AVILA", "Maria-Jose D'Avila"),
        ("DE CASTRO & CIA", "De Castro & CIA"),
    ],
)
def test_converte_caixa_alta(entrada: str, esperado: str) -> None:
    assert nome_exibicao(entrada) == esperado


def test_nome_ja_misto_nao_e_tocado() -> None:
    """Quem já tem minúsculas veio de uma origem que sabia o que fazia."""
    assert nome_exibicao("Clínica São Lucas Ltda") == "Clínica São Lucas Ltda"


def test_nao_inventa_acento() -> None:
    assert nome_exibicao("SERVICOS ELETRICOS") == "Servicos Eletricos"


def test_vazio_e_none() -> None:
    assert nome_exibicao("") == ""
    assert nome_exibicao(None) == ""
