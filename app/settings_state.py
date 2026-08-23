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
    install_token_ttl_min: int = 0
    trilha_retencao_dias: int = 0

    # ── Alertas por e-mail (20/08/2026) ────────────────────────────────────
    # Mesma convenção acima, e aqui ela é a diferença entre "ninguém recebe" e
    # "recebe quem sempre recebeu": vazio em `alertas_destinatarios` manda o
    # resumo a todo administrador ativo, como antes desta tela existir.
    # A leitura e a validação moram em `app/alertas_config.py`.
    alertas_destinatarios: str = ""
    alertas_marcos: str = ""
    alertas_intervalo_horas: int = 0

    # ── Texto do e-mail de alerta (22/08/2026) ─────────────────────────────
    # Mesma convenção: vazio é "usar o padrão". Os padrões e a validação moram
    # em `app/email_modelo.py`, que é o único lugar que sabe o que cada campo
    # significa — aqui eles são texto opaco, de propósito.
    alerta_email_assunto: str = ""
    alerta_email_titulo: str = ""
    alerta_email_abertura: str = ""
    alerta_email_recado: str = ""

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
        # `row.get` com default: se a migration ainda não rodou, a coluna não
        # vem no PostgREST e o padrão do código continua valendo. É o que torna
        # a migration ordem-independente.
        alertas_destinatarios=str(row.get("alertas_destinatarios", "") or ""),
        alertas_marcos=str(row.get("alertas_marcos", "") or ""),
        alertas_intervalo_horas=int(row.get("alertas_intervalo_horas") or 0),
        alerta_email_assunto=str(row.get("alerta_email_assunto", "") or ""),
        alerta_email_titulo=str(row.get("alerta_email_titulo", "") or ""),
        alerta_email_abertura=str(row.get("alerta_email_abertura", "") or ""),
        alerta_email_recado=str(row.get("alerta_email_recado", "") or ""),
        install_token_ttl_min=int(row.get("install_token_ttl_min") or 0),
        trilha_retencao_dias=int(row.get("trilha_retencao_dias") or 0),
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
            alertas_destinatarios=str(raw.get("alertas_destinatarios", "") or ""),
            alertas_marcos=str(raw.get("alertas_marcos", "") or ""),
            alertas_intervalo_horas=int(raw.get("alertas_intervalo_horas") or 0),
            alerta_email_assunto=str(raw.get("alerta_email_assunto", "") or ""),
            alerta_email_titulo=str(raw.get("alerta_email_titulo", "") or ""),
            alerta_email_abertura=str(raw.get("alerta_email_abertura", "") or ""),
            alerta_email_recado=str(raw.get("alerta_email_recado", "") or ""),
            install_token_ttl_min=int(raw.get("install_token_ttl_min", 0) or 0),
            trilha_retencao_dias=int(raw.get("trilha_retencao_dias", 0) or 0),
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
                # Se o Supabase tem pastas vazias, tenta complementar com o arquivo local
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
                            supa.alertas_destinatarios = local.alertas_destinatarios
                            supa.alertas_marcos = local.alertas_marcos
                            supa.alertas_intervalo_horas = local.alertas_intervalo_horas
                            supa.alerta_email_assunto = local.alerta_email_assunto
                            supa.alerta_email_titulo = local.alerta_email_titulo
                            supa.alerta_email_abertura = local.alerta_email_abertura
                            supa.alerta_email_recado = local.alerta_email_recado
                return supa
        except Exception:  # noqa: BLE001
            logger.exception("Falha ao ler portal_settings no Supabase; usando o arquivo local")
    s = _load_file()
    if s:
        return s
    return PortalSettings(
        source_folder="",
        expired_folder="",
        machine_id="default",
    )


class GravacaoNaoPersistida(RuntimeError):
    """O arquivo local recebeu, o Supabase não.

    Existe porque as duas coisas NÃO são equivalentes: `load_settings` prefere
    o Supabase quando ele está configurado, então uma gravação que só chegou ao
    arquivo é uma gravação que ninguém vai ler. Engolir isso fazia a tela
    responder "salvo com sucesso" sobre um valor que a próxima leitura
    descartaria — inclusive numa instalação a que faltasse uma migration.
    """


def save_settings(s: PortalSettings, *, exigir_supabase: bool = False) -> bool:
    """
    Grava em data/portal_settings.json sempre. Com Supabase, faz upsert (insert ou update)
    para a linha id=1, pois update em linha inexistente não grava nada.

    Devolve True quando a gravação chegou onde será lida. Com
    `exigir_supabase=True`, levanta `GravacaoNaoPersistida` em vez de devolver
    False — para quem responde a uma tela e precisa transformar isso em erro.

    O padrão continua sendo o antigo (registrar e seguir): o ingest do agente
    chama isto no meio de uma varredura, e derrubá-la por causa da configuração
    seria trocar um problema pequeno por um grande.
    """
    _save_file(s)
    client = _supabase()
    if not client:
        # Sem Supabase, o arquivo local É a fonte de verdade.
        return True
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
        "install_token_ttl_min": s.install_token_ttl_min,
        "trilha_retencao_dias": s.trilha_retencao_dias,
        "alertas_destinatarios": s.alertas_destinatarios,
        "alertas_marcos": s.alertas_marcos,
        "alertas_intervalo_horas": s.alertas_intervalo_horas,
        "alerta_email_assunto": s.alerta_email_assunto,
        "alerta_email_titulo": s.alerta_email_titulo,
        "alerta_email_abertura": s.alerta_email_abertura,
        "alerta_email_recado": s.alerta_email_recado,
        "updated_at": now,
    }
    try:
        client.table("portal_settings").upsert(row, on_conflict="id").execute()
    except Exception as e:  # noqa: BLE001
        logger.exception(
            "Falha ao gravar no Supabase; a configuração foi guardada em %s", DATA_FILE
        )
        if exigir_supabase:
            raise GravacaoNaoPersistida(str(e)) from e
        return False
    return True


INGEST_FILE = config.ROOT / "data" / "last_ingest.json"


def _save_snapshot_to_file(
    machine_id: str,
    source_folder: str,
    expired_folder: str,
    scanned_iso: str,
    items: List[dict[str, Any]],
) -> None:
    """Grava o snapshot em arquivo local (fallback ou modo sem Supabase)."""
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


def load_colaborador_selecao(email: str, user_id: Optional[str] = None) -> List[str]:
    """
    Documentos (CNPJ/CPF só dígitos) que o usuário escolheu para acompanhar.

    Com Supabase, a linha é procurada **só** por `user_id`. A queda para
    `user_email` existiu na fase 2 para curar linhas criadas antes dela; saiu
    na 3c depois de a produção confirmar 1 linha, 1 ligada, 0 órfãs, e porque
    a fase 3d remove a coluna — código que ainda a lesse quebraria ali.

    Sem Supabase é o arquivo local, que continua chaveado por e-mail: nesse
    modo não existe tabela `users`, então ali a identidade *é* o endereço. Os
    dois backends divergem de propósito.
    """
    key = (email or "").strip().lower()
    uid = (user_id or "").strip() or None
    client = _supabase()
    if client:
        if not uid:
            # Sem identidade não há o que procurar, e devolver [] calado faria
            # a pessoa ver a seleção vazia e concluir que perdeu o trabalho.
            logger.warning(
                "Seleção pedida sem user_id (email=%s); nenhum chamador deveria "
                "chegar aqui assim desde a fase 2 do rechaveamento.",
                key or "?",
            )
            return []
        try:
            r = (
                client.table("colaborador_cert_selecoes")
                .select("documentos")
                .eq("user_id", uid)
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
                "Falha ao ler colaborador_cert_selecoes no Supabase; usando o arquivo local"
            )
    return _load_colaborador_file_dict().get(key, [])


def save_colaborador_selecao(
    email: str, docs: List[str], user_id: Optional[str] = None
) -> None:
    """
    Grava sempre no arquivo local; com Supabase faz upsert por identidade.

    Desde a fase 3c a linha guarda **só** `user_id`. `user_email` deixou de ser
    escrita — ela virou coluna anulável na 3b-2 justamente para isto, e sai de
    vez na 3d.

    O `on_conflict` é `user_id`, o que só passou a ser possível na 3a: o índice
    da fase 1 era PARCIAL (`WHERE user_id IS NOT NULL`), e índice parcial não
    serve para o `ON CONFLICT` inferir alvo. A 3a trocou-o por uma constraint
    `UNIQUE` de verdade.
    """
    key = (email or "").strip().lower()
    uid = (user_id or "").strip() or None
    if not key:
        return
    clean = [str(x).strip() for x in docs if str(x).strip()]
    merged = _load_colaborador_file_dict()
    merged[key] = clean
    _save_colaborador_file_dict(merged)
    client = _supabase()
    if not client:
        return
    if not uid:
        # A seleção ficou no arquivo local, mas em produção esse arquivo é
        # efêmero. Gravar sem identidade não é opção: `user_id` é o alvo do
        # `on_conflict`, e uma linha sem ele seria órfã de nascença.
        logger.error(
            "Seleção de %s não foi gravada: chamada sem user_id. A escolha "
            "dela se perde no próximo reinício.",
            key,
        )
        return
    now = datetime.now(timezone.utc).isoformat()
    row: Dict[str, Any] = {
        "user_id": uid,
        "documentos": clean,
        "updated_at": now,
    }
    try:
        client.table("colaborador_cert_selecoes").upsert(row, on_conflict="user_id").execute()
    except Exception:  # noqa: BLE001
        logger.exception(
            "Falha ao gravar colaborador_cert_selecoes no Supabase; seleção ficou em %s",
            COLAB_SELECAO_FILE,
        )


# ── Preferência de alerta do colaborador (20/08/2026) ──────────────────────

def load_preferencia_alerta(user_id: Optional[str]) -> Dict[str, Any]:
    """Como a pessoa quer ser avisada. Ausência = o padrão de sempre.

    Devolve sempre um dicionário utilizável: sem Supabase, sem linha ou sem as
    colunas (migration pendente), o resultado é "recebe tudo" — que é o que
    acontecia antes desta preferência existir.
    """
    padrao = {"notificar_email": True, "alerta_marcos_ignorados": ""}
    uid = (user_id or "").strip()
    client = _supabase()
    if not client or not uid:
        return padrao
    try:
        r = (
            client.table("colaborador_cert_selecoes")
            .select("notificar_email, alerta_marcos_ignorados")
            .eq("user_id", uid)
            .limit(1)
            .execute()
        )
        linhas = r.data or []
        if not linhas:
            return padrao
        row = linhas[0]
        return {
            "notificar_email": bool(row.get("notificar_email", True)),
            "alerta_marcos_ignorados": str(row.get("alerta_marcos_ignorados") or ""),
        }
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao ler preferência de alerta; usando o padrão")
        return padrao


def save_preferencia_alerta(
    user_id: Optional[str], notificar: bool, ignorados: str
) -> None:
    """Grava só as duas colunas da preferência.

    UPDATE e não upsert, de propósito: a linha pertence à SELEÇÃO, e criá-la
    aqui produziria uma linha com `documentos` vazio que a tela de seleção
    depois sobrescreveria. Quem ainda não selecionou nada também não tem o que
    ser avisado — a preferência dele é gravada quando ele selecionar.

    Levanta `GravacaoNaoPersistida` se o banco recusar: esta função só é
    chamada por uma tela, e tela que diz "salvo" sobre gravação que falhou é o
    defeito que 20/08 passou o dia corrigindo.
    """
    uid = (user_id or "").strip()
    client = _supabase()
    if not client or not uid:
        return
    try:
        (
            client.table("colaborador_cert_selecoes")
            .update(
                {
                    "notificar_email": bool(notificar),
                    "alerta_marcos_ignorados": ignorados,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("user_id", uid)
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("Falha ao gravar preferência de alerta de %s", uid)
        raise GravacaoNaoPersistida(str(e)) from e


# ── Notificações lidas no sino (20/08/2026) ────────────────────────────────
#
# Sem fallback em arquivo, ao contrário das seleções. É deliberado: em produção
# o disco é efêmero, e um "li todos" que volta atrás no próximo reinício seria
# pior do que um botão que assumidamente não funciona sem banco. Sem Supabase,
# ler devolve conjunto vazio e marcar não faz nada — o sino se comporta como
# antes de o botão existir.

def carregar_notificacoes_lidas(user_id: Optional[str]) -> set:
    """Chaves que esta pessoa já marcou como lidas."""
    uid = (user_id or "").strip()
    client = _supabase()
    if not client or not uid:
        return set()
    try:
        r = (
            client.table("notificacao_lida")
            .select("chave")
            .eq("user_id", uid)
            .execute()
        )
        return {str(row.get("chave") or "") for row in (r.data or []) if row.get("chave")}
    except Exception:  # noqa: BLE001
        # Silencioso a ponto de não sumir com alerta: falhar aqui devolve
        # "nada lido", e o pior que acontece é o sino mostrar de novo algo que
        # a pessoa já viu. O inverso — esconder um vencimento por erro de
        # leitura — é que não pode acontecer.
        logger.warning("Falha ao ler notificacao_lida; tratando como nada lido")
        return set()


def marcar_notificacoes_lidas(user_id: Optional[str], chaves: List[str]) -> int:
    """Marca as chaves como lidas. Devolve quantas foram gravadas."""
    uid = (user_id or "").strip()
    limpas = sorted({str(c).strip() for c in chaves if str(c).strip()})
    client = _supabase()
    if not client or not uid or not limpas:
        return 0
    agora = datetime.now(timezone.utc).isoformat()
    linhas = [{"user_id": uid, "chave": c, "lida_em": agora} for c in limpas]
    try:
        # `on_conflict` na PK composta: marcar de novo o que já estava marcado
        # é o caso NORMAL (a pessoa clica "li todos" duas vezes), e não um erro.
        (
            client.table("notificacao_lida")
            .upsert(linhas, on_conflict="user_id,chave")
            .execute()
        )
        return len(limpas)
    except Exception as e:  # noqa: BLE001
        logger.exception("Falha ao marcar notificações como lidas para %s", uid)
        raise GravacaoNaoPersistida(str(e)) from e


def supabase_configured() -> bool:
    return bool(config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY)
