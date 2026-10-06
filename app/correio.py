"""Um ponto de saída para todo e-mail do portal (03/10/2026).

Até aqui seis lugares chamavam `smtp_service.send_smtp_email` direto, com os
campos SMTP da configuração; a Leva B acrescenta o Microsoft Graph como
segunda forma de envio. Este módulo escolhe a forma pela configuração e
mantém a ASSINATURA de `send_smtp_email` de propósito: os seis chamadores e
os testes que os dublam (`monkeypatch.setattr(modulo, "send_smtp_email", …)`)
continuam iguais. O nome é histórico; o que ele faz é "enviar e-mail".

`settings` é opcional só para compatibilidade com quem ainda não o passa: sem
ele a forma de envio é lida de `load_settings()`.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app import graph_mail, smtp_service

logger = logging.getLogger(__name__)

TRANSPORTE_SMTP = "smtp"
TRANSPORTE_GRAPH = "graph"
TRANSPORTES = (TRANSPORTE_SMTP, TRANSPORTE_GRAPH)

ROTULOS = {TRANSPORTE_SMTP: "SMTP", TRANSPORTE_GRAPH: "Microsoft 365 (Graph)"}


def transporte(settings: Any) -> str:
    t = str(getattr(settings, "email_transporte", "") or "").strip().lower()
    return t if t in TRANSPORTES else TRANSPORTE_SMTP


def configurado(settings: Any) -> bool:
    """Há como enviar? SMTP precisa de servidor; Graph, de tenant, app, segredo
    e caixa. É o que substitui os `if not settings.smtp_host` espalhados."""
    if transporte(settings) == TRANSPORTE_GRAPH:
        return bool(
            getattr(settings, "graph_tenant_id", "")
            and getattr(settings, "graph_client_id", "")
            and getattr(settings, "graph_client_secret_encrypted", "")
            and getattr(settings, "graph_remetente", "")
        )
    return bool(getattr(settings, "smtp_host", ""))


def remetente_efetivo(settings: Any) -> str:
    if transporte(settings) == TRANSPORTE_GRAPH:
        return str(getattr(settings, "graph_remetente", "") or "")
    return str(getattr(settings, "smtp_from_email", "") or getattr(settings, "smtp_user", "") or "")


def send_smtp_email(
    host: str,
    port: int,
    user: str,
    password_enc: str,
    use_tls: bool,
    use_ssl: bool,
    from_email: str,
    to_email: str,
    subject: str,
    html_content: str,
    settings: Optional[Any] = None,
) -> None:
    """Envia pela forma configurada. Assinatura do SMTP mantida (ver topo)."""
    if settings is None:
        from app.settings_state import load_settings

        settings = load_settings()
    if transporte(settings) == TRANSPORTE_GRAPH:
        graph_mail.enviar(
            tenant_id=str(getattr(settings, "graph_tenant_id", "") or ""),
            client_id=str(getattr(settings, "graph_client_id", "") or ""),
            segredo_enc=str(getattr(settings, "graph_client_secret_encrypted", "") or ""),
            remetente=str(getattr(settings, "graph_remetente", "") or ""),
            reply_to=str(getattr(settings, "graph_reply_to", "") or ""),
            to_email=to_email,
            subject=subject,
            html_content=html_content,
        )
        return
    # Procurado no módulo em tempo de chamada: os testes trocam
    # `smtp_service.send_smtp_email` e esperam ser alcançados.
    smtp_service.send_smtp_email(
        host=host,
        port=port,
        user=user,
        password_enc=password_enc,
        use_tls=use_tls,
        use_ssl=use_ssl,
        from_email=from_email,
        to_email=to_email,
        subject=subject,
        html_content=html_content,
    )
