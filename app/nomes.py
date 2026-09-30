"""Nome de exibição de titular de certificado e de pessoa.

Até 30/09/2026 este módulo convertia a caixa alta da origem em title case
("Supermercado Economico Uniao LTDA"), com partículas e siglas tratadas por
palavra. Em uso, o usuário decidiu o contrário: **tudo em maiúsculas**, na
lista de certificados e nos nomes de pessoas, porque assim as listas ficam
alinhadas e mais fáceis de varrer. A regra passou a ser uma só — subir a
caixa — e continua num lugar só, no servidor, para todas as telas e a
exportação lerem igual.

O original nunca é alterado: continua em `nome`, na busca e na exportação.
Acentos são preservados pelo `str.upper()` ("Clínica" → "CLÍNICA"); nada
é inventado.
"""
from __future__ import annotations


def nome_exibicao(nome: object) -> str:
    """Nome de titular de certificado para exibição: em maiúsculas."""
    s = "" if nome is None else str(nome)
    return s.upper()


def nome_pessoa(nome: object) -> str:
    """Nome de PESSOA para exibição: em maiúsculas, sem espaços nas pontas.
    O dado gravado nasce em maiúsculas desde 30/09/2026 (cadastro, edição e
    importação); contas anteriores são só exibidas assim."""
    s = "" if nome is None else str(nome).strip()
    return s.upper()
