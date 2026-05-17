"""Hospedeiro do Serviço Windows (SCM) para o Analise CertiDigital Agent — usa pywin32.

Compilar com PyInstaller através de AnaliseCertiDigital_Service.spec → AnaliseCertiDigital_Agent_Service.exe.

Instalação/registo:
  AnaliseCertiDigital_Agent_Service.exe install
  AnaliseCertiDigital_Agent_Service.exe remove
(o instalador Inno pode criar o serviço automaticamente.)
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import traceback
from pathlib import Path

try:
    import win32serviceutil  # noqa: WPS433
    import win32service  # noqa: WPS433
    import win32event  # noqa: WPS433
    import servicemanager  # noqa: WPS433
except ImportError as exc:  # pragma: no cover - só Windows na build final
    raise SystemExit(
        "pywin32 é necessário para o serviço (pip install pywin32 no Windows)."
    ) from exc


def _bootstrap_import_paths() -> None:
    """Garante que run_agent e app.* sejam importáveis em modo frozen e dev."""
    if getattr(sys, "frozen", False):
        mei = getattr(sys, "_MEIPASS", "") or ""
        if mei:
            sys.path.insert(0, mei)
        exe_dir = str(Path(sys.executable).resolve().parent)
        if exe_dir not in sys.path:
            sys.path.insert(0, exe_dir)
        return
    agent_dir = Path(__file__).resolve().parent
    repo = agent_dir.parent
    for p in (str(repo), str(agent_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)


_bootstrap_import_paths()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Analise CertiDigital-Service] %(levelname)s %(message)s",
)

_LOG = logging.getLogger("analise_certidigital_service")

# ── Import tardio do agente (com diagnóstico detalhado em caso de falha) ──
_IMPORT_OK = False
_IMPORT_ERROR: str | None = None

try:
    from run_agent import AgentRunConfig, run_agent_application  # noqa: E402
    _IMPORT_OK = True
except Exception as _exc:
    _IMPORT_ERROR = (
        f"Falha ao importar run_agent: {_exc}\n"
        f"sys.path = {sys.path}\n"
        f"cwd = {os.getcwd()}\n"
        f"frozen = {getattr(sys, 'frozen', False)}\n"
        f"exe = {sys.executable}\n"
        f"traceback:\n{traceback.format_exc()}"
    )
    _LOG.critical(_IMPORT_ERROR)


class AnaliseCertiDigitalAgentService(win32serviceutil.ServiceFramework):
    _svc_name_ = "AnaliseCertiDigitalAgent"
    _svc_display_name_ = "Analise CertiDigital Agent"
    _svc_description_ = (
        "Monitoriza pastas de certificados PFX no Windows e envia inventário ao portal Analise CertiDigital."
    )

    def __init__(self, args: tuple) -> None:
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.h_wait_stop = win32event.CreateEvent(None, 0, 0, None)
        self._agent_quit = threading.Event()
        self._worker: threading.Thread | None = None

    def SvcStop(self) -> None:
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING, waitHint=45000)
        self._agent_quit.set()
        win32event.SetEvent(self.h_wait_stop)

    def SvcDoRun(self) -> None:
        if getattr(sys, "frozen", False):
            os.chdir(str(Path(sys.executable).resolve().parent))

        # ── Sinalizar RUNNING ao SCM o mais rápido possível ──────────
        # O SCM espera essa sinalização em ~30s; se demorar, dá erro 1053.
        # Todo trabalho pesado (import, I/O, rede) vai para a thread worker.
        self.ReportServiceStatus(win32service.SERVICE_START_PENDING, waitHint=120000)
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )

        # Se o import falhou, logar e parar imediatamente (sem travar)
        if not _IMPORT_OK:
            servicemanager.LogErrorMsg(
                f"AnaliseCertiDigitalAgent: import de run_agent falhou.\n{_IMPORT_ERROR}"
            )
            self.ReportServiceStatus(win32service.SERVICE_STOPPED)
            return

        self._worker = threading.Thread(
            target=self._worker_main,
            name="AnaliseCertiDigitalAgentWorker",
            daemon=True,
        )
        self._worker.start()

        # Sinaliza explicitamente ao SCM que o serviço já iniciou.
        self.ReportServiceStatus(win32service.SERVICE_RUNNING)

        win32event.WaitForSingleObject(self.h_wait_stop, win32event.INFINITE)
        self._agent_quit.set()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=240)

        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STOPPED,
            (self._svc_name_, ""),
        )

    def _worker_main(self) -> None:
        try:
            run_agent_application(
                self._agent_quit,
                AgentRunConfig(once=False, no_tray=True, mover_cli=False),
            )
        except SystemExit:
            pass
        except Exception:
            _LOG.exception("O worker do Analise CertiDigital falhou dentro do serviço")


def main() -> None:
    if getattr(sys, "frozen", False):
        os.chdir(str(Path(sys.executable).resolve().parent))
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(AnaliseCertiDigitalAgentService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(AnaliseCertiDigitalAgentService)


if __name__ == "__main__":
    main()
