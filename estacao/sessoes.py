"""Reabrir a bandeja nas sessões de quem está logado (1.1.0).

Veio de `core/sessoes.py` do Hardlyze. A atualização automática roda o
instalador como SYSTEM: ele fecha a bandeja de todo mundo (o executável vai
ser sobrescrito) e, em silêncio, não a reabre — reabrir dali a poria na sessão
do SYSTEM, invisível. Quem reabre é a tarefa da versão nova, depois de
confirmar: para cada sessão ATIVA, pede ao Windows o token de quem está nela e
sobe a bandeja como essa pessoa, na área de trabalho dela.

A bandeja tem trava de uma instância por sessão (`bandeja.instancia_unica`),
então abrir onde ela já estiver é inofensivo.

Só funciona rodando como SYSTEM (WTSQueryUserToken exige). Fora disso, ou
fora do Windows, não faz nada.
"""

from __future__ import annotations

import contextlib
import logging

logger = logging.getLogger(__name__)


def reabrir_bandejas(caminho_exe: str) -> int:
    """Sobe `caminho_exe` (sem argumento: a bandeja) em cada sessão ativa.
    Devolve quantas."""
    try:
        import win32ts
    except ImportError:
        return 0
    try:
        sessoes = win32ts.WTSEnumerateSessions(win32ts.WTS_CURRENT_SERVER_HANDLE)
    except Exception:
        logger.warning("Não foi possível listar as sessões para reabrir a bandeja.", exc_info=True)
        return 0
    abertas = 0
    for s in sessoes:
        if s.get("State") != win32ts.WTSActive:
            continue
        if _abrir_na_sessao(s["SessionId"], caminho_exe):
            abertas += 1
    return abertas


def _abrir_na_sessao(sessao: int, caminho_exe: str) -> bool:
    import win32con
    import win32process
    import win32profile
    import win32ts

    try:
        token = win32ts.WTSQueryUserToken(sessao)
    except Exception:
        # Sessão sem usuário (tela de logon) ou sem privilégio: segue.
        return False
    try:
        ambiente = win32profile.CreateEnvironmentBlock(token, False)
        info = win32process.STARTUPINFO()
        info.lpDesktop = "winsta0\\default"
        win32process.CreateProcessAsUser(
            token, None, f'"{caminho_exe}"', None, None, False,
            win32con.NORMAL_PRIORITY_CLASS | win32process.CREATE_UNICODE_ENVIRONMENT,
            ambiente, None, info,
        )
        return True
    except Exception:
        logger.warning("Não foi possível reabrir a bandeja na sessão %s.", sessao, exc_info=True)
    finally:
        with contextlib.suppress(Exception):
            token.Close()
    return False
