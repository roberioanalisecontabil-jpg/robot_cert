import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

from app import config
from app.settings_state import load_settings, _supabase, _load_colaborador_file_dict
from app.cert_scanner import scan_folder, cert_to_public_dict
from app.smtp_service import send_smtp_email

logger = logging.getLogger(__name__)

SENT_ALERTS_FILE = config.ROOT / "data" / "sent_alerts.json"

def _load_local_sent_alerts() -> List[Dict[str, Any]]:
    if not SENT_ALERTS_FILE.is_file():
        return []
    try:
        return json.loads(SENT_ALERTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

def _save_local_sent_alerts(alerts: List[Dict[str, Any]]) -> None:
    SENT_ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Rotação de fallback local: mantém apenas os últimos 1000 registros
    if len(alerts) > 1000:
        alerts = alerts[-1000:]
    try:
        SENT_ALERTS_FILE.write_text(
            json.dumps(alerts, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        logger.error(f"Erro ao salvar localmente sent_alerts: {e}")

def _is_alert_already_sent(
    fingerprint: str,
    tipo_alerta: str,
    destinatario: str,
    validade_iso: str
) -> bool:
    """Verifica antispam composto: certificado + tipo + validade + destinatário."""
    client = _supabase()
    if client:
        try:
            r = (
                client.table("sent_alerts")
                .select("id")
                .eq("fingerprint_sha256", fingerprint)
                .eq("tipo_alerta", tipo_alerta)
                .eq("destinatario", destinatario.lower().strip())
                .eq("data_validade", validade_iso)
                .limit(1)
                .execute()
            )
            return len(r.data or []) > 0
        except Exception as e:
            logger.warning(f"Falha ao ler sent_alerts no Supabase, usando local: {e}")
            
    # Fallback local
    local_alerts = _load_local_sent_alerts()
    dest_norm = destinatario.lower().strip()
    for al in local_alerts:
        if (
            al.get("fingerprint_sha256") == fingerprint
            and al.get("tipo_alerta") == tipo_alerta
            and str(al.get("destinatario") or "").lower().strip() == dest_norm
            and al.get("data_validade") == validade_iso
        ):
            return True
    return False

def _record_sent_alert(
    fingerprint: str,
    tipo_alerta: str,
    destinatario: str,
    validade_iso: str
) -> None:
    """Registra o envio para fins de antispam."""
    now_iso = datetime.now(timezone.utc).isoformat()
    client = _supabase()
    if client:
        try:
            row = {
                "fingerprint_sha256": fingerprint,
                "tipo_alerta": tipo_alerta,
                "destinatario": destinatario.lower().strip(),
                "data_validade": validade_iso,
                "sent_at": now_iso
            }
            client.table("sent_alerts").insert(row).execute()
            return
        except Exception as e:
            logger.warning(f"Falha ao salvar sent_alert no Supabase, salvando local: {e}")
            
    # Gravação local com rotação
    local_alerts = _load_local_sent_alerts()
    local_alerts.append({
        "fingerprint_sha256": fingerprint,
        "tipo_alerta": tipo_alerta,
        "destinatario": destinatario.lower().strip(),
        "data_validade": validade_iso,
        "sent_at": now_iso
    })
    _save_local_sent_alerts(local_alerts)

def _get_todos_colaboradores_selecoes() -> Dict[str, List[str]]:
    """Mapeia user_email -> lista de documentos digitos."""
    client = _supabase()
    if client:
        try:
            r = client.table("colaborador_cert_selecoes").select("user_email, documentos").execute()
            out = {}
            for row in (r.data or []):
                email = str(row.get("user_email") or "").lower().strip()
                docs = row.get("documentos")
                if email and isinstance(docs, list):
                    out[email] = [str(x).strip() for x in docs if str(x).strip()]
            return out
        except Exception as e:
            logger.warning(f"Falha ao ler seleções de colaboradores no Supabase, usando local: {e}")
            
    return _load_colaborador_file_dict()

def trigger_all_alerts() -> Dict[str, Any]:
    """
    Executa a varredura completa dos certificados e envia alertas aos colaboradores.
    Retorna estatísticas do processamento.
    """
    settings = load_settings()
    stats = {
        "processed_certs": 0,
        "alerts_sent": 0,
        "skipped_already_sent": 0,
        "skipped_no_recipient_email": 0,
        "errors": 0,
        "alerts_disabled": not settings.smtp_alerts_enabled,
        "smtp_configured": bool(settings.smtp_host and settings.smtp_user)
    }
    
    # 1. Se alertas estão desligados ou SMTP não está configurado, interrompe
    if not settings.smtp_alerts_enabled or not settings.smtp_host:
        logger.info("Envio de alertas ignorado (alertas desligados ou SMTP não configurado).")
        return stats

    # 2. Carrega todos os certificados do sistema
    # Tenta usar o último snapshot ou faz scan local
    from app.settings_state import get_latest_snapshot
    from app.main import _list_certificados_payload
    snap = get_latest_snapshot()
    payload = _list_certificados_payload(settings, snap, "auto")
    itens = payload.get("itens") or []
    
    # 3. Carrega seleções de colaboradores
    selecoes = _get_todos_colaboradores_selecoes()
    
    # 4. Inicia processamento
    now = datetime.now(timezone.utc)
    for it in itens:
        stats["processed_certs"] += 1
        fingerprint = it.get("fingerprint_sha256")
        if not fingerprint:
            continue
            
        venc_iso = it.get("not_after")
        if not venc_iso:
            continue
            
        try:
            # Parsing data de validade
            v_dt = datetime.fromisoformat(venc_iso.replace("Z", "+00:00"))
        except Exception:
            continue
            
        # Determina tipo de alerta
        dias = (v_dt.date() - now.date()).days
        tipo_alerta = None
        if v_dt < now:
            tipo_alerta = "expired"
        elif 0 <= dias <= 30:
            tipo_alerta = "expiring"
            
        if not tipo_alerta:
            continue
            
        # Acha todos os destinatários monitorando este documento
        doc_digitos = "".join(c for c in (it.get("documento_numero") or "") if c.isdigit())
        if not doc_digitos:
            # Caso o CNPJ/CPF não esteja em formato puro
            doc_digitos = "".join(c for c in (it.get("documento_formatado") or "") if c.isdigit())
            
        destinatarios = []
        for email, docs in selecoes.items():
            # Limpa cada documento para comparar apenas os dígitos
            docs_clean = ["".join(c for c in d if c.isdigit()) for d in docs]
            if doc_digitos in docs_clean:
                destinatarios.append(email)
                
        # Se não há destinatários
        if not destinatarios:
            continue
            
        for dest in destinatarios:
            email_dest = dest.strip()
            if not email_dest:
                stats["skipped_no_recipient_email"] += 1
                logger.warning(f"Certificado {it.get('nome')} exige alerta mas o destinatário está sem e-mail.")
                continue
                
            # Verifica antispam
            if _is_alert_already_sent(fingerprint, tipo_alerta, email_dest, venc_iso):
                stats["skipped_already_sent"] += 1
                continue
                
            # Prepara e-mail
            subject = ""
            html_content = ""
            nome_cert = it.get("nome") or it.get("display_name") or "Certificado Digital"
            doc_fmt = it.get("documento_formatado") or it.get("documento_numero") or "Sem documento"
            
            if tipo_alerta == "expired":
                subject = f"⚠️ ALERTA: Certificado Vencido - {nome_cert}"
                html_content = f"""
                <html>
                  <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f5f5f7; padding: 20px; color: #1d1d1f;">
                    <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 12px; padding: 24px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); border: 1px solid #e5e5ea;">
                      <h2 style="color: #ff3b30; margin-top: 0;">⚠️ Certificado Vencido</h2>
                      <p>Olá,</p>
                      <p>Identificamos que o certificado digital que você está acompanhando venceu.</p>
                      <hr style="border: 0; border-top: 1px solid #e5e5ea; margin: 20px 0;" />
                      <table style="width: 100%; border-collapse: collapse;">
                        <tr><td style="padding: 6px 0; font-weight: 600;">Nome:</td><td>{nome_cert}</td></tr>
                        <tr><td style="padding: 6px 0; font-weight: 600;">CNPJ/CPF:</td><td>{doc_fmt}</td></tr>
                        <tr><td style="padding: 6px 0; font-weight: 600; color: #ff3b30;">Vencimento:</td><td style="color: #ff3b30;">{v_dt.strftime('%d/%m/%Y')}</td></tr>
                      </table>
                      <hr style="border: 0; border-top: 1px solid #e5e5ea; margin: 20px 0;" />
                      <p style="font-size: 13px; color: #86868b; margin-bottom: 0;">Por favor, providencie a renovação do certificado o quanto antes para evitar interrupção nos serviços.</p>
                    </div>
                  </body>
                </html>
                """
            else:
                subject = f"⏳ ALERTA: Certificado Expirando em {dias} dias - {nome_cert}"
                html_content = f"""
                <html>
                  <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f5f5f7; padding: 20px; color: #1d1d1f;">
                    <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 12px; padding: 24px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); border: 1px solid #e5e5ea;">
                      <h2 style="color: #ff9500; margin-top: 0;">⏳ Certificado Próximo ao Vencimento</h2>
                      <p>Olá,</p>
                      <p>O certificado digital que você acompanha está prestes a expirar.</p>
                      <hr style="border: 0; border-top: 1px solid #e5e5ea; margin: 20px 0;" />
                      <table style="width: 100%; border-collapse: collapse;">
                        <tr><td style="padding: 6px 0; font-weight: 600;">Nome:</td><td>{nome_cert}</td></tr>
                        <tr><td style="padding: 6px 0; font-weight: 600;">CNPJ/CPF:</td><td>{doc_fmt}</td></tr>
                        <tr><td style="padding: 6px 0; font-weight: 600; color: #ff9500;">Vencimento:</td><td style="color: #ff9500;">{v_dt.strftime('%d/%m/%Y')} ({dias} dias restantes)</td></tr>
                      </table>
                      <hr style="border: 0; border-top: 1px solid #e5e5ea; margin: 20px 0;" />
                      <p style="font-size: 13px; color: #86868b; margin-bottom: 0;">Recomendamos iniciar o processo de renovação em breve.</p>
                    </div>
                  </body>
                </html>
                """
                
            try:
                send_smtp_email(
                    host=settings.smtp_host,
                    port=settings.smtp_port,
                    user=settings.smtp_user,
                    password_enc=settings.smtp_password_encrypted,
                    use_tls=settings.smtp_use_tls,
                    use_ssl=settings.smtp_use_ssl,
                    from_email=settings.smtp_from_email,
                    to_email=email_dest,
                    subject=subject,
                    html_content=html_content
                )
                stats["alerts_sent"] += 1
                _record_sent_alert(fingerprint, tipo_alerta, email_dest, venc_iso)
            except Exception as e:
                stats["errors"] += 1
                logger.error(f"Falha ao enviar e-mail de alerta para {email_dest}: {e}")
                
    return stats
