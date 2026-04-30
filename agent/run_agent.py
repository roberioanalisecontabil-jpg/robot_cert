"""Agente Windows em background com tray, logs e notificações."""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from typing import Optional, Tuple
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
# Instalador PyInstaller: .env e agent_config.json ficam ao lado do .exe
if getattr(sys, "frozen", False):
    load_dotenv(Path(sys.executable).resolve().parent / ".env", override=True)

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


@dataclass(frozen=True)
class AgentRunConfig:
    """Opções equivalentes à linha de comandos (para serviço Windows ou CLI)."""

    once: bool = False
    no_tray: bool = False
    mover_cli: bool = False


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


def _httpx_timeout() -> httpx.Timeout:
    """Conecta/ler com margem; portal remoto ou ingest lentos podem precisar de read maior."""
    read_s = float(os.getenv("AGENT_HTTP_READ_SEC", "300"))
    connect_s = float(os.getenv("AGENT_HTTP_CONNECT_SEC", "15"))
    return httpx.Timeout(connect=connect_s, read=read_s, write=60.0, pool=10.0)


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


def _http_transient_codes() -> frozenset[int]:
    """Códigos em que faz sentido voltar a tentar (portal em deploy, Render a aquecer)."""
    return frozenset({408, 425, 429, 502, 503, 504})


def _settings_retries() -> int:
    return max(1, int(os.getenv("AGENT_SETTINGS_RETRIES", "8")))


def _settings_retry_base_sec() -> float:
    return max(1.0, float(os.getenv("AGENT_SETTINGS_RETRY_WAIT_SEC", "5")))


def _settings_cache_path() -> Path:
    return _app_dir() / ".certguard_cached_settings.json"


def _save_settings_cache(payload: dict) -> None:
    """Guarda fonte/expired/machine_id para sobreviver a quedas breves do portal."""
    path = _settings_cache_path()
    try:
        path.write_text(
            json.dumps(
                {
                    "saved_at_epoch": time.time(),
                    "source_folder": payload.get("source_folder") or "",
                    "expired_folder": payload.get("expired_folder") or "",
                    "machine_id": payload.get("machine_id") or "default",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        LOGGER.exception("Não foi possível gravar cache local de settings")


def _load_settings_cache() -> dict | None:
    path = _settings_cache_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            max_age_h = float(os.getenv("AGENT_SETTINGS_CACHE_MAX_AGE_HOURS", "168"))
            if max_age_h > 0:
                age_sec = time.time() - float(raw.get("saved_at_epoch", 0))
                if age_sec > max_age_h * 3600:
                    return None
            return {
                "source_folder": str(raw.get("source_folder") or ""),
                "expired_folder": str(raw.get("expired_folder") or ""),
                "machine_id": str(raw.get("machine_id") or "default"),
            }
    except (json.JSONDecodeError, OSError, TypeError):
        LOGGER.exception("Cache local de settings inválido ou ilegível")
    return None


def _fallback_cache_allowed() -> bool:
    return os.getenv("AGENT_USE_SETTINGS_CACHE", "1").strip().lower() not in ("0", "false", "no", "off")


def fetch_portal_settings(
    client: httpx.Client,
    base: str,
    headers_factory,
) -> Tuple[Optional[dict], Optional[str]]:
    """
    GET /api/settings com várias tentativas e backoff.
    Devolve (payload, None) em sucesso; (None, 'unauthorized'|'not_found'|'unavailable').
    """
    retries = _settings_retries()
    base_sleep = _settings_retry_base_sec()
    transient = _http_transient_codes()

    last_status: int | None = None
    for attempt in range(1, retries + 1):
        try:
            r = client.get(f"{base}/api/settings", headers=headers_factory())
        except (httpx.ConnectError, httpx.TimeoutException, httpx.ReadError) as e:
            LOGGER.warning(
                "Falha de rede ao ler /api/settings (tentativa %s/%s): %s",
                attempt,
                retries,
                e,
            )
            if attempt < retries:
                wait = min(90.0, base_sleep * (2 ** (attempt - 1)))
                time.sleep(wait)
            continue
        last_status = r.status_code

        if r.status_code == 401:
            return (None, "unauthorized")
        if r.status_code == 404:
            return (None, "not_found")

        if r.status_code in transient:
            LOGGER.warning(
                "Portal temporariamente indisponível (%s) em /api/settings; tentativa %s/%s",
                r.status_code,
                attempt,
                retries,
            )
            if attempt < retries:
                wait = min(120.0, base_sleep * (2 ** (attempt - 1)))
                LOGGER.info("Nova tentativa daqui a %.0fs", wait)
                time.sleep(wait)
            continue

        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            LOGGER.error("HTTP %s ao ler /api/settings: %s", e.response.status_code, e)
            if attempt < retries and e.response.status_code >= 500:
                wait = min(120.0, base_sleep * (2 ** (attempt - 1)))
                time.sleep(wait)
                continue
            LOGGER.error(
                "Esgotadas tentativas com erro HTTP não transitório ao ler settings"
            )
            return (None, "unavailable")

        body = r.json()
        if isinstance(body, dict):
            return (body, None)

        LOGGER.error("Resposta JSON inesperada de /api/settings")
        return (None, "unavailable")

    LOGGER.error(
        "Esgotaram-se as tentativas de GET /api/settings (último HTTP=%s)",
        last_status,
    )
    return (None, "unavailable")


def _ingest_retries() -> int:
    return max(1, int(os.getenv("AGENT_INGEST_RETRIES", "5")))


def _ingest_retry_base_sec() -> float:
    return max(1.0, float(os.getenv("AGENT_INGEST_RETRY_WAIT_SEC", "4")))


def run_agent_application(quit_event: threading.Event, cfg: AgentRunConfig) -> None:
    log_file = _setup_logging()
    local_cfg = _load_local_agent_config()

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
    if cfg.mover_cli:
        mover = True

    LOGGER.info("Conectando a: %s", base)

    trigger_event = threading.Event()
    observer = None
    current_watch_path = None
    last_full_scan_time = 0.0
    connected = False
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
        if cfg.no_tray or cfg.once:
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

    with httpx.Client(timeout=_httpx_timeout()) as client:
        while not quit_event.is_set():
            s_payload, fetch_err = fetch_portal_settings(client, base, _headers)
            s = s_payload
            from_cache = False

            if fetch_err == "unauthorized":
                connected = False
                _notify("CertGuard Agent", "Erro 401: configure a chave API no agente.")
                LOGGER.error("401: servidor exige chave API correta.")
                if cfg.once:
                    raise SystemExit(1)
                time.sleep(interval)
                continue
            if fetch_err == "not_found":
                connected = False
                _notify("CertGuard Agent", "Erro 404: URL do portal inválida no agente.")
                LOGGER.error("404 em /api/settings. Verifique CERT_ROBOT_BASE_URL.")
                if cfg.once:
                    raise SystemExit(1)
                time.sleep(interval)
                continue

            if s is None and _fallback_cache_allowed():
                cached = _load_settings_cache()
                if cached:
                    LOGGER.warning(
                        "Portal indisponível; a usar pastas gravadas localmente desde a última conexão."
                    )
                    s = cached
                    from_cache = True

            if s is None:
                if connected:
                    _notify(
                        "CertGuard Agent",
                        "Portal indisponível. Novas tentativas em ciclo seguinte.",
                    )
                connected = False
                LOGGER.error(
                    "Não foi possível obter /api/settings (sem cache). Aguardando antes de tentar novamente."
                )
                if cfg.once:
                    raise SystemExit(1)
                wait_loop = min(120.0, float(max(30, min(interval, 300))))
                time.sleep(wait_loop)
                continue

            if not from_cache:
                _save_settings_cache(s)

            if not connected and not from_cache:
                _notify("CertGuard Agent", "Conexão estabelecida com o portal.")
                LOGGER.info("Conexão com portal estabelecida.")
            if from_cache:
                LOGGER.info("Continuando com configuração em cache até o portal voltar.")

            connected = True
            try:
                src, exp = _resolve_paths(s, local_cfg)
            except Exception as e:  # noqa: BLE001
                LOGGER.warning("Aguardando configuração: %s", e)
                if observer:
                    observer.stop()
                    observer.join()
                    observer = None
                    current_watch_path = None
                if cfg.once:
                    raise SystemExit(1)
                time.sleep(10)
                continue

            if not src.is_dir():
                LOGGER.error("Pasta inexistente ou inacessível: %s", src)
                if cfg.once:
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
                transient_codes = _http_transient_codes()
                max_ingest = _ingest_retries()
                ingest_base = _ingest_retry_base_sec()
                sent_ok = False
                for ingest_try in range(1, max_ingest + 1):
                    try:
                        p = client.post(f"{base}/api/ingest", headers=_headers(), json=payload)
                    except (httpx.ConnectError, httpx.TimeoutException, httpx.ReadError) as e:
                        LOGGER.warning(
                            "Rede ao enviar snapshot (%s/%s): %s", ingest_try, max_ingest, e
                        )
                        if ingest_try < max_ingest:
                            time.sleep(min(90.0, ingest_base * (2 ** (ingest_try - 1))))
                            continue
                        LOGGER.error("Falha de rede repetida ao enviar snapshot.")
                        _notify(
                            "CertGuard Agent",
                            "Erro de conexão ao enviar snapshot; tentará no próximo ciclo.",
                        )
                        break

                    if p.status_code in transient_codes and ingest_try < max_ingest:
                        wait = min(120.0, ingest_base * (2 ** (ingest_try - 1)))
                        LOGGER.warning(
                            "Servidor (%s) ao enviar snapshot; nova tentativa em %.0fs",
                            p.status_code,
                            wait,
                        )
                        time.sleep(wait)
                        continue

                    try:
                        p.raise_for_status()
                    except httpx.HTTPStatusError as e:
                        LOGGER.error(
                            "Erro HTTP ao enviar snapshot: %s", e.response.status_code
                        )
                        _notify(
                            "CertGuard Agent",
                            f"Erro HTTP ao enviar snapshot: {e.response.status_code}",
                        )
                        break

                    try:
                        body = p.json()
                    except json.JSONDecodeError:
                        body = {}
                    LOGGER.info(
                        "Enviado: %s itens; máquina: %s",
                        body.get("itens_recebidos"),
                        payload["machine_id"],
                    )
                    sent_ok = True
                    break

            if cfg.once:
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


def main() -> None:
    parser = ArgumentParser(description="Agente de certificados PFX (Windows).")
    parser.add_argument("--once", action="store_true", help="Executa um ciclo e termina")
    parser.add_argument("--no-tray", action="store_true", help="Executa sem ícone de bandeja")
    parser.add_argument(
        "--mover",
        action="store_true",
        help="Após o scan, move certificados vencidos (só no disco local desta máquina).",
    )
    args = parser.parse_args()
    run_agent_application(
        threading.Event(),
        AgentRunConfig(once=args.once, no_tray=args.no_tray, mover_cli=args.mover),
    )


def _fatal_restart_backoff_sec() -> float:
    raw = os.getenv("AGENT_RESTART_ON_FATAL_SEC", "0").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.0


if __name__ == "__main__":
    restart_sec = _fatal_restart_backoff_sec()
    while True:
        try:
            main()
            break
        except SystemExit:
            raise
        except KeyboardInterrupt:
            raise
        except BaseException:
            if restart_sec <= 0:
                raise
            LOGGER.exception(
                "Falha inesperada no agente; a reiniciar daqui a %.0fs", restart_sec
            )
            time.sleep(restart_sec)
