"""1.5.2: a bandeja não fecha (sem "Fechar", o vigia reabre) e não cai mais
pelo Tk em várias threads (estacao/ui.py)."""

from __future__ import annotations

import gc
import inspect
import threading

import pytest

from estacao import bandeja, sessoes


def test_menu_da_bandeja_sem_fechar() -> None:
    fonte = inspect.getsource(bandeja.Bandeja.rodar)
    assert 'item("Fechar"' not in fonte and not hasattr(bandeja.Bandeja, "on_fechar")


def test_sessao_sem_bandeja_ignora_o_anotador_do_system() -> None:
    exe = "certguard_analise.exe"
    processos = [
        (1, "CERTGUARD_ANALISE.EXE", "S-1-5-21-1-2-3-1001"),  # bandeja da pessoa
        (2, exe, sessoes.SYSTEM),  # só o anotador, como SYSTEM
        (3, "explorer.exe", "S-1-5-21-1-2-3-1002"),
    ]
    assert sessoes.sessoes_sem_bandeja([1, 2, 3], processos, exe) == [2, 3]


def test_janelas_dividem_um_so_tk_e_o_lixo_nao_derruba() -> None:
    """Até a 1.5.1 cada janela tinha o seu Tk numa thread; o lixo coletado em
    outra thread dava Tcl_AsyncDelete e matava o processo (0x80000003)."""
    tk = pytest.importorskip("tkinter")
    try:
        tk.Tk().destroy()
    except tk.TclError:
        pytest.skip("sem interface gráfica")
    from estacao import ui

    threads, pronto = [], threading.Event()

    def _janela(raiz) -> None:
        threads.append(threading.current_thread().name)
        topo = tk.Toplevel(raiz)

        def _ciclo():  # fecho que prende a janela, como o _atualizar do status
            topo.after(50, _ciclo)

        _ciclo()
        topo.after(100, topo.destroy)
        if len(threads) == 2:
            raiz.after(300, pronto.set)  # na raiz: o destroy do topo apaga os after dele

    ui.executar(_janela)
    ui.executar(_janela)
    assert pronto.wait(10)
    gc.collect()  # na thread do pytest: antes, aqui o processo morria
    assert threads == ["CertguardTk", "CertguardTk"]
