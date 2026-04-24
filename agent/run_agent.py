"""Agente Windows em background com tray, logs e notificações."""

from __future__ import annotations

import os
import sys
import time
import threading
import json
import logging
from argparse import ArgumentParser
from pathlib import Path
from logging.handlers import RotatingFileHandler

import httpx
import pystray
from dotenv import load_dotenv
from PIL import Image, ImageDraw
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")
load_dotenv(Path(__file__).resolve().parent / ".env")

from app.cert_scanner import (  # noqa: E402
    CertStatus,
    cert_to_public_dict,
    move_to_expired,
    scan_folder,
)

# Porta padrão do monitor cert_robot (evita conflito com outro serviço em 8000)
DEFAULT_ROBOT_API_PORT = 8020
DEFAULT_ROBOT_BASE = f"http://127.0.0.1:{DEFAULT_ROBOT_API_PORT}"
LOGGER = logging.getLogger("certguard_agent")


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return ROOT


def _setup_logging() -> Path:
    app_dir = _app_dir()
    app_dir.mkdir(parents=True, exist_ok=True)
    log_file = app_dir / "agent.log"
    handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    LOGGER.addHandler(handler)
    LOGGER.addHandler(logging.StreamHandler(sys.stdout))
    LOGGER.propagate = False
    return log_file


def _load_local_agent_config() -> dict:
    """
    Lê agent_config.json ao lado do executável/script, quando existir.
    Útil para instalação em servidor sem depender de editar .env manualmente.
    """
    candidates = [
        Path(sys.executable).resolve().parent / "agent_config.json",
        Path(__file__).resolve().parent / "agent_config.json",
        ROOT / "agent_config.json",
    ]
    for p in candidates:
        if not p.is_file():
            continue
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except (json.JSONDecodeError, OSError):
            print(f"Aviso: falha ao ler {p}", file=sys.stderr)
    return {}


def _resolve_paths(s: dict, local_cfg: dict) -> tuple[Path, Path]:
    """Prioriza portal; fallback para agent_config.json e variáveis AGENT_*."""
    raw_src = (s.get("source_folder") or "").strip()
    raw_exp = (s.get("expired_folder") or "").strip()
    if not raw_src:
        raw_src = str(local_cfg.get("source_folder") or os.getenv("AGENT_SOURCE") or "").strip()
    if not raw_exp:
        raw_exp = str(local_cfg.get("expired_folder") or os.getenv("AGENT_EXPIRED") or "").strip()
    if not raw_src or not raw_exp:
        raise ValueError(
            "Origem e destino obrigatórios: configure no portal web ou em agent_config.json."
        )
    return Path(raw_src), Path(raw_exp)

class CertEventHandler(FileSystemEventHandler):
    def __init__(self, trigger_event: threading.Event, ignored_dir: Path | None):
        super().__init__()
        self.trigger_event = trigger_event
        self.ignored_dir = ignored_dir.resolve() if ignored_dir else None

    def on_created(self, event):
        self._check(event)

    def on_modified(self, event):
        self._check(event)

    def on_deleted(self, event):
        self._check(event)

    def _check(self, event):
        if event.is_directory:
            return
        p = Path(event.src_path)
        if self.ignored_dir:
            try:
                p.resolve().relative_to(self.ignored_dir)
                return
            except ValueError:
                pass
        if p.suffix.lower() in (".pfx", ".p12"):
            self.trigger_event.set()


def _machine_id(s: dict, local_cfg: dict) -> str:
    return (
        (os.getenv("MACHINE_ID") or "").strip()
        or str(local_cfg.get("machine_id") or "").strip()
        or s.get("machine_id")
        or "default"
    )


def main() -> None:
    log_file = _setup_logging()
    local_cfg = _load_local_agent_config()
    parser = ArgumentParser(description="Agente de certificados PFX (Windows).")
    parser.add_argument("--once", action="store_true", help="Executa um ciclo e termina")
    parser.add_argument("--no-tray", action="store_true", help="Executa sem ícone de bandeja")
    parser.add_argument(
        "--mover",
        action="store_true",
        help="Após o scan, move certificados vencidos (só no disco local desta máquina).",
    )
    args = parser.parse_args()

    default_base = DEFAULT_ROBOT_BASE
    base = (
        os.getenv("CERT_ROBOT_BASE_URL")
        or str(local_cfg.get("cert_robot_base_url") or "").strip()
        or default_base
    ).strip().rstrip("/")
    api_key = (
        os.getenv("CERT_ROBOT_API_KEY")
        or str(local_cfg.get("cert_robot_api_key") or "").strip()
        or os.getenv("API_KEY")
        or ""
    ).strip()
    if not base:
        print(
            "Defina CERT_ROBOT_BASE_URL no .env (ex.: " + default_base + ")",
            file=sys.stderr,
        )
        raise SystemExit(1)

    interval = int(
        os.getenv("INTERVAL_SEC")
        or str(local_cfg.get("interval_sec") or "").strip()
        or "86400"
    )  # Padrão: a cada 24 horas
    mover_env = os.getenv("MOVER_VENCIDOS", "").strip().lower()
    mover_local = str(local_cfg.get("mover_vencidos", "")).strip().lower()
    mover = True
    if mover_local:
        mover = mover_local in ("1", "true", "yes", "on")
    if mover_env:
        mover = mover_env in ("1", "true", "yes", "on")
    if args.mover:
        mover = True

    LOGGER.info("Conectando a: %s", base)

    trigger_event = threading.Event()
    observer = None
    current_watch_path = None
    last_full_scan_time = 0.0
    connected = False
    quit_event = threading.Event()
    tray_ref: dict[str, pystray.Icon | None] = {"icon": None}

    def _notify(title: str, message: str) -> None:
        icon = tray_ref.get("icon")
        if icon:
            try:
                icon.notify(message, title=title)
            except Exception:
                LOGGER.exception("Falha ao exibir notificação")

    def _create_icon_image() -> Image.Image:
        img = Image.new("RGB", (64, 64), color=(33, 150, 243))
        draw = ImageDraw.Draw(img)
        draw.rectangle((10, 10, 54, 54), outline=(255, 255, 255), width=3)
        draw.rectangle((18, 18, 46, 46), fill=(255, 255, 255))
        return img

    def _quit_action(icon: pystray.Icon, _item) -> None:
        LOGGER.info("Encerrando agente por ação do usuário.")
        quit_event.set()
        trigger_event.set()
        icon.stop()

    def _rescan_action(_icon: pystray.Icon, _item) -> None:
        LOGGER.info("Rescan manual solicitado pelo menu da bandeja.")
        trigger_event.set()

    def _start_tray() -> None:
        if args.no_tray or args.once:
            return
        menu = pystray.Menu(
            pystray.MenuItem("Forçar leitura agora", _rescan_action),
            pystray.MenuItem("Sair", _quit_action),
        )
        icon = pystray.Icon("CertGuard Agent", _create_icon_image(), "CertGuard Agent", menu)
        tray_ref["icon"] = icon
        t = threading.Thread(target=icon.run, daemon=True)
        t.start()

    def _headers() -> dict:
        h: dict = {"Content-Type": "application/json"}
        if api_key:
            h["X-API-Key"] = api_key
        return h
    _start_tray()
    LOGGER.info("Logs em: %s", log_file)

    with httpx.Client(timeout=60.0) as client:
        while not quit_event.is_set():
            try:
                r = client.get(f"{base}/api/settings", headers=_headers())
            except httpx.ConnectError as e:
                if connected:
                    _notify("CertGuard Agent", "Conexão perdida com o portal.")
                connected = False
                LOGGER.error("Falha de conexão com API: %s", e)
                if args.once:
                    raise SystemExit(1) from e
                time.sleep(interval)
                continue
            if r.status_code == 401:
                connected = False
                _notify("CertGuard Agent", "Erro 401: configure a chave API no agente.")
                LOGGER.error("401: servidor exige chave API correta.")
                if args.once:
                    raise SystemExit(1)
                time.sleep(interval)
                continue
            if r.status_code == 404:
                connected = False
                _notify("CertGuard Agent", "Erro 404: URL do portal inválida no agente.")
                LOGGER.error("404 em /api/settings. Verifique CERT_ROBOT_BASE_URL.")
                if args.once:
                    raise SystemExit(1)
                time.sleep(interval)
                continue
            r.raise_for_status()
            if not connected:
                _notify("CertGuard Agent", "Conexão estabelecida com o portal.")
                LOGGER.info("Conexão com portal estabelecida.")
            connected = True
            s = r.json()
            try:
                src, exp = _resolve_paths(s, local_cfg)
            except Exception as e:  # noqa: BLE001
                LOGGER.warning("Aguardando configuração: %s", e)
                if observer:
                    observer.stop()
                    observer.join()
                    observer = None
                    current_watch_path = None
                if args.once:
                    raise SystemExit(1)
                time.sleep(10)
                continue

            if not src.is_dir():
                LOGGER.error("Pasta inexistente ou inacessível: %s", src)
                if args.once:
                    raise SystemExit(1)
                time.sleep(10)
                continue
            exp.mkdir(parents=True, exist_ok=True)
            exclude_dirs = [exp] if str(exp.resolve()).startswith(str(src.resolve())) else []

            if current_watch_path != str(src):
                if observer:
                    observer.stop()
                    observer.join()
                LOGGER.info("Iniciando monitoramento Watchdog na pasta %s (recursivo).", src)
                observer = Observer()
                event_handler = CertEventHandler(trigger_event, exp if exclude_dirs else None)
                observer.schedule(event_handler, str(src), recursive=True)
                observer.start()
                current_watch_path = str(src)
                trigger_event.set()

            mid = _machine_id(s, local_cfg)
            poll_commands = (
                os.getenv("POLL_COMMANDS")
                or str(local_cfg.get("poll_commands", "")).strip()
                or "1"
            )
            if poll_commands.strip().lower() not in (
                "0",
                "false",
                "no",
                "off",
            ):
                try:
                    nr = client.get(
                        f"{base}/api/agent/next",
                        params={"machine_id": mid},
                        headers=_headers(),
                    )
                    if nr.status_code == 200:
                        j = nr.json() or {}
                        cmd = j.get("command")
                        if cmd == "mover_vencidos" and j.get("id"):
                            itens_mv = scan_folder(src)
                            for c in itens_mv:
                                if c.status != CertStatus.EXPIRED:
                                    continue
                                try:
                                    move_to_expired(c, exp)
                                except OSError as ex:
                                    LOGGER.error("Comando mover_vencidos (%s): %s", c.file_name, ex)
                            LOGGER.info("Comando remoto mover_vencidos executado (id %s).", j.get("id"))
                        elif cmd == "rescan":
                            LOGGER.info("Comando remoto: rescan; máquina %s.", mid)
                            trigger_event.set()
                        elif cmd == "ping":
                            LOGGER.info("Comando remoto: ping; máquina %s.", mid)
                except httpx.HTTPError as e:
                    LOGGER.warning("Aviso em /api/agent/next: %s", e)

            now = time.time()
            if trigger_event.is_set() or (now - last_full_scan_time > interval):
                if trigger_event.is_set():
                    time.sleep(2)  # Debounce de 2s para o Windows terminar cópias
                    trigger_event.clear()
                    LOGGER.info("Mudança detectada (ou forçada). Processando...")
                else:
                    LOGGER.info("Executando ciclo periódico programado...")
                
                last_full_scan_time = time.time()
                
                itens = scan_folder(src, recursive=True, exclude_dirs=exclude_dirs)
                if mover:
                    for c in itens:
                        if c.status != CertStatus.EXPIRED:
                            continue
                        try:
                            move_to_expired(c, exp)
                        except OSError as ex:
                            LOGGER.error("Falha ao mover %s: %s", c.file_name, ex)
                    itens = scan_folder(src, recursive=True, exclude_dirs=exclude_dirs)

                payload = {
                    "machine_id": mid,
                    "source_folder": str(src),
                    "expired_folder": str(exp),
                    "items": [cert_to_public_dict(c) for c in itens],
                }
                try:
                    p = client.post(f"{base}/api/ingest", headers=_headers(), json=payload)
                    p.raise_for_status()
                    LOGGER.info(
                        "Enviado: %s itens; máquina: %s",
                        p.json().get("itens_recebidos"),
                        payload["machine_id"],
                    )
                except httpx.HTTPStatusError as e:
                    LOGGER.error("Erro HTTP ao enviar snapshot: %s", e.response.status_code)
                    _notify("CertGuard Agent", f"Erro HTTP ao enviar snapshot: {e.response.status_code}")
                except httpx.HTTPError as e:
                    LOGGER.error("Erro de conexão ao enviar snapshot: %s", e)
                    _notify("CertGuard Agent", "Erro de conexão ao enviar snapshot.")

            if args.once:
                if observer:
                    observer.stop()
                    observer.join()
                break
            
            trigger_event.wait(timeout=10.0)

    if observer:
        observer.stop()
        observer.join()
    if tray_ref.get("icon"):
        try:
            tray_ref["icon"].stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
