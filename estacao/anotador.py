"""Anotador e vigia (Frente C: programa e página).

  certguard_analise.exe --vigia                a tarefa agendada (SYSTEM): a cada
                                               5 s, sobe um anotador em cada
                                               sessão ativa que não tem um; a
                                               cada 60 s, reabre a bandeja
                                               onde ela não está; a cada
                                               5 min, leva o uso ao portal
                                               (1.5.2)
  certguard_analise.exe --anotador --sid <S>   SYSTEM dentro da sessão da pessoa:
                                               a cada 1 s, anota a janela em foco
                                               em `tarefa.pastas().raiz`

O anotador roda como SYSTEM para a pessoa (sem admin) não poder matá-lo nem
mexer no que ele grava; a pasta é trancada (só SYSTEM e Administradores).
Superfície mínima: não abre janela, não lê arquivo da pasta da pessoa e não
recebe comando de fora (nenhum socket, pipe ou arquivo de entrada).

Um por vez: cada um trava um arquivo dentro da pasta trancada
(`vigia.lock`, `anotador-<sessao>.lock`). Mutex em `Global\\` não serve: a
pessoa sem admin pode criar o nome antes e calar o anotador para sempre.

As partes puras (`passo`, `laco`, `volta`, `sessoes_sem_anotador`) não tocam
no Win32, para os testes rodarem sem privilégio.
"""

from __future__ import annotations

import ctypes
import logging
import os
import re
import sys
import time
from ctypes import wintypes
from datetime import datetime, timezone

from estacao import janelas, tarefa

logger = logging.getLogger("estacao.anotador")

WTS_ACTIVE = 0  # win32ts.WTSActive
WTS_DISCONNECTED = 4  # win32ts.WTSDisconnected
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TRAVA_VIGIA = "vigia.lock"
# Em segundos de `time.monotonic()`: acertar o relógio do Windows não mexe neles.
CONFERIR_SESSAO = 30
PODAR = 3600
AVISAR = 60
MORTE_PRECOCE = 30  # anotador que morre antes disso depois de subir...
PAUSA = 60  # ...não é relançado nessa sessão por este tempo (o onefile extrai a cada subida)
BANDEJA = 60  # a cada quanto o vigia reabre a bandeja que alguém fechou
COLETA = 300  # a cada quanto o vigia leva o uso ao portal (1.5.2)
COLETA_PRIMEIRA = 60  # depois de subir: a rede ainda pode estar chegando
_SID = re.compile(r"S-1(-\d+)+")
_TRAVAS = []  # travas presas até o processo sair: o Windows solta quando ele morre
_AVISOS: dict = {}


def trava_do_anotador(raiz: str, sessao: int) -> str:
    return os.path.join(raiz, f"anotador-{sessao}.lock")


def _avisar(tipo: str, texto: str, *args, agora: float | None = None) -> None:
    """`logger.warning` com o traceback, no máximo um por minuto de cada `tipo`:
    estes laços rodam para sempre e um erro que se repete não pode encher o log."""
    agora = time.monotonic() if agora is None else agora
    if tipo in _AVISOS and agora - _AVISOS[tipo] < AVISAR:
        return
    _AVISOS[tipo] = agora
    logger.warning(texto, *args, exc_info=True)


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


def laco(raiz: str, sid: str, dormir, ler, relogio, viva, monotonico=time.monotonic) -> None:
    """O laço do anotador: termina só quando `viva()` diz que a sessão acabou.
    Qualquer erro de uma volta vai ao log (no máximo um por minuto) e o laço
    segue: um título estranho ou o disco ocupado não derrubam o anotador.
    `relogio` (UTC) só carimba a janela; os intervalos contam em `monotonico`."""
    estado: dict = {}
    conferida = podada = None
    while True:
        m = monotonico()
        try:
            if conferida is None or m - conferida >= CONFERIR_SESSAO:
                conferida = m
                if not viva():
                    return
            agora = relogio()
            if podada is None or m - podada >= PODAR:
                podada = m
                janelas.podar(raiz, agora)
            passo(estado, agora, ler(), lambda q, p, t: janelas.anotar(raiz, sid, q, p, t))
        except Exception:
            _avisar("anotador", "Falha numa volta do anotador; segue.", agora=m)
        dormir(1)


def sessoes_sem_anotador(sessoes: list[dict], vivos: dict) -> list[int]:
    """Sessões ativas sem anotador vivo (`poll()` igual ao do Popen)."""
    return [
        s["SessionId"] for s in sessoes
        if s.get("State") == WTS_ACTIVE and (s["SessionId"] not in vivos or vivos[s["SessionId"]].poll() is not None)
    ]


def volta(sessoes: list[dict], vivos: dict, coberta, lancar, agora: float = 0.0,
          pausa: dict | None = None) -> None:
    """Uma volta da vigia. Tira de `vivos` (fechando o handle) quem morreu ou
    cuja sessão sumiu; lança o anotador nas sessões ativas sem um. `coberta`
    pega o anotador de uma vigia anterior, que não está em `vivos`.
    `agora` é monotônico; `pausa` (sessão -> até quando) guarda, entre as
    voltas, as sessões cujo anotador morreu logo depois de subir."""
    pausa = {} if pausa is None else pausa
    listadas = {s["SessionId"] for s in sessoes}
    for s, processo in list(vivos.items()):
        morreu = processo.poll() is not None
        if s not in listadas or morreu:
            del vivos[s]
            processo.fechar()
            lancado = getattr(processo, "lancado", None)
            if morreu and lancado is not None and agora - lancado < MORTE_PRECOCE:
                pausa[s] = agora + PAUSA
    for s in sessoes_sem_anotador(sessoes, vivos):
        if pausa.get(s, agora) > agora or coberta(s):
            continue
        processo = lancar(s)
        if processo is not None:
            processo.lancado = agora
            vivos[s] = processo


# ── Travas (arquivo na pasta trancada) ──────────────────────────────────


def _travar(caminho: str) -> int | None:
    """Descritor com o 1º byte de `caminho` travado; None se outro já trava."""
    import msvcrt

    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    fd = os.open(caminho, os.O_RDWR | os.O_CREAT)
    try:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return fd
    except OSError:
        os.close(fd)
        return None


def _ocupada(caminho: str) -> bool:
    """Alguém trava `caminho`? Se não, solta na hora o que acabou de pegar."""
    import msvcrt

    fd = _travar(caminho)
    if fd is None:
        return True
    try:
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    finally:
        os.close(fd)
    return False


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


def _minha_sessao() -> int | None:
    sessao = wintypes.DWORD()
    if not ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sessao)):
        return None
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

    def fechar(self) -> None:
        self.handle.Close()


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
        _avisar("sid", "Não foi possível ler o SID da sessão %s.", sessao)
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
        _avisar("lancar", "Não foi possível subir o anotador na sessão %s.", sessao)
        return None


# ── Os dois modos ───────────────────────────────────────────────────────


def rodar_anotador(sid: str, dormir=time.sleep, ler=janela_em_foco,
                   relogio=lambda: datetime.now(timezone.utc)) -> int:
    sessao = _minha_sessao()
    # Um log por sessão: vários processos girando o mesmo RotatingFileHandler falham no Windows.
    tarefa.configurar_log("anotador.log" if sessao is None else f"anotador-{sessao}.log")
    if sessao is None:
        logger.error("ProcessIdToSessionId falhou; encerrando.")
        return 1
    if not _SID.fullmatch(sid):
        logger.error("SID inválido no --sid; encerrando.")  # vira nome de pasta: nada de `..`
        return 2
    raiz = tarefa.pastas().raiz
    trava = _travar(trava_do_anotador(raiz, sessao))
    if trava is None:
        logger.info("Já há anotador na sessão %s; encerrando este.", sessao)
        return 0
    _TRAVAS.append(trava)
    logger.info("Anotador na sessão %s.", sessao)
    laco(raiz, sid, dormir, ler, relogio, lambda: _sessao_viva(sessao))
    logger.info("Sessão %s encerrada; anotador sai.", sessao)
    return 0


def coletar_uso_sempre(dormir=time.sleep, coletar=None) -> None:
    """Thread do vigia: leva o uso ao portal a cada COLETA s. Dentro do vigia,
    que já roda o tempo todo, e não numa tarefa de 5 min: cada subida do exe
    onefile extrai ~49 MB e gasta ~2 s de CPU (medido na TI-002, 20/11/2026)."""
    if coletar is None:
        def coletar() -> None:
            from estacao import uso

            with tarefa._cliente() as http:
                enviados = uso.coletar_travado(http)
            if enviados:
                logger.info("Uso dos certificados: %d evento(s) enviado(s).", enviados)

    dormir(COLETA_PRIMEIRA)
    while True:
        try:
            coletar()
        except Exception:
            _avisar("coleta", "Coleta do uso falhou; tenta de novo em %s s.", COLETA)
        dormir(COLETA)


def rodar_vigia(intervalo: int = 5) -> int:
    tarefa.configurar_log("vigia.log")
    if not getattr(sys, "frozen", False):
        logger.warning("Fora do executável (desenvolvimento): vigia não roda.")
        return 1
    raiz = tarefa.pastas().raiz
    # De novo aqui, como SYSTEM: as travas só valem numa pasta que a pessoa não escreve.
    if not tarefa.proteger_pasta(raiz):
        logger.error("Pasta %s não pôde ser trancada; vigia não roda.", raiz)
        return 1
    trava = _travar(os.path.join(raiz, TRAVA_VIGIA))
    if trava is None:
        logger.info("Outra vigia já está rodando; encerrando esta.")
        return 0
    _TRAVAS.append(trava)
    import win32ts

    from estacao import sessoes as bandejas

    if tarefa.e_estacao():
        import threading

        threading.Thread(target=coletar_uso_sempre, name="coleta-uso", daemon=True).start()

    vivos: dict = {}
    pausa: dict = {}
    bandeja_em = 0.0
    while True:
        # 1.5.2: a bandeja não tem "Fechar"; morta pelo Gerenciador de
        # Tarefas, volta em até BANDEJA segundos.
        if time.monotonic() - bandeja_em >= BANDEJA:
            bandeja_em = time.monotonic()
            try:
                bandejas.garantir_bandejas(sys.executable)
            except Exception:
                _avisar("bandeja", "Falha ao conferir a bandeja; segue.")
        try:
            sessoes = win32ts.WTSEnumerateSessions(win32ts.WTS_CURRENT_SERVER_HANDLE)
        except Exception:
            _avisar("sessoes", "Não foi possível listar as sessões.")
        else:
            try:
                volta(sessoes, vivos, lambda s: _ocupada(trava_do_anotador(raiz, s)),
                      lambda s: lancar_na_sessao(s, sys.executable), time.monotonic(), pausa)
            except Exception:
                _avisar("volta", "Falha numa volta da vigia; segue.")
        time.sleep(intervalo)
