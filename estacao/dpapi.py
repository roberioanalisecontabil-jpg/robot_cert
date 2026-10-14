"""DPAPI do Windows, nos dois escopos: da pessoa e da máquina.

Veio de `core/identidade.py` e `core/chave_maquina.py` do INVENT. A entropia é
parâmetro porque os arquivos herdados do Hardlyze foram cifrados com as
entropias de lá, e o agente novo precisa abri-los.

Sem DPAPI, levanta `SemCofreLocal` em vez de gravar em claro: um segredo que
"funciona de qualquer jeito" continua funcionando sem ninguém perceber que a
garantia sumiu.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

CRYPTPROTECT_LOCAL_MACHINE = 0x04


class SemCofreLocal(RuntimeError):
    """DPAPI indisponível ou recusou. Nada é gravado em claro."""


class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(dados: bytes) -> _BLOB:
    buf = ctypes.create_string_buffer(dados, len(dados))
    return _BLOB(len(dados), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _crypt32():
    if not (sys.platform == "win32" and hasattr(ctypes, "windll")):
        raise SemCofreLocal("DPAPI indisponível nesta plataforma; o segredo não será gravado em claro.")
    return ctypes.windll.crypt32


def _liberar(saida: _BLOB) -> bytes:
    try:
        return ctypes.string_at(saida.pbData, saida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(saida.pbData)


def proteger(dados: bytes, entropia: bytes, maquina: bool = False) -> bytes:
    entrada, ent, saida = _blob(dados), _blob(entropia), _BLOB()
    flags = CRYPTPROTECT_LOCAL_MACHINE if maquina else 0
    if not _crypt32().CryptProtectData(ctypes.byref(entrada), None, ctypes.byref(ent), None, None, flags,
                                       ctypes.byref(saida)):
        raise SemCofreLocal(f"CryptProtectData falhou ({ctypes.GetLastError()}).")
    return _liberar(saida)


def desproteger(dados: bytes, entropia: bytes) -> bytes:
    entrada, ent, saida = _blob(dados), _blob(entropia), _BLOB()
    if not _crypt32().CryptUnprotectData(ctypes.byref(entrada), None, ctypes.byref(ent), None, None, 0,
                                         ctypes.byref(saida)):
        raise SemCofreLocal(f"CryptUnprotectData falhou ({ctypes.GetLastError()}).")
    return _liberar(saida)
