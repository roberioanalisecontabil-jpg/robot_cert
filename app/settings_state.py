from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app import config

logger = logging.getLogger(__name__)

DATA_FILE = config.ROOT / "data" / "portal_settings.json"


@dataclass
class PortalSettings:
    source_folder: str
    expired_folder: str
    machine_id: str = "default"

    def effective_source(self) -> Path:
        p = (self.source_folder or "").strip()
        if p:
            return Path(p)
        return config.CERT_SOURCE_DIR

    def effective_expired(self) -> Path:
        p = (self.expired_folder or "").strip()
        if p:
            return Path(p)
        return config.CERT_EXPIRED_DIR


def _from_row(row: dict) -> PortalSettings:
    return PortalSettings(
        source_folder=str(row.get("source_folder", "") or ""),
        expired_folder=str(row.get("expired_folder", "") or ""),
        machine_id=str(row.get("machine_id", "default") or "default"),
    )


def _load_file() -> Optional[PortalSettings]:
    if not DATA_FILE.is_file():
        return None
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        return PortalSettings(
            source_folder=str(raw.get("source_folder", "")),
            expired_folder=str(raw.get("expired_folder", "")),
            machine_id=str(raw.get("machine_id", "default")),
        )
    except (json.JSONDecodeError, OSError):
        return None


def _save_file(s: PortalSettings) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {**asdict(s), "updated_at": datetime.now(timezone.utc).isoformat()}
    DATA_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _supabase():
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return None
    from supabase import create_client  # type: ignore[import-untyped]

    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


def load_settings() -> PortalSettings:
    client = _supabase()
    if client:
        try:
            r = client.table("portal_settings").select("*").eq("id", 1).limit(1).execute()
            rows = r.data
            if rows:
                supa = _from_row(rows[0])
                # Se o Supabase tem pastas vazias, tenta complementar com o ficheiro local
                if not supa.source_folder.strip() and not supa.expired_folder.strip():
                    local = _load_file()
                    if local and (local.source_folder.strip() or local.expired_folder.strip()):
                        # Mantém machine_id do Supabase, pastas do ficheiro local
                        return PortalSettings(
                            source_folder=local.source_folder,
                            expired_folder=local.expired_folder,
                            machine_id=supa.machine_id or local.machine_id,
                        )
                return supa
        except Exception:  # noqa: BLE001
            logger.exception("Falha ao ler portal_settings no Supabase; a usar ficheiro local")
    s = _load_file()
    if s:
        return s
    return PortalSettings(
        source_folder="",
        expired_folder="",
        machine_id="default",
    )


def save_settings(s: PortalSettings) -> None:
    """
    Grava em data/portal_settings.json sempre. Com Supabase, faz upsert (insert ou update)
    para a linha id=1, pois update em linha inexistente não grava nada.
    """
    _save_file(s)
    client = _supabase()
    if not client:
        return
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "id": 1,
        "source_folder": s.source_folder,
        "expired_folder": s.expired_folder,
        "machine_id": s.machine_id,
        "updated_at": now,
    }
    try:
        client.table("portal_settings").upsert(row, on_conflict="id").execute()
    except Exception:  # noqa: BLE001
        logger.exception(
            "Falha ao gravar no Supabase; a configuração foi guardada em %s", DATA_FILE
        )


INGEST_FILE = config.ROOT / "data" / "last_ingest.json"


def _save_snapshot_to_file(
    machine_id: str,
    source_folder: str,
    expired_folder: str,
    scanned_iso: str,
    items: List[dict[str, Any]],
) -> None:
    """Grava o snapshot em ficheiro local (fallback ou modo sem Supabase)."""
    INGEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    INGEST_FILE.write_text(
        json.dumps(
            {
                "machine_id": machine_id,
                "source_folder": source_folder,
                "expired_folder": expired_folder,
                "scanned_at": scanned_iso,
                "items": items,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def save_snapshot(
    machine_id: str,
    source_folder: str,
    expired_folder: str,
    items: List[dict[str, Any]],
) -> None:
    scanned = datetime.now(timezone.utc)
    scanned_iso = scanned.isoformat()
    client = _supabase()
    if client:
        try:
            client.table("cert_snapshots").insert(
                {
                    "machine_id": machine_id,
                    "source_folder": source_folder,
                    "expired_folder": expired_folder,
                    "scanned_at": scanned_iso,
                    "items": items,
                }
            ).execute()
        except Exception:  # noqa: BLE001
            logger.exception(
                "Falha ao gravar snapshot no Supabase; a guardar em %s", INGEST_FILE
            )
            _save_snapshot_to_file(machine_id, source_folder, expired_folder, scanned_iso, items)
    else:
        _save_snapshot_to_file(machine_id, source_folder, expired_folder, scanned_iso, items)


def get_latest_snapshot() -> Optional[dict]:
    """
    Retorna o snapshot mais recente, qualquer machine_id, ou None.
    """
    client = _supabase()
    if client:
        r = (
            client.table("cert_snapshots")
            .select("*")
            .order("scanned_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = r.data
        if rows:
            return rows[0]
    if INGEST_FILE.is_file():
        try:
            return json.loads(INGEST_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


COLAB_SELECAO_FILE = config.ROOT / "data" / "colaborador_certificados.json"


def _load_colaborador_file_dict() -> Dict[str, List[str]]:
    if not COLAB_SELECAO_FILE.is_file():
        return {}
    try:
        data = json.loads(COLAB_SELECAO_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            out: Dict[str, List[str]] = {}
            for k, v in data.items():
                if isinstance(v, list):
                    out[str(k).strip().lower()] = [str(x).strip() for x in v if str(x).strip()]
            return out
    except (json.JSONDecodeError, OSError):
        return {}
    return {}


def _save_colaborador_file_dict(data: Dict[str, List[str]]) -> None:
    COLAB_SELECAO_FILE.parent.mkdir(parents=True, exist_ok=True)
    COLAB_SELECAO_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_colaborador_selecao(email: str) -> List[str]:
    """
    Documentos (CNPJ/CPF só dígitos) que o utilizador escolheu para acompanhar.
    Com Supabase, lê da tabela `colaborador_cert_selecoes`; senão do ficheiro local.
    """
    key = (email or "").strip().lower()
    if not key:
        return []
    client = _supabase()
    if client:
        try:
            r = (
                client.table("colaborador_cert_selecoes")
                .select("documentos")
                .eq("user_email", key)
                .limit(1)
                .execute()
            )
            rows = r.data or []
            if rows:
                docs = rows[0].get("documentos")
                if isinstance(docs, list):
                    return [str(x).strip() for x in docs if str(x).strip()]
            return []
        except Exception:  # noqa: BLE001
            logger.exception(
                "Falha ao ler colaborador_cert_selecoes no Supabase; a usar ficheiro local"
            )
    return _load_colaborador_file_dict().get(key, [])


def save_colaborador_selecao(email: str, docs: List[str]) -> None:
    """Grava sempre no ficheiro local; com Supabase faz upsert por e-mail."""
    key = (email or "").strip().lower()
    if not key:
        return
    clean = [str(x).strip() for x in docs if str(x).strip()]
    merged = _load_colaborador_file_dict()
    merged[key] = clean
    _save_colaborador_file_dict(merged)
    client = _supabase()
    if not client:
        return
    now = datetime.now(timezone.utc).isoformat()
    row = {"user_email": key, "documentos": clean, "updated_at": now}
    try:
        client.table("colaborador_cert_selecoes").upsert(row, on_conflict="user_email").execute()
    except Exception:  # noqa: BLE001
        logger.exception(
            "Falha ao gravar colaborador_cert_selecoes no Supabase; seleção ficou em %s",
            COLAB_SELECAO_FILE,
        )


def supabase_configured() -> bool:
    return bool(config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY)
