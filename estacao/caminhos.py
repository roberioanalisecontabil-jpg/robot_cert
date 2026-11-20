"""Onde o CertGuard Análise guarda as coisas.

  máquina  %ProgramData%\\CertguardAnalise   chave da máquina (o instalador grava)
  pessoa   %LOCALAPPDATA%\\CertguardAnalise  conta do portal e o log da bandeja

LOCALAPPDATA e não APPDATA: perfil móvel sincronizaria a conta entre máquinas,
e um blob DPAPI de outra máquina não decifra.

As pastas `InventAgent` do Hardlyze não são mais lidas: a migração da chave e
da conta (adendo de 14/10/2026 ao ADR 0003) foi retirada em 20/11/2026.
"""

from __future__ import annotations

import os
from pathlib import Path

PASTA = "CertguardAnalise"


def _programdata() -> Path:
    return Path((os.getenv("PROGRAMDATA") or "").strip() or r"C:\ProgramData")


def _localappdata() -> Path:
    base = (os.getenv("LOCALAPPDATA") or "").strip()
    return Path(base) if base else Path.home() / ".config"


def pasta_maquina() -> Path:
    return _programdata() / PASTA


def pasta_pessoa() -> Path:
    return _localappdata() / PASTA


def pasta_de_log() -> Path:
    return pasta_pessoa() / "logs"
