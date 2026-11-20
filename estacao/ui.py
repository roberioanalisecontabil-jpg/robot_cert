"""A thread única do Tk na bandeja (1.5.2).

Até a 1.5.1 cada janela (login, status) criava o próprio `tk.Tk()` numa
thread nova. Fechada a janela, o interpretador ficava num ciclo de
referências (os fechos do `after`) e o coletor de lixo o apagava mais tarde,
de OUTRA thread: o Tcl entra em pânico ("Tcl_AsyncDelete: async handler
deleted by the wrong thread") e derruba o processo inteiro, a bandeja junto
(0x80000003 em tcl86t.dll no log de Aplicativo; TI-002, 18 e 20/11/2026).

Agora há um só `Tk`, escondido, criado e mantido vivo por esta thread até o
fim do processo. As janelas são `Toplevel` dele, montadas aqui dentro por
`executar`. Nenhum interpretador é apagado, então não há thread errada.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable

logger = logging.getLogger("estacao.ui")

_fila: "queue.Queue[Callable[[Any], None]]" = queue.Queue()
_trava = threading.Lock()
_thread: threading.Thread | None = None


def executar(montar: Callable[[Any], None]) -> None:
    """Roda `montar(raiz)` na thread do Tk. `raiz` é o `Tk` escondido: a janela
    nova é um `tk.Toplevel(raiz)`. Volta na hora, sem esperar a janela."""
    global _thread
    with _trava:
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_laco, name="CertguardTk", daemon=True)
            _thread.start()
    _fila.put(montar)


def _laco() -> None:
    import tkinter as tk

    try:
        raiz = tk.Tk()
    except Exception:
        # Sessão sem desktop: descarta os pedidos para não acumularem.
        logger.warning("Sem interface gráfica; as janelas não abrem.")
        while True:
            _fila.get()
    raiz.withdraw()

    def _bombear() -> None:
        while True:
            try:
                montar = _fila.get_nowait()
            except queue.Empty:
                break
            try:
                montar(raiz)
            except Exception:
                logger.exception("Falha ao montar uma janela")
        raiz.after(100, _bombear)

    _bombear()
    raiz.mainloop()  # nunca sai: a raiz não é destruída
