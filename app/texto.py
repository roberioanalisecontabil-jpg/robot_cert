"""Textos prontos para a tela, resolvidos no servidor num lugar só.

Plural, rótulo de status, rótulo de papel e rótulo de alerta moravam em cada
template (e saíam como "tentativa(s)", "fora_do_padrao", "digest:2026-08-26").
Aqui é a única cópia: a API entrega a frase pronta e a tela só a mostra.
Chave interna nunca chega à tela.
"""
from __future__ import annotations

import re
from typing import Optional


def numero(n: object) -> str:
    """1049 → "1.049" (separador de milhar pt-BR)."""
    try:
        v = int(n or 0)
    except (TypeError, ValueError):
        return str(n)
    return f"{v:,}".replace(",", ".")


def plural(n: object, singular: str, plural_: Optional[str] = None) -> str:
    """"5 tentativas", "1 máquina". Sem "(s)"."""
    try:
        v = int(n or 0)
    except (TypeError, ValueError):
        v = 0
    forma = singular if v == 1 else (plural_ if plural_ is not None else singular + "s")
    return f"{numero(v)} {forma}"


# Status do arquivo no inventário (cert_scanner.CertStatus). "Expirado" é o
# que a ÚLTIMA VARREDURA viu; "vencido pela data" é calculado agora — os dois
# números divergem em tudo que venceu depois da varredura, e o rótulo diz qual é.
ROTULOS_STATUS = {
    "ok": "Lidos sem problema",
    "erro": "Erro de leitura",
    "fora_do_padrao": "Fora do padrão de nome",
    "expirado": "Expirados na última varredura",
    "vencido": "Vencidos",
}

ORDEM_STATUS = ("ok", "expirado", "erro", "fora_do_padrao", "vencido")


def rotulo_status(chave: object) -> str:
    c = str(chave or "").lower()
    return ROTULOS_STATUS.get(c, c.replace("_", " ").capitalize() or "Sem status")


ROTULOS_PAPEL = {
    "admin": ("Administrador", "Administradores"),
    "user": ("Operador", "Operadores"),
    "gestor": ("Gestor", "Gestores"),
}


def rotulo_papel(chave: object, n: int = 2) -> str:
    """Papel no plural conforme a contagem: "1 Operador", "6 Operadores"."""
    c = str(chave or "").lower()
    sing, plur = ROTULOS_PAPEL.get(c, (c.capitalize() or "Sem papel", c.capitalize() or "Sem papel"))
    return sing if n == 1 else plur


_RE_EXPIRING = re.compile(r"^expiring:(\d+)$")


def chave_alerta(tipo: object) -> str:
    """Agrupa "digest:2026-08-26", "digest:2026-08-27"… numa chave só."""
    t = str(tipo or "")
    if t.startswith("digest:"):
        return "digest"
    return t


def rotulo_alerta(tipo: object) -> str:
    t = str(tipo or "")
    if t.startswith("digest"):
        return "Resumo diário"
    m = _RE_EXPIRING.match(t)
    if m:
        d = int(m.group(1))
        return "Aviso de vencimento em " + plural(d, "dia")
    if t == "expired":
        return "Aviso de vencido"
    return t or "Sem tipo"
