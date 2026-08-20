"""Regras dos alertas por e-mail que a tela passou a configurar.

Funções puras, sem Supabase e sem SMTP: a validação que a tela usa para recusar
um valor tem de ser a MESMA que o job usa para interpretá-lo. Duas cópias da
regra é como "a vencer em 30 dias" viraria dois números diferentes.

Convenção herdada de `PortalSettings`, e mantida aqui sem exceção: **vazio
significa "usar o padrão do código", não "desligado"**. Uma instalação que nunca
abriu esta tela precisa se comportar exatamente como antes de ela existir.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional, Sequence, Tuple

# ── Marcos de aviso ────────────────────────────────────────────────────────
# Dias que faltam para o vencimento em que um novo aviso é disparado. O padrão
# é o que valia antes desta tela existir.
MARCOS_PADRAO: Tuple[int, ...] = (30, 15, 7, 1)
MARCO_MIN = 1
MARCO_MAX = 365
MARCOS_MAX_QTD = 6

# ── Intervalo entre execuções do job ───────────────────────────────────────
# Não é um horário de disparo: é o intervalo MÍNIMO entre duas execuções. O
# Procfile usa `--max-requests 500`, então o worker recicla várias vezes ao dia
# e o job tentaria rodar a cada reinício.
INTERVALO_PADRAO_HORAS = 20
INTERVALO_MIN_HORAS = 1
INTERVALO_MAX_HORAS = 24 * 30

_RE_EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]{2,}$")
_SEPARADORES = re.compile(r"[,;\s]+")


class ConfiguracaoInvalida(ValueError):
    """Valor recusado na hora de salvar, com o motivo em português."""


# ══════════════════════════════════════════════════════════════════════════
# Marcos
# ══════════════════════════════════════════════════════════════════════════

def parse_marcos(texto: str) -> Tuple[int, ...]:
    """Texto da tela -> marcos normalizados, do maior para o menor.

    Vazio devolve tupla vazia, que é "usar o padrão" — e não "nunca avisar".
    Desligar os avisos é o `smtp_alerts_enabled`, que já existe; sobrecarregar
    a lista vazia com esse sentido daria dois jeitos de desligar e nenhum
    explícito.
    """
    bruto = (texto or "").strip()
    if not bruto:
        return ()

    valores: list[int] = []
    for pedaco in _SEPARADORES.split(bruto):
        if not pedaco:
            continue
        try:
            n = int(pedaco)
        except ValueError:
            raise ConfiguracaoInvalida(
                f"“{pedaco}” não é um número de dias. Use apenas números, "
                "separados por vírgula."
            )
        if not (MARCO_MIN <= n <= MARCO_MAX):
            raise ConfiguracaoInvalida(
                f"O marco de {n} dias está fora do intervalo permitido "
                f"({MARCO_MIN} a {MARCO_MAX} dias)."
            )
        valores.append(n)

    unicos = sorted(set(valores), reverse=True)
    if len(unicos) != len(valores):
        raise ConfiguracaoInvalida("Há marcos repetidos na lista.")
    if len(unicos) > MARCOS_MAX_QTD:
        raise ConfiguracaoInvalida(
            f"São permitidos no máximo {MARCOS_MAX_QTD} marcos. "
            "Cada marco é um e-mail a mais por certificado."
        )
    return tuple(unicos)


def formatar_marcos(marcos: Iterable[int]) -> str:
    """Forma de armazenamento e de exibição: "30,15,5"."""
    return ",".join(str(m) for m in marcos)


def marcos_efetivos(texto: str) -> Tuple[int, ...]:
    """O que o job deve usar de fato, já com o padrão aplicado.

    Nunca levanta: o job roda sem ninguém olhando, e um valor estragado no
    banco não pode derrubar o envio inteiro. Ilegível vira o padrão, que é o
    comportamento conhecido.
    """
    try:
        marcos = parse_marcos(texto)
    except ConfiguracaoInvalida:
        return MARCOS_PADRAO
    return marcos or MARCOS_PADRAO


def marco_de(dias: int, marcos: Sequence[int]) -> int:
    """Menor marco ainda não ultrapassado — com [30,15,5]: 25 -> 30, 12 -> 15.

    É a chave do antispam: enquanto o certificado continuar no mesmo marco, o
    aviso não se repete; ao cruzar para o próximo, sai um reforço.
    """
    candidatos = [m for m in marcos if m >= dias]
    return min(candidatos) if candidatos else marcos[-1]


def janela_dias(marcos: Sequence[int]) -> int:
    """Maior marco: quanto o resumo olha para frente e para trás."""
    return max(marcos) if marcos else MARCOS_PADRAO[0]


# ══════════════════════════════════════════════════════════════════════════
# Destinatários do resumo
# ══════════════════════════════════════════════════════════════════════════

def parse_destinatarios(texto: str) -> Tuple[str, ...]:
    """Texto da tela -> e-mails normalizados, sem repetição.

    Vazio devolve tupla vazia: o resumo continua indo para todo administrador
    ativo, como antes desta tela.
    """
    bruto = (texto or "").strip()
    if not bruto:
        return ()

    vistos: list[str] = []
    for pedaco in _SEPARADORES.split(bruto):
        if not pedaco:
            continue
        email = pedaco.strip().lower()
        if not _RE_EMAIL.match(email):
            raise ConfiguracaoInvalida(f"“{pedaco}” não parece um endereço de e-mail.")
        if email not in vistos:
            vistos.append(email)
    return tuple(vistos)


def formatar_destinatarios(emails: Iterable[str]) -> str:
    return ",".join(emails)


def destinatarios_configurados(texto: str) -> Optional[Tuple[str, ...]]:
    """Lista fixa do resumo, ou None quando o padrão (os admins) deve valer.

    None e tupla vazia querem dizer a MESMA coisa aqui, e é de propósito: um
    valor ilegível no banco cai no padrão em vez de cortar o envio. Alerta que
    para de sair não gera reclamação — gera certificado vencendo em silêncio.
    """
    try:
        emails = parse_destinatarios(texto)
    except ConfiguracaoInvalida:
        return None
    return emails or None


# ══════════════════════════════════════════════════════════════════════════
# Intervalo
# ══════════════════════════════════════════════════════════════════════════

def validar_intervalo(horas: int) -> int:
    """0 é válido e significa "usar o padrão"."""
    n = int(horas or 0)
    if n == 0:
        return 0
    if not (INTERVALO_MIN_HORAS <= n <= INTERVALO_MAX_HORAS):
        raise ConfiguracaoInvalida(
            f"O intervalo precisa ficar entre {INTERVALO_MIN_HORAS} hora e "
            f"{INTERVALO_MAX_HORAS} horas, ou 0 para o padrão."
        )
    return n


def intervalo_efetivo_horas(horas: int) -> int:
    try:
        n = validar_intervalo(horas)
    except ConfiguracaoInvalida:
        return INTERVALO_PADRAO_HORAS
    return n or INTERVALO_PADRAO_HORAS
