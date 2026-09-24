"""Nome de exibição de titular de certificado.

Os nomes chegam da origem em CAIXA ALTA ("SUPERMERCADO ECONOMICO UNIAO LTDA",
"A DE CASTRO DANIEL SERVICOS LTDA"). Na lista o DS pede sentence/title case:
caixa alta é dos cabeçalhos da tabela, não das células. `text-transform` não
resolve porque partículas ("de", "da") ficam minúsculas e siglas societárias
("LTDA", "ME", "S/A") ficam maiúsculas — decisão por palavra, não por
caractere. Por isso vive no servidor, num lugar só, e vai para o JSON da API
(`nome_exibicao`) e para os templates como filtro Jinja de mesmo nome.

O original nunca é alterado: continua em `nome`, na busca e na exportação.
Palavras não ganham acento ("Servicos" continua como veio): inventar acento
erraria em nome próprio.
"""
from __future__ import annotations

import re

# Conectivos que ficam minúsculos no meio do nome. No começo do nome a
# palavra sobe ("De Castro" só quando é a primeira), porque um nome não
# começa com minúscula.
PARTICULAS = frozenset({"de", "da", "do", "das", "dos", "e"})

# Siglas societárias e afins que ficam em maiúsculas onde quer que estejam.
# Comparação sem pontuação: "S.A." e "S/A" batem com "SA".
SIGLAS = frozenset({
    "LTDA", "ME", "EPP", "EIRELI", "SA", "SS", "MEI", "CIA", "SLU", "SCP",
    "EI", "ONG", "OSC", "CNPJ", "CPF",
})

_TOKEN = re.compile(r"(\s+)")


def _capitalizar(palavra: str) -> str:
    """Primeira letra maiúscula, resto minúsculo — inclusive depois de hífen
    e apóstrofo ("Maria-Jose", "D'Avila")."""
    baixo = palavra.lower()
    return re.sub(r"(^|[-'])(\w)", lambda m: m.group(1) + m.group(2).upper(), baixo)


def nome_exibicao(nome: object) -> str:
    """Converte um nome em caixa alta para exibição.

    Nome que já tem minúsculas não é tocado: veio de uma origem que sabia o
    que estava fazendo. Números, pontuação e espaços passam intactos — o
    código numérico na frente do nome faz parte dele.
    """
    s = "" if nome is None else str(nome)
    if not s or s != s.upper():
        return s
    partes = _TOKEN.split(s)
    saida: list[str] = []
    primeira = True
    for p in partes:
        if not p or p.isspace() or not re.search(r"[A-ZÀ-Ü]", p):
            saida.append(p)
            continue
        chave = re.sub(r"[^A-Z]", "", p)
        if chave in SIGLAS:
            saida.append(p)
        elif not primeira and p.lower() in PARTICULAS:
            saida.append(p.lower())
        else:
            saida.append(_capitalizar(p))
        primeira = False
    return "".join(saida)


def nome_pessoa(nome: object) -> str:
    """Nome de PESSOA para exibição: "irla" → "Irla", "BEATRIZ VITORIA MELO DA
    SILVA" → "Beatriz Vitoria Melo da Silva". Um nome todo em minúsculas é tão
    "sem caixa" quanto um todo em maiúsculas — vem de cadastro apressado — e
    subir a primeira letra não erra. Nome com maiúsculas e minúsculas
    misturadas não é tocado. O dado gravado nunca muda: a correção do
    cadastro é na tela Usuários."""
    s = "" if nome is None else str(nome).strip()
    if not s:
        return s
    if s == s.lower():
        return nome_exibicao(s.upper())
    return nome_exibicao(s)
