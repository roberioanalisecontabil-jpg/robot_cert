"""Mini serviço Windows para teste isolado de SCM + PyInstaller."""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

try:
    import win32event  # noqa: WPS433
    import win32service  # noqa: WPS433
    import win32serviceutil  # noqa: WPS433
    import servicemanager  # noqa: WPS433
except ImportError as exc:  # pragma: no cover
    raise SystemExit("pywin32 é obrigatório para smoke test de serviço.") from exc


def _log_path() -> Path:
    program_data = os.getenv("PROGRAMDATA", "").strip()
    if program_data:
        base = Path(program_data) / "Analise CertiDigital Service Smoke"
    else:
        base = Path(tempfile.gettempdir()) / "Analise CertiDigital Service Smoke"
    base.mkdir(parents=True, exist_ok=True)
    return base / "smoke_service.log"


LOG_FILE = _log_path()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SMOKE-SERVICE] %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
LOGGER = logging.getLogger("service_smoke")


class AnaliseCertiDigitalSmokeService(win32serviceutil.ServiceFramework):
    _svc_name_ = "AnaliseCertiDigitalSmokeSvc"
    _svc_display_name_ = "Analise CertiDigital Smoke Service"
    _svc_description_ = "Serviço mínimo para validar bootstrap SCM e build PyInstaller."

    def __init__(self, args: tuple) -> None:
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.h_wait_stop = win32event.CreateEvent(None, 0, 0, None)
        self._quit = threading.Event()
        self._worker: threading.Thread | None = None

    def SvcStop(self) -> None:
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING, waitHint=30000)
        self._quit.set()
        win32event.SetEvent(self.h_wait_stop)

    def SvcDoRun(self) -> None:
        if getattr(sys, "frozen", False):
            os.chdir(str(Path(sys.executable).resolve().parent))

        self.ReportServiceStatus(win32service.SERVICE_START_PENDING, waitHint=120000)
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        LOGGER.info("Iniciando serviço smoke. Log: %s", LOG_FILE)

        self._worker = threading.Thread(target=self._worker_main, name="SmokeWorker", daemon=True)
        self._worker.start()
        self.ReportServiceStatus(win32service.SERVICE_RUNNING)

        win32event.WaitForSingleObject(self.h_wait_stop, win32event.INFINITE)
        self._quit.set()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=20)

        LOGGER.info("Serviço smoke finalizado.")
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STOPPED,
            (self._svc_name_, ""),
        )

    def _worker_main(self) -> None:
        while not self._quit.is_set():
            LOGGER.info("heartbeat")
            time.sleep(5)


def main() -> None:
    if getattr(sys, "frozen", False):
        os.chdir(str(Path(sys.executable).resolve().parent))
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(AnaliseCertiDigitalSmokeService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(AnaliseCertiDigitalSmokeService)


if __name__ == "__main__":
    main()
