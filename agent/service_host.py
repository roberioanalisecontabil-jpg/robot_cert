"""Hospedeiro do Serviço Windows (SCM) para o CertGuard Agent — usa pywin32.

Compilar com PyInstaller através de CertGuard_Service.spec → CertGuard_Agent_Service.exe.

Instalação/registo:
  CertGuard_Agent_Service.exe install
  CertGuard_Agent_Service.exe remove
(o instalador Inno pode criar o serviço automaticamente.)
"""

from __future__ import annotations

import logging
import os
import sys
import threading
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
    if getattr(sys, "frozen", False):
        mei = getattr(sys, "_MEIPASS", "") or ""
        if mei:
            sys.path.insert(0, mei)
        sys.path.insert(0, str(Path(sys.executable).resolve().parent))
        return
    agent_dir = Path(__file__).resolve().parent
    repo = agent_dir.parent
    sys.path.insert(0, str(repo))
    sys.path.insert(0, str(agent_dir))


_bootstrap_import_paths()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CertGuard-Service] %(levelname)s %(message)s",
)


from run_agent import AgentRunConfig, run_agent_application  # noqa: E402

_LOG = logging.getLogger("certguard_service")


class CertGuardAgentService(win32serviceutil.ServiceFramework):
    _svc_name_ = "CertGuardAgent"
    _svc_display_name_ = "CertGuard Agent"
    _svc_description_ = (
        "Monitoriza pastas de certificados PFX no Windows e envia inventário ao portal CertGuard."
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

        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )

        self._worker = threading.Thread(
            target=self._worker_main,
            name="CertGuardAgentWorker",
            daemon=True,
        )
        self._worker.start()

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
            _LOG.exception("O worker do CertGuard falhou dentro do serviço")


def main() -> None:
    if getattr(sys, "frozen", False):
        os.chdir(str(Path(sys.executable).resolve().parent))
    win32serviceutil.HandleCommandLine(CertGuardAgentService)


if __name__ == "__main__":
    main()
