"""Remoção de certificados nas estações (Frente B).

Spec: docs/superpowers/specs/2026-11-13-carteira-certificados-remocao-uso-design.md,
seção "Frente B". Por ora só as duas chaves de modo, ajustadas na Configuração:
a regra da carteira e a regra do "sem login".
"""

from __future__ import annotations

from app.settings_state import load_settings

MODOS = ("desligado", "relatorio", "ligado")
PADRAO = "relatorio"


def _modo(valor: str) -> str:
    return valor if valor in MODOS else PADRAO


def modo_carteira() -> str:
    return _modo(load_settings().remocao_carteira_modo)


def modo_sem_login() -> str:
    return _modo(load_settings().remocao_sem_login_modo)
