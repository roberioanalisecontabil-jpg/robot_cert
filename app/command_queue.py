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
COMMANDS = frozenset({"mover_vencidos", "rescan", "ping", "instalar_certificados"})

_file_lock = threading.Lock()
QUEUE_FILE = config.ROOT / "data" / "agent_command_queue.json"


@dataclass
class QueuedCommand:
    id: str
    machine_id: str
    command: str
    status: str
    created_at: str
    # Dado extra do comando. Em `instalar_certificados` carrega o token de uso
    # único: era gerado no /prepare e nunca chegava ao agente, então a
    # instalação nunca completava.
    payload: Optional[str] = None


def _supabase():
    # Reutiliza o singleton de settings_state para não criar um segundo client.
    from app.settings_state import _supabase as _sb
    return _sb()


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


def enqueue(machine_id: str, command: str, payload: Optional[str] = None) -> str:
    if command not in COMMANDS:
        raise ValueError(f"Comando inválido. Use: {', '.join(sorted(COMMANDS))}")
    mid = (machine_id or "").strip() or "default"
    now = datetime.now(timezone.utc).isoformat()
    cid = str(uuid.uuid4())
    row = {
        "id": cid,
        "machine_id": mid,
        "command": command,
        "status": "pending",
        "created_at": now,
    }
    if payload is not None:
        row["payload"] = payload

    client = _supabase()
    if client:
        try:
            client.table("agent_command_queue").insert(row).execute()
            return cid
        except Exception:  # noqa: BLE001
            logger.exception("Fila Supabase indisponível; a enfileirar em disco")
    with _file_lock:
        q = _load_file_queue()
        q.append(row)
        _save_file_queue(q)
    return cid


def pop_next_for_agent(machine_id: str) -> Optional[QueuedCommand]:
    """
    Retira e devolve o próximo comando em fila para este agente, ou None.
    Tenta Supabase primeiro; se vazio, consome a fila em arquivo (enfileiramentos de fallback).
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
            payload=row.get("payload"),
        )
        del q[i]
        _save_file_queue(q)
        return out
    return None


def _linha_para_comando(row: dict[str, Any]) -> QueuedCommand:
    return QueuedCommand(
        id=str(row.get("id")),
        machine_id=str(row.get("machine_id", "")),
        command=str(row.get("command", "")),
        status="popped",
        created_at=str(row.get("created_at", "")),
        payload=row.get("payload"),
    )


def _e_funcao_ausente(erro: Exception) -> bool:
    texto = str(erro).lower()
    return "pop_agent_command" in texto and (
        "could not find the function" in texto
        or "does not exist" in texto
        or "pgrst202" in texto
    )


def _pop_from_supabase(client: Any, agent: str) -> Optional[QueuedCommand]:
    """Retira o próximo comando desta máquina — atomicamente, quando dá.

    O caminho principal é a RPC `pop_agent_command` (migration 20260902110000):
    SELECT+DELETE numa transação com FOR UPDATE SKIP LOCKED, então dois
    consumidores do mesmo machine_id nunca levam o MESMO comando. Era o R8 do
    diagnóstico de 25/08/2026 — hoje um agente só mascara a corrida; a mina se
    desarma antes do dia em que houver dois.

    Sem a função no banco (deploy antes da migration), cai no SELECT+DELETE
    antigo com aviso: perde a atomicidade, não a fila — o padrão de resiliência
    a ordem de implantação usado em todo o projeto.
    """
    try:
        r = client.rpc("pop_agent_command", {"p_machine_id": agent}).execute()
        rows = r.data or []
        return _linha_para_comando(rows[0]) if rows else None
    except Exception as e:  # noqa: BLE001
        if _e_funcao_ausente(e):
            logger.warning(
                "Função pop_agent_command ausente (rode a migration "
                "20260902110000); usando o pop em duas idas, sem atomicidade."
            )
        else:
            logger.exception("pop atômico falhou; tentando o caminho antigo")

    # ── Caminho legado: SELECT e depois DELETE, em duas idas ──────────────
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
        return _linha_para_comando(row)
    return None


def list_pending() -> List[dict[str, Any]]:
    """
    Comandos pendentes para monitorização no portal.

    NÃO devolve `payload`: em instalar_certificados ele carrega o token de uso
    único, e esta lista é exposta em /api/agent/queue. A seleção de colunas
    abaixo é explícita de propósito — não trocar por select("*").
    """
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
