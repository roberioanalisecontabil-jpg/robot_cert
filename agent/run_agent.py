"""
Agente Windows: lê a configuração publicada na API, escaneia a pasta local e envia o snapshot.
Execute em segundo plano (Agendador de Tarefas) com o mesmo Python onde está o projeto.

Variáveis de ambiente (ficheiro .env ao lado deste script ou do projeto):

  CERT_ROBOT_BASE_URL  — URL do FastAPI (padrão: http://127.0.0.1:8020, para não colidir com a 8000)
  CERT_ROBOT_API_KEY   — Igual a API_KEY no servidor; omita se o servidor não usar chave
  AGENT_SOURCE         — (opcional) se o portal tiver source vazio, usa este caminho
  AGENT_EXPIRED        — (opcional) idem para pasta de vencidos
  MACHINE_ID           — (opcional) id da máquina; senão vindo do portal
  INTERVAL_SEC         — (opcional) segundos entre ciclos, padrão 300
  MOVER_VENCIDOS       — (opcional) 1 = após o scan, move vencidos localmente
  POLL_COMMANDS        — (opcional) 0 = não pergunta /api/agent/next; padrão 1
"""

from __future__ import annotations

import os
import sys
import time
import threading
import json
from argparse import ArgumentParser
from pathlib import Path

import httpx
from dotenv import load_dotenv
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
    def __init__(self, trigger_event: threading.Event):
        super().__init__()
        self.trigger_event = trigger_event

    def on_created(self, event):
        self._check(event)

    def on_modified(self, event):
        self._check(event)

    def on_deleted(self, event):
        self._check(event)

    def _check(self, event):
        if event.is_directory:
            return
        p = event.src_path.lower()
        if p.endswith(".pfx") or p.endswith(".p12"):
            self.trigger_event.set()


def _machine_id(s: dict, local_cfg: dict) -> str:
    return (
        (os.getenv("MACHINE_ID") or "").strip()
        or str(local_cfg.get("machine_id") or "").strip()
        or s.get("machine_id")
        or "default"
    )


def main() -> None:
    local_cfg = _load_local_agent_config()
    parser = ArgumentParser(description="Agente de certificados PFX (Windows).")
    parser.add_argument("--once", action="store_true", help="Executa um ciclo e termina")
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
    mover_env = os.getenv("MOVER_VENCIDOS", "").strip()
    mover_local = str(local_cfg.get("mover_vencidos", "")).strip()
    mover = args.mover or (mover_env in ("1", "true", "True", "yes")) or (
        mover_local in ("1", "true", "True", "yes")
    )

    print(f"Conectando a: {base}", file=sys.stderr)

    trigger_event = threading.Event()
    observer = None
    current_watch_path = None
    last_full_scan_time = 0.0

    def _headers() -> dict:
        h: dict = {"Content-Type": "application/json"}
        if api_key:
            h["X-API-Key"] = api_key
        return h
    with httpx.Client(timeout=60.0) as client:
        while True:
            try:
                r = client.get(f"{base}/api/settings", headers=_headers())
            except httpx.ConnectError as e:
                print(
                    "Não deu para ligar ao API. Ligue o servidor (porta padrão deste projeto: "
                    f"{DEFAULT_ROBOT_API_PORT}): "
                    f"python -m uvicorn app.main:app --host 127.0.0.1 --port {DEFAULT_ROBOT_API_PORT}",
                    file=sys.stderr,
                )
                print(e, file=sys.stderr)
                if args.once:
                    raise SystemExit(1) from e
                time.sleep(interval)
                continue
            if r.status_code == 401:
                print(
                    "401: o servidor exige chave. Defina CERT_ROBOT_API_KEY no .env "
                    "com o mesmo valor de API_KEY do servidor.",
                    file=sys.stderr,
                )
                if args.once:
                    raise SystemExit(1)
                time.sleep(interval)
                continue
            if r.status_code == 404:
                print(
                    "404 em /api/settings: ajuste CERT_ROBOT_BASE_URL (URL do uvicorn cert_robot) "
                    f"e confirme: python -m uvicorn app.main:app --host 127.0.0.1 --port {DEFAULT_ROBOT_API_PORT}",
                    file=sys.stderr,
                )
                if args.once:
                    raise SystemExit(1)
                time.sleep(interval)
                continue
            r.raise_for_status()
            s = r.json()
            try:
                src, exp = _resolve_paths(s, local_cfg)
            except Exception as e:  # noqa: BLE001
                print("Aguardando configuração:", e, file=sys.stderr)
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
                print("Pasta inexistente ou inacessível:", src, file=sys.stderr)
                if args.once:
                    raise SystemExit(1)
                time.sleep(10)
                continue
            exp.mkdir(parents=True, exist_ok=True)

            if current_watch_path != str(src):
                if observer:
                    observer.stop()
                    observer.join()
                print(f"Iniciando monitoramento em tempo real (Watchdog) na pasta: {src}", file=sys.stderr)
                observer = Observer()
                event_handler = CertEventHandler(trigger_event)
                observer.schedule(event_handler, str(src), recursive=False)
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
                                    print("Comando mover_vencidos:", c.file_name, ex, file=sys.stderr)
                            print(
                                "Comando remoto mover_vencidos executado; id:",
                                j.get("id"),
                                file=sys.stderr,
                            )
                        elif cmd == "rescan":
                            print(
                                "Comando remoto: rescan; forçando novo ciclo; máquina",
                                mid,
                                file=sys.stderr,
                            )
                            trigger_event.set()
                        elif cmd == "ping":
                            print("Comando remoto: ping; máquina", mid, file=sys.stderr)
                except httpx.HTTPError as e:
                    print("Aviso: /api/agent/next", e, file=sys.stderr)

            now = time.time()
            if trigger_event.is_set() or (now - last_full_scan_time > interval):
                if trigger_event.is_set():
                    time.sleep(2)  # Debounce de 2s para o Windows terminar cópias
                    trigger_event.clear()
                    print("Mudança detectada (ou forçada). Processando...", file=sys.stderr)
                else:
                    print("Executando ciclo periódico programado...", file=sys.stderr)
                
                last_full_scan_time = time.time()
                
                itens = scan_folder(src)
                if mover:
                    for c in itens:
                        if c.status != CertStatus.EXPIRED:
                            continue
                        try:
                            move_to_expired(c, exp)
                        except OSError as ex:
                            print("Falha ao mover", c.file_name, ex, file=sys.stderr)
                    itens = scan_folder(src)

                payload = {
                    "machine_id": mid,
                    "source_folder": str(src),
                    "expired_folder": str(exp),
                    "items": [cert_to_public_dict(c) for c in itens],
                }
                try:
                    p = client.post(f"{base}/api/ingest", headers=_headers(), json=payload)
                    p.raise_for_status()
                    print("Enviado:", p.json().get("itens_recebidos"), "itens; máquina:", payload["machine_id"])
                except httpx.HTTPStatusError as e:
                    print(
                        f"Erro HTTP ao enviar snapshot: {e.response.status_code}",
                        file=sys.stderr,
                    )
                except httpx.HTTPError as e:
                    print("Erro de conexão ao enviar snapshot:", e, file=sys.stderr)

            if args.once:
                if observer:
                    observer.stop()
                    observer.join()
                break
            
            trigger_event.wait(timeout=10.0)


if __name__ == "__main__":
    main()
