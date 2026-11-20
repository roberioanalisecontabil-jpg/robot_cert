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
import ntpath

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


SYSTEM = "S-1-5-18"


def sessoes_sem_bandeja(ativas: list[int], processos: list[tuple[int, str, str]],
                        nome_exe: str) -> list[int]:
    """Das sessões ativas, as que não têm a bandeja. `processos` são trios
    (sessão, nome do executável, SID do dono). O anotador é o mesmo exe, mas
    roda como SYSTEM na sessão da pessoa: não conta como bandeja."""
    com_bandeja = {s for s, nome, sid in processos
                   if nome.lower() == nome_exe.lower() and sid != SYSTEM}
    return [s for s in ativas if s not in com_bandeja]


def garantir_bandejas(caminho_exe: str) -> int:
    """Reabre a bandeja só onde ela NÃO está (1.5.2: a bandeja não tem mais
    "Fechar"; quem a fecha pelo Gerenciador de Tarefas a vê voltar). Roda no
    vigia, como SYSTEM. Devolve quantas abriu."""
    try:
        import win32security
        import win32ts
    except ImportError:
        return 0
    servidor = win32ts.WTS_CURRENT_SERVER_HANDLE
    try:
        ativas = [s["SessionId"] for s in win32ts.WTSEnumerateSessions(servidor)
                  if s.get("State") == win32ts.WTSActive]
        processos = []
        for sessao, _pid, nome, sid in win32ts.WTSEnumerateProcesses(servidor):
            try:
                texto = win32security.ConvertSidToStringSid(sid) if sid else ""
            except Exception:
                texto = ""
            processos.append((sessao, nome, texto))
    except Exception:
        logger.debug("Não foi possível listar sessões/processos.", exc_info=True)
        return 0
    abertas = 0
    for sessao in sessoes_sem_bandeja(ativas, processos, ntpath.basename(caminho_exe)):
        if _abrir_na_sessao(sessao, caminho_exe):
            logger.info("Bandeja reaberta na sessão %s.", sessao)
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
