"""Anotador e vigia (Frente C: programa e página).

  certguard_analise.exe --vigia                a tarefa agendada (SYSTEM): a cada
                                               5 s, sobe um anotador em cada
                                               sessão ativa que não tem um
  certguard_analise.exe --anotador --sid <S>   SYSTEM dentro da sessão da pessoa:
                                               a cada 1 s, anota a janela em foco
                                               em `tarefa.pastas().raiz`

O anotador roda como SYSTEM para a pessoa (sem admin) não poder matá-lo nem
mexer no que ele grava; a pasta é trancada (só SYSTEM e Administradores).
Superfície mínima: não abre janela, não lê arquivo da pasta da pessoa e não
recebe comando de fora (nenhum socket, pipe ou arquivo de entrada).

As partes puras (`passo`, `laco`, `sessoes_sem_anotador`) não tocam no Win32,
para os testes rodarem sem privilégio.
"""

from __future__ import annotations

import ctypes
import logging
import os
import re
import sys
import time
from ctypes import wintypes
from datetime import datetime, timedelta, timezone

from estacao import janelas, tarefa

logger = logging.getLogger("estacao.anotador")

WTS_ACTIVE = 0  # win32ts.WTSActive
WTS_DISCONNECTED = 4  # win32ts.WTSDisconnected
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
ERRO_JA_EXISTE = 183  # ERROR_ALREADY_EXISTS
MUTEX_VIGIA = "Global\\CertguardVigia"
CONFERIR_SESSAO = timedelta(seconds=30)
PODAR = timedelta(hours=1)
AVISAR = timedelta(minutes=1)
_SID = re.compile(r"S-1(-\d+)+")
_MUTEXES = []  # handles vivos até o processo sair: soltar o mutex é sair


def mutex_do_anotador(sessao: int) -> str:
    return f"Global\\CertguardAnotador-{sessao}"


# ── Partes puras ────────────────────────────────────────────────────────


def passo(estado: dict, agora: datetime, lida, gravar) -> None:
    """Grava só quando a janela muda. `None` (sem janela, sessão bloqueada) não
    grava, mas zera a última: a mesma janela volta a ser anotada depois."""
    if lida is None:
        estado["ultima"] = None
        return
    if lida != estado.get("ultima"):
        gravar(agora, *lida)  # se falhar, a última não muda e o próximo passo tenta de novo
    estado["ultima"] = lida


def laco(raiz: str, sid: str, dormir, ler, relogio, viva) -> None:
    """O laço do anotador: termina só quando `viva()` diz que a sessão acabou.
    Qualquer erro de uma volta vai ao log (no máximo um por minuto) e o laço
    segue: um título estranho ou o disco ocupado não derrubam o anotador."""
    estado: dict = {}
    conferida = podada = avisada = None
    while True:
        agora = relogio()
        try:
            if conferida is None or agora - conferida >= CONFERIR_SESSAO:
                conferida = agora
                if not viva():
                    return
            if podada is None or agora - podada >= PODAR:
                podada = agora
                janelas.podar(raiz, agora)
            passo(estado, agora, ler(), lambda q, p, t: janelas.anotar(raiz, sid, q, p, t))
        except Exception:
            if avisada is None or agora - avisada >= AVISAR:
                avisada = agora
                logger.exception("Falha numa volta do anotador; segue.")
        dormir(1)


def sessoes_sem_anotador(sessoes: list[dict], vivos: dict) -> list[int]:
    """Sessões ativas sem anotador vivo (`poll()` igual ao do Popen)."""
    return [
        s["SessionId"] for s in sessoes
        if s.get("State") == WTS_ACTIVE and (s["SessionId"] not in vivos or vivos[s["SessionId"]].poll() is not None)
    ]


# ── Win32 ───────────────────────────────────────────────────────────────


def janela_em_foco() -> tuple[str, str] | None:
    """(programa sem `.exe`, título) da janela em primeiro plano; `None` sem janela."""
    # WinDLL próprio: os tipos declarados aqui não mexem no `ctypes.windll` dos outros módulos.
    u, k = ctypes.WinDLL("user32"), ctypes.WinDLL("kernel32")
    u.GetForegroundWindow.restype = wintypes.HWND
    u.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    u.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    k.CloseHandle.argtypes = (wintypes.HANDLE,)

    h = u.GetForegroundWindow()
    if not h:
        return None
    titulo = ctypes.create_unicode_buffer(512)
    u.GetWindowTextW(h, titulo, 512)
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(h, ctypes.byref(pid))
    programa = ""
    hp = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if hp:
        try:
            caminho, n = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
            if k.QueryFullProcessImageNameW(hp, 0, caminho, ctypes.byref(n)):
                programa = os.path.basename(caminho.value)
                if programa.lower().endswith(".exe"):
                    programa = programa[:-4]
        finally:
            k.CloseHandle(hp)
    return programa, titulo.value


def _mutex(nome: str) -> bool:
    """True se este processo é o primeiro com `nome`. Criar em `Global\\` exige
    SeCreateGlobalPrivilege, que a pessoa sem admin não tem: ela não ocupa o nome."""
    try:
        _MUTEXES.append(ctypes.windll.kernel32.CreateMutexW(None, False, nome))
        return ctypes.windll.kernel32.GetLastError() != ERRO_JA_EXISTE
    except Exception:
        return True


def _mutex_existe(nome: str) -> bool:
    h = ctypes.windll.kernel32.OpenMutexW(SYNCHRONIZE, False, nome)
    if h:
        ctypes.windll.kernel32.CloseHandle(h)
    return bool(h)


def _minha_sessao() -> int:
    sessao = wintypes.DWORD()
    ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sessao))
    return sessao.value


def _sessao_viva(sessao: int) -> bool:
    """Some da lista no logoff. Sair também nos estados de desmontagem: um
    processo SYSTEM preso na sessão poderia segurá-la na lista."""
    import win32ts

    for s in win32ts.WTSEnumerateSessions(win32ts.WTS_CURRENT_SERVER_HANDLE):
        if s["SessionId"] == sessao:
            return s.get("State") in (WTS_ACTIVE, WTS_DISCONNECTED)
    return False


class _Processo:
    """O handle do processo com o `poll()` do Popen."""

    def __init__(self, handle):
        self.handle = handle

    def poll(self):
        import win32event
        import win32process

        if win32event.WaitForSingleObject(self.handle, 0) == win32event.WAIT_TIMEOUT:
            return None
        return win32process.GetExitCodeProcess(self.handle)


def lancar_na_sessao(sessao: int, exe: str) -> _Processo | None:
    """Sobe `exe --anotador --sid <dono da sessão>` como SYSTEM na sessão.
    Sessão sem usuário (tela de logon) devolve None sem log."""
    import win32api
    import win32con
    import win32process
    import win32security
    import win32ts

    try:
        usuario = win32ts.WTSQueryUserToken(sessao)
    except Exception:
        return None
    try:
        sid = win32security.ConvertSidToStringSid(win32security.GetTokenInformation(usuario, win32security.TokenUser)[0])
    except Exception:
        logger.warning("Não foi possível ler o SID da sessão %s.", sessao, exc_info=True)
        return None
    finally:
        usuario.Close()
    try:
        proprio = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_ALL_ACCESS)
        try:
            dup = win32security.DuplicateTokenEx(proprio, win32security.SecurityImpersonation,
                                                 win32con.TOKEN_ALL_ACCESS, win32security.TokenPrimary)
            try:
                win32security.SetTokenInformation(dup, win32security.TokenSessionId, sessao)
                info = win32process.STARTUPINFO()
                info.lpDesktop = "winsta0\\default"
                hp, ht, pid, _tid = win32process.CreateProcessAsUser(
                    dup, None, f'"{exe}" --anotador --sid {sid}', None, None, False,
                    win32process.CREATE_NO_WINDOW, None, None, info)
                ht.Close()
                logger.info("Anotador %s na sessão %s.", pid, sessao)
                return _Processo(hp)
            finally:
                dup.Close()
        finally:
            proprio.Close()
    except Exception:
        logger.warning("Não foi possível subir o anotador na sessão %s.", sessao, exc_info=True)
        return None


# ── Os dois modos ───────────────────────────────────────────────────────


def rodar_anotador(sid: str, dormir=time.sleep, ler=janela_em_foco,
                   relogio=lambda: datetime.now(timezone.utc)) -> int:
    tarefa.configurar_log("anotador.log")
    if not _SID.fullmatch(sid):
        logger.error("SID inválido no --sid; encerrando.")  # vira nome de pasta: nada de `..`
        return 2
    sessao = _minha_sessao()
    if not _mutex(mutex_do_anotador(sessao)):
        logger.info("Já há anotador na sessão %s; encerrando este.", sessao)
        return 0
    logger.info("Anotador na sessão %s.", sessao)
    laco(tarefa.pastas().raiz, sid, dormir, ler, relogio, lambda: _sessao_viva(sessao))
    logger.info("Sessão %s encerrada; anotador sai.", sessao)
    return 0


def rodar_vigia(intervalo: int = 5) -> int:
    tarefa.configurar_log("vigia.log")
    if not getattr(sys, "frozen", False):
        logger.warning("Fora do executável (desenvolvimento): vigia não roda.")
        return 1
    if not _mutex(MUTEX_VIGIA):
        logger.info("Outra vigia já está rodando; encerrando esta.")
        return 0
    import win32ts

    vivos: dict = {}
    while True:
        try:
            sessoes = win32ts.WTSEnumerateSessions(win32ts.WTS_CURRENT_SERVER_HANDLE)
            for s in sessoes_sem_anotador(sessoes, vivos):
                # Anotador de uma vigia anterior (sem handle aqui): o mutex dele prova que vive.
                if _mutex_existe(mutex_do_anotador(s)):
                    continue
                processo = lancar_na_sessao(s, sys.executable)
                if processo is None:
                    vivos.pop(s, None)
                else:
                    vivos[s] = processo
        except Exception:
            logger.exception("Falha numa volta da vigia; segue.")
        time.sleep(intervalo)
