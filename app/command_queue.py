from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Optional

from app import config

logger = logging.getLogger(__name__)

# Comandos reconhecidos pelo agente
COMMANDS = frozenset({"mover_vencidos", "rescan", "ping"})

_file_lock = threading.Lock()
QUEUE_FILE = config.ROOT / "data" / "agent_command_queue.json"


@dataclass
class QueuedCommand:
    id: str
    machine_id: str
    command: str
    status: str
    created_at: str


def _supabase():
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return None
    from supabase import create_client  # type: ignore[import-untyped]

    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


def _load_file_queue() -> List[dict[str, Any]]:
    if not QUEUE_FILE.is_file():
        return []
    try:
        raw = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        return list(raw.get("commands", []))
    except (json.JSONDecodeError, OSError, TypeError):
        return []


def _save_file_queue(commands: List[dict[str, Any]]) -> None:
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(
        json.dumps({"commands": commands}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _matches_agent(row_machine: str, agent_id: str) -> bool:
    a = (row_machine or "").strip()
    b = (agent_id or "").strip() or "default"
    if a in ("*", "all", "qualquer"):
        return True
    return a == b


def enqueue(machine_id: str, command: str) -> str:
    if command not in COMMANDS:
        raise ValueError(f"Comando inválido. Use: {', '.join(sorted(COMMANDS))}")
    mid = (machine_id or "").strip() or "default"
    now = datetime.now(timezone.utc).isoformat()
    cid = str(uuid.uuid4())
    client = _supabase()
    if client:
        try:
            client.table("agent_command_queue").insert(
                {
                    "id": cid,
                    "machine_id": mid,
                    "command": command,
                    "status": "pending",
                    "created_at": now,
                }
            ).execute()
            return cid
        except Exception:  # noqa: BLE001
            logger.exception("Fila Supabase indisponível; a enfileirar em disco")
    with _file_lock:
        q = _load_file_queue()
        q.append(
            {
                "id": cid,
                "machine_id": mid,
                "command": command,
                "status": "pending",
                "created_at": now,
            }
        )
        _save_file_queue(q)
    return cid


def pop_next_for_agent(machine_id: str) -> Optional[QueuedCommand]:
    """
    Retira e devolve o próximo comando em fila para este agente, ou None.
    Tenta Supabase primeiro; se vazio, consome a fila em ficheiro (enfileiramentos de fallback).
    """
    agent = (machine_id or "").strip() or "default"
    client = _supabase()
    if client:
        r = _pop_from_supabase(client, agent)
        if r:
            return r
    with _file_lock:
        return _pop_from_file(agent)


def _pop_from_file(agent: str) -> Optional[QueuedCommand]:
    q = _load_file_queue()
    for i, row in enumerate(q):
        if row.get("status") != "pending":
            continue
        if not _matches_agent(str(row.get("machine_id", "")), agent):
            continue
        out = QueuedCommand(
            id=str(row["id"]),
            machine_id=str(row.get("machine_id", "")),
            command=str(row["command"]),
            status="popped",
            created_at=str(row.get("created_at", "")),
        )
        del q[i]
        _save_file_queue(q)
        return out
    return None


def _pop_from_supabase(client: Any, agent: str) -> Optional[QueuedCommand]:
    try:
        r = (
            client.table("agent_command_queue")
            .select("*")
            .eq("status", "pending")
            .order("created_at", desc=False)
            .execute()
        )
        rows = r.data or []
    except Exception:  # noqa: BLE001
        logger.exception("listar fila no Supabase")
        return _pop_from_file(agent)
    for row in rows:
        if not _matches_agent(str(row.get("machine_id", "")), agent):
            continue
        cid = str(row.get("id"))
        try:
            client.table("agent_command_queue").delete().eq("id", cid).execute()
        except Exception:  # noqa: BLE001
            logger.exception("remover comando da fila (Supabase); id=%s", cid)
            return None
        return QueuedCommand(
            id=cid,
            machine_id=str(row.get("machine_id", "")),
            command=str(row.get("command", "")),
            status="popped",
            created_at=str(row.get("created_at", "")),
        )
    return None


def list_pending() -> List[dict[str, Any]]:
    out: List[dict[str, Any]] = []
    client = _supabase()
    if client:
        try:
            r = (
                client.table("agent_command_queue")
                .select("id, machine_id, command, status, created_at")
                .eq("status", "pending")
                .order("created_at", desc=False)
                .execute()
            )
            out.extend(dict(row) for row in (r.data or []))
        except Exception:  # noqa: BLE001
            logger.exception("list_pending supabase")
    with _file_lock:
        for row in _load_file_queue():
            if row.get("status") == "pending":
                out.append(
                    {
                        "id": row.get("id"),
                        "machine_id": row.get("machine_id"),
                        "command": row.get("command"),
                        "status": row.get("status"),
                        "created_at": row.get("created_at"),
                    }
                )
    return out
