"""E-mail de certificado novo na pasta (pedido de 30/09/2026).

Quando o agente ingere um arquivo que nunca esteve em `cert_history`, o
portal avisa por e-mail quem tem aquele cliente na carteira — e os
administradores (ou a lista fixa de Configuração › Alertas), que recebem
tudo. Um e-mail por pessoa por ingestão, listando só os certificados que
lhe dizem respeito.

Quem recebe o quê:
- administradores / lista fixa: todos os novos da ingestão;
- gestor: os novos, menos as Exceções (todo o inventário é o alcance dele);
- operador: os novos cujo documento está atribuído à sua carteira.
Conta desativada não recebe. É o mesmo recorte do sino (`documentos_ao_alcance`),
de propósito: o e-mail e o sino falam da mesma lista.

Antispam: o mesmo par (certificado, destinatário) não recebe "novo" duas
vezes — reusa `sent_alerts` com `tipo_alerta = "novo"`. A data de validade da
chave é o vencimento do certificado (ou o dia do envio, se ilegível).

O nome do ARQUIVO nunca entra no e-mail: carrega a senha do PFX
(SECURITY_AUDIT #2). O item já chega sanitizado, e aqui só nome do titular,
documento e vencimento são usados.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from app import alertas_config
from app.alert_state import _is_alert_already_sent, _record_sent_alert
from app.auth import conta_ativa
from app.cert_installer import documentos_ao_alcance
from app.settings_state import _banco, load_preferencia_alerta, load_settings
from app.correio import send_smtp_email
from app import correio

logger = logging.getLogger(__name__)

TIPO_ALERTA = "novo"


def _so_digitos(valor: Any) -> str:
    return "".join(c for c in str(valor or "") if c.isdigit())


def _documento(it: Dict[str, Any]) -> str:
    return _so_digitos(it.get("documento_numero")) or _so_digitos(it.get("documento_formatado"))


def _identidade(it: Dict[str, Any]) -> str:
    """Chave antispam do certificado: fingerprint, senão a chave do arquivo."""
    return str(it.get("fingerprint_sha256") or it.get("arquivo_chave") or it.get("nome") or "?")


def _validade_iso(it: Dict[str, Any], now: datetime) -> str:
    s = str(it.get("not_after") or "").strip()
    if s:
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            return datetime.fromisoformat(s).isoformat()
        except ValueError:
            pass
    return now.isoformat()


def _vencimento_legivel(it: Dict[str, Any]) -> str:
    s = str(it.get("not_after") or "").strip()
    if not s:
        return "—"
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).strftime("%d/%m/%Y")
    except ValueError:
        return "—"


def fingerprints_do_snapshot(snapshot: Optional[Dict[str, Any]]) -> Set[str]:
    """Fingerprints do inventário anterior: o que o portal já conhecia."""
    out: Set[str] = set()
    for it in ((snapshot or {}).get("items") or []):
        fp = str(it.get("fingerprint_sha256") or it.get("cert_sha256") or "").strip().lower()
        if fp:
            out.add(fp)
    return out


def filtrar_ineditos(novos: List[Dict[str, Any]], conhecidos: Set[str]) -> List[Dict[str, Any]]:
    """Só o que é certificado NOVO, e não arquivo novo de certificado velho.

    A chave do histórico é nome do arquivo + fingerprint; copiar um PFX para
    a pasta Copias, ou renomeá-lo, cria uma chave nova para o mesmo
    certificado. Sem este filtro cada cópia mandava "certificado novo" para
    todo mundo. Sem fingerprint (arquivo ilegível) não há como saber: passa.
    """
    out: List[Dict[str, Any]] = []
    for it in novos:
        fp = str(it.get("fingerprint_sha256") or "").strip().lower()
        if fp and fp in conhecidos:
            continue
        out.append(it)
    return out


def _contas_ativas() -> List[Dict[str, Any]]:
    client = _banco()
    if not client:
        return []
    try:
        r = client.table("users").select("id, email, role, ativo").execute()
    except Exception as e:  # noqa: BLE001
        logger.warning("Não foi possível listar as contas para avisar de certificados novos: %s", e)
        return []
    return [
        row for row in (r.data or [])
        if str(row.get("email") or "").strip() and conta_ativa(row)
    ]


def _destinatarios(settings, novos: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """e-mail → certificados novos que essa pessoa deve ver."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    contas = _contas_ativas()

    # Lista fixa da tela quando houver; senão, todo administrador ativo — a
    # mesma regra do resumo de vencimentos (`alert_state._enviar_resumo_admins`).
    fixos = alertas_config.destinatarios_configurados(getattr(settings, "alertas_destinatarios", "")) or ()
    geral = list(fixos) if fixos else sorted({
        str(c.get("email") or "").strip().lower()
        for c in contas if str(c.get("role") or "").strip().lower() == "admin"
    })
    for email in geral:
        out.setdefault(email.strip().lower(), list(novos))

    for conta in contas:
        email = str(conta.get("email") or "").strip().lower()
        papel = str(conta.get("role") or "").strip().lower()
        if not email or email in out or papel == "admin":
            continue
        # "Quero receber aviso" desligado vale para TODO e-mail pessoal (A2,
        # 01/10/2026), inclusive este. Administradores e a lista fixa não
        # passam por aqui.
        if not load_preferencia_alerta(str(conta.get("id") or "")).get("notificar_email", True):
            continue
        try:
            alcance: Optional[Set[str]] = documentos_ao_alcance(str(conta.get("id") or ""), papel)
        except Exception as e:  # noqa: BLE001
            logger.warning("Carteira de %s ilegível; sem aviso de certificado novo: %s", email, e)
            continue
        if alcance is None:
            meus = list(novos)
        else:
            meus = [it for it in novos if _documento(it) and _documento(it) in alcance]
        if meus:
            out[email] = meus
    return out


def _montar_email(itens: List[Dict[str, Any]], now: datetime, motivo: str):
    n = len(itens)
    assunto = f"[Certificados] {n} certificado{'s' if n != 1 else ''} novo{'s' if n != 1 else ''} na pasta"
    linhas = "".join(
        f'<tr><td style="padding:6px 8px;border-bottom:1px solid #e5e5ea;">'
        f'{html.escape(str(it.get("nome") or it.get("display_name") or "Sem nome").upper())}</td>'
        f'<td style="padding:6px 8px;border-bottom:1px solid #e5e5ea;">'
        f'{html.escape(str(it.get("documento_formatado") or it.get("documento_numero") or "—"))}</td>'
        f'<td style="padding:6px 8px;border-bottom:1px solid #e5e5ea;white-space:nowrap;">'
        f'{_vencimento_legivel(it)}</td></tr>'
        for it in itens
    )
    corpo = f"""
    <html>
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color:#f5f5f7; padding:20px; color:#1d1d1f;">
        <div style="max-width:680px;margin:0 auto;background:#ffffff;border-radius:12px;padding:24px;box-shadow:0 4px 12px rgba(0,0,0,0.05);border:1px solid #e5e5ea;">
          <h2 style="margin-top:0;">Certificado{'s' if n != 1 else ''} novo{'s' if n != 1 else ''} na pasta</h2>
          <p style="color:#6e6e73;margin-top:0;">
            Em {now.strftime("%d/%m/%Y")} o agente encontrou {n} certificado{'s' if n != 1 else ''}
            que ainda não estava{'m' if n != 1 else ''} no portal. Já pode{'m' if n != 1 else ''} ser instalado{'s' if n != 1 else ''} pelo Início.
          </p>
          <table style="width:100%;border-collapse:collapse;font-size:13px;">
            <tr>
              <th style="text-align:left;padding:6px 8px;border-bottom:2px solid #e5e5ea;">Nome</th>
              <th style="text-align:left;padding:6px 8px;border-bottom:2px solid #e5e5ea;">CNPJ/CPF</th>
              <th style="text-align:left;padding:6px 8px;border-bottom:2px solid #e5e5ea;">Vencimento</th>
            </tr>
            {linhas}
          </table>
          <p style="font-size:12px;color:#86868b;margin-top:24px;margin-bottom:0;">{motivo}</p>
        </div>
      </body>
    </html>
    """
    return assunto, corpo


def notificar_novos(novos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Envia o aviso de certificados novos. Devolve estatísticas; nunca levanta.

    Roda em segundo plano depois do `/api/ingest`. Nada sai se os alertas
    estiverem desligados ou o SMTP não estiver configurado — o sino continua
    mostrando os novos de qualquer forma.
    """
    out = {
        "certificados": len(novos or []),
        "destinatarios": 0,
        "enviados": 0,
        "ignorados_ja_enviados": 0,
        "erros": 0,
        "alerts_disabled": False,
    }
    if not novos:
        return out
    try:
        settings = load_settings()
    except Exception as e:  # noqa: BLE001
        logger.error("Sem configuração para avisar de certificados novos: %s", e)
        out["erros"] = 1
        return out
    if not getattr(settings, "smtp_alerts_enabled", False) or not correio.configurado(settings):
        out["alerts_disabled"] = True
        logger.info("Aviso de certificado novo não enviado (alertas desligados ou SMTP não configurado).")
        return out

    now = datetime.now(timezone.utc)
    fixos = {
        e.strip().lower()
        for e in (alertas_config.destinatarios_configurados(getattr(settings, "alertas_destinatarios", "")) or ())
    }
    por_email = _destinatarios(settings, novos)
    out["destinatarios"] = len(por_email)

    for email, itens in por_email.items():
        pendentes = []
        for it in itens:
            if _is_alert_already_sent(_identidade(it), TIPO_ALERTA, email, _validade_iso(it, now)):
                out["ignorados_ja_enviados"] += 1
                continue
            pendentes.append(it)
        if not pendentes:
            continue
        motivo = (
            "Você recebe este aviso porque seu endereço está na lista de destinatários "
            "configurada em Configuração &rsaquo; Alertas."
            if email in fixos
            else "Você recebe este aviso porque é administrador do portal ou tem estes clientes na sua carteira."
        )
        assunto, corpo = _montar_email(pendentes, now, motivo)
        try:
            send_smtp_email(
                host=settings.smtp_host,
                port=settings.smtp_port,
                user=settings.smtp_user,
                password_enc=settings.smtp_password_encrypted,
                use_tls=settings.smtp_use_tls,
                use_ssl=settings.smtp_use_ssl,
                from_email=settings.smtp_from_email,
                to_email=email,
                subject=assunto,
                html_content=corpo,
                settings=settings,
            )
        except Exception as e:  # noqa: BLE001
            out["erros"] += 1
            logger.error("Falha ao avisar %s de certificado novo: %s", email, e)
            continue
        out["enviados"] += 1
        for it in pendentes:
            _record_sent_alert(_identidade(it), TIPO_ALERTA, email, _validade_iso(it, now))

    logger.info(
        "Certificados novos: %d certificado(s), %d destinatário(s), %d e-mail(s) enviado(s), %d já avisado(s), %d erro(s).",
        out["certificados"], out["destinatarios"], out["enviados"], out["ignorados_ja_enviados"], out["erros"],
    )
    return out



# ══════════════════════════════════════════════════════════════════════════
# Por hora cheia (02/10/2026)
# ══════════════════════════════════════════════════════════════════════════
#
# Em vez de um e-mail por ingestão, os novos de cada hora saem juntos na
# virada da hora: o que entrou das 09:01 às 09:59 vai às 10:00. A fila mora na
# tabela `novos_pendentes` (uma linha por certificado, com o item inteiro);
# sem banco, numa lista em memória — o processo é um só no ANALISESRV.
#
# "Imediato" continua existindo como modo, e a chave geral
# `alertas_novos_enabled` desliga os dois. O antispam por (certificado,
# destinatário) em `sent_alerts` segue valendo no envio, então um reinício
# entre a gravação e o envio no máximo atrasa, nunca duplica.

TABELA_PENDENTES = "novos_pendentes"
_pendentes_memoria: List[Dict[str, Any]] = []


def segundos_ate_a_proxima_hora_cheia(agora: Optional[datetime] = None) -> float:
    """Quanto dormir até a próxima hora cheia (mínimo 1 s, para não girar)."""
    agora = agora or datetime.now(timezone.utc)
    proxima = agora.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return max(1.0, (proxima - agora).total_seconds())


def guardar_pendentes(novos: List[Dict[str, Any]]) -> int:
    """Põe os novos na fila da hora. Devolve quantos ficaram guardados."""
    if not novos:
        return 0
    client = _banco()
    if not client:
        _pendentes_memoria.extend(dict(it) for it in novos)
        return len(novos)
    agora = datetime.now(timezone.utc).isoformat()
    linhas = [
        {"fingerprint_sha256": _identidade(it), "item": dict(it), "registrado_em": agora}
        for it in novos
    ]
    try:
        client.table(TABELA_PENDENTES).upsert(linhas, on_conflict="fingerprint_sha256").execute()
    except Exception as e:  # noqa: BLE001
        # Não perder o aviso: sem a tabela (migration por rodar), sai agora.
        logger.error("Fila de certificados novos indisponível (%s); avisando de imediato.", e)
        notificar_novos(novos)
        return 0
    return len(linhas)


def enviar_novos_pendentes() -> Dict[str, Any]:
    """Esvazia a fila e manda UM e-mail por destinatário. Para o laço da hora."""
    client = _banco()
    if not client:
        itens = list(_pendentes_memoria)
        _pendentes_memoria.clear()
        return notificar_novos(itens) if itens else {"certificados": 0}
    try:
        r = client.table(TABELA_PENDENTES).select("fingerprint_sha256, item").execute()
    except Exception as e:  # noqa: BLE001
        logger.error("Fila de certificados novos ilegível: %s", e)
        return {"certificados": 0, "erros": 1}
    linhas = r.data or []
    if not linhas:
        return {"certificados": 0}
    itens = [dict(x.get("item") or {}) for x in linhas if x.get("item")]
    out = notificar_novos(itens)
    try:
        client.table(TABELA_PENDENTES).delete().in_(
            "fingerprint_sha256", [str(x.get("fingerprint_sha256") or "") for x in linhas]
        ).execute()
    except Exception as e:  # noqa: BLE001
        logger.error("Fila de certificados novos não esvaziou (%s); o antispam evita repetição.", e)
    return out


def agendar_ou_notificar(novos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """O que o `/api/ingest` chama: desligado → nada; imediato → envia; hora → guarda."""
    if not novos:
        return {"certificados": 0}
    try:
        settings = load_settings()
    except Exception as e:  # noqa: BLE001
        logger.error("Sem configuração para o aviso de certificados novos: %s", e)
        return {"certificados": len(novos), "erros": 1}
    if not getattr(settings, "alertas_novos_enabled", True):
        logger.info("Aviso de certificado novo desligado na Configuração; %d novo(s) sem e-mail.", len(novos))
        return {"certificados": len(novos), "alerts_disabled": True}
    if alertas_config.modo_novos_efetivo(getattr(settings, "alertas_novos_modo", "")) == alertas_config.MODO_NOVOS_IMEDIATO:
        return notificar_novos(novos)
    return {"certificados": len(novos), "guardados": guardar_pendentes(novos)}
