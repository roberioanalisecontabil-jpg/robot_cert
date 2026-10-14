"""Onde o Certguard Análise guarda as coisas, e onde o Hardlyze guardava.

  máquina  %ProgramData%\\CertguardAnalise   chave da máquina (o instalador grava)
  pessoa   %LOCALAPPDATA%\\CertguardAnalise  conta do portal e o log da bandeja

LOCALAPPDATA e não APPDATA: perfil móvel sincronizaria a conta entre máquinas,
e um blob DPAPI de outra máquina não decifra.

As pastas `InventAgent` são as do Hardlyze, lidas uma vez na transição e
apagadas depois (adendo de 14/10/2026 do ADR 0003).
"""

from __future__ import annotations

import os
from pathlib import Path

PASTA = "CertguardAnalise"
PASTA_HARDLYZE = "InventAgent"


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


def chave_hardlyze() -> Path:
    return _programdata() / PASTA_HARDLYZE / "chave_certificados.dat"


def conta_hardlyze() -> Path:
    return _localappdata() / PASTA_HARDLYZE / "certificados.dat"
