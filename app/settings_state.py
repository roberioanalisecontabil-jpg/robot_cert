from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app import config
from app.historico_agg_cache import invalidate_all as _invalidate_historico_agg_cache

logger = logging.getLogger(__name__)

DATA_FILE = config.ROOT / "data" / "portal_settings.json"


@dataclass
class PortalSettings:
    source_folder: str
    expired_folder: str
    machine_id: str = "default"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password_encrypted: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    smtp_from_email: str = ""
    smtp_alerts_enabled: bool = False

    # ── Módulo instalador (leva 3b, 15/08/2026) ────────────────────────────
    # Vazio/zero significa "usar o padrão do código", e não "desligado". A
    # distinção importa: uma configuração nunca tocada tem de se comportar
    # exatamente como antes de existir.
    instalador_nome_template: str = ""
    install_token_ttl_min: int = 0
    install_log_retencao_dias: int = 0

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
        smtp_host=str(row.get("smtp_host", "") or ""),
        smtp_port=int(row.get("smtp_port", 587) if row.get("smtp_port") is not None else 587),
        smtp_user=str(row.get("smtp_user", "") or ""),
        smtp_password_encrypted=str(row.get("smtp_password_encrypted", "") or ""),
        smtp_use_tls=bool(row.get("smtp_use_tls") if row.get("smtp_use_tls") is not None else True),
        smtp_use_ssl=bool(row.get("smtp_use_ssl") if row.get("smtp_use_ssl") is not None else False),
        smtp_from_email=str(row.get("smtp_from_email", "") or ""),
        smtp_alerts_enabled=bool(row.get("smtp_alerts_enabled") if row.get("smtp_alerts_enabled") is not None else False),
        instalador_nome_template=str(row.get("instalador_nome_template", "") or ""),
        install_token_ttl_min=int(row.get("install_token_ttl_min") or 0),
        install_log_retencao_dias=int(row.get("install_log_retencao_dias") or 0),
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
            smtp_host=str(raw.get("smtp_host", "")),
            smtp_port=int(raw.get("smtp_port", 587)),
            smtp_user=str(raw.get("smtp_user", "")),
            smtp_password_encrypted=str(raw.get("smtp_password_encrypted", "")),
            smtp_use_tls=bool(raw.get("smtp_use_tls", True)),
            smtp_use_ssl=bool(raw.get("smtp_use_ssl", False)),
            smtp_from_email=str(raw.get("smtp_from_email", "")),
            smtp_alerts_enabled=bool(raw.get("smtp_alerts_enabled", False)),
            instalador_nome_template=str(raw.get("instalador_nome_template", "")),
            install_token_ttl_min=int(raw.get("install_token_ttl_min", 0) or 0),
            install_log_retencao_dias=int(raw.get("install_log_retencao_dias", 0) or 0),
        )
    except (json.JSONDecodeError, OSError):
        return None


def _save_file(s: PortalSettings) -> None:
    try:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {**asdict(s), "updated_at": datetime.now(timezone.utc).isoformat()}
        DATA_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning(f"Falha ao salvar portal_settings.json localmente (ambiente read-only / Vercel): {e}")


# Singleton: o cliente Supabase é criado uma única vez e reutilizado.
# Antes: cada chamada a _supabase() criava um novo client (~15-25 MB),
# gerando dezenas de instâncias por minuto e estourando a memória.
_supabase_client = None


def _supabase():
    global _supabase_client
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return None
    if _supabase_client is None:
        from supabase import create_client  # type: ignore[import-untyped]
        _supabase_client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
    return _supabase_client


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
                    if local:
                        # Mantém pastas locais e SMTP local se vazios no Supabase
                        supa.source_folder = local.source_folder
                        supa.expired_folder = local.expired_folder
                        if not supa.smtp_host.strip():
                            supa.smtp_host = local.smtp_host
                            supa.smtp_port = local.smtp_port
                            supa.smtp_user = local.smtp_user
                            supa.smtp_password_encrypted = local.smtp_password_encrypted
                            supa.smtp_use_tls = local.smtp_use_tls
                            supa.smtp_use_ssl = local.smtp_use_ssl
                            supa.smtp_from_email = local.smtp_from_email
                            supa.smtp_alerts_enabled = local.smtp_alerts_enabled
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
        "smtp_host": s.smtp_host,
        "smtp_port": s.smtp_port,
        "smtp_user": s.smtp_user,
        "smtp_password_encrypted": s.smtp_password_encrypted,
        "smtp_use_tls": s.smtp_use_tls,
        "smtp_use_ssl": s.smtp_use_ssl,
        "smtp_from_email": s.smtp_from_email,
        "smtp_alerts_enabled": s.smtp_alerts_enabled,
        "instalador_nome_template": s.instalador_nome_template,
        "install_token_ttl_min": s.install_token_ttl_min,
        "install_log_retencao_dias": s.install_log_retencao_dias,
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

    _invalidate_historico_agg_cache()


def upsert_cert_history(
    machine_id: str,
    scanned_iso: str,
    items: List[dict[str, Any]],
) -> None:
    """
    Mantém a tabela materializada cert_history atualizada.
    Para cada item do scan faz UPSERT usando file_name como chave,
    sobrescrevendo apenas se o scanned_at for mais recente que o registrado.
    Silenciosamente ignorado se o Supabase não estiver configurado.
    """
    client = _supabase()
    if not client or not items:
        return

    rows = []
    for it in items:
        file_name = str(it.get("file_name") or "").strip()
        if not file_name:
            continue

        # Tenta parsear o vencimento para um valor compatível com timestamptz
        not_after = it.get("not_after")
        vencimento: Optional[str] = None
        if not_after:
            try:
                s = str(not_after).strip()
                if s.endswith("Z"):
                    s = s[:-1] + "+00:00"
                datetime.fromisoformat(s)  # valida formato
                vencimento = s
            except ValueError:
                vencimento = None

        rows.append({
            "file_name":              file_name,
            "machine_id":             machine_id,
            "nome":                   it.get("nome") or it.get("display_name") or file_name,
            "documento":              it.get("documento_formatado") or it.get("documento_numero"),
            "documento_numero":       it.get("documento_numero"),
            "status_ultimo":          it.get("status"),
            "vencimento_certificado": vencimento,
            "ultima_data_registrada": scanned_iso,
            "updated_at":             datetime.now(timezone.utc).isoformat(),
        })

    if not rows:
        return

    # Envia em lotes de 200 para não ultrapassar limites do Supabase
    BATCH = 200
    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        try:
            client.table("cert_history").upsert(
                batch,
                on_conflict="file_name",
            ).execute()
        except Exception:  # noqa: BLE001
            logger.exception(
                "Falha ao fazer upsert em cert_history (lote %d/%d)",
                i // BATCH + 1,
                (len(rows) + BATCH - 1) // BATCH,
            )


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
