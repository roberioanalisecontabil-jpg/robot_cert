"""
Entrada de certificados, do lado do portal (02/10/2026).

O agente do servidor processa a pasta de entrada (`agent/entrada.py`) e conta
ao portal o que fez: cada arquivo renomeado e movido vira um EVENTO; cada
arquivo que não abriu e ficou na pasta é um PENDENTE. Este módulo guarda os
dois na tabela `entrada_eventos` e avisa os administradores por e-mail quando
um pendente NOVO aparece — uma vez por arquivo, e não a cada ciclo.

Pendente é estado, não histórico: a cada relatório do agente a lista que ele
manda é o estado atual da pasta de entrada daquela máquina. O que estava
pendente e não veio mais foi resolvido (alguém renomeou, apagou ou o arquivo
passou a abrir), e a linha ganha `resolvido_em`. O que veio e não estava vira
linha nova — e é só para essas que sai e-mail.

Sem banco configurado nada é guardado: a entrada aparece vazia no Instalador
e o log do agente continua sendo a trilha.
"""

from __future__ import annotations

import html
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app import alertas_config
from app.auth import conta_ativa
from app.settings_state import _banco, load_settings
from app.correio import send_smtp_email
from app import correio

logger = logging.getLogger(__name__)

TABELA = "entrada_eventos"
RESULTADO_PENDENTE = "pendente"
RESULTADO_VENCIDO_PRESO = "vencido_preso"
# As duas pendências: arquivo que ficou na entrada por não abrir, e vencido que
# a varredura não conseguiu tirar da pasta da letra (02/10/2026). Ambas têm
# `resolvido_em` nulo enquanto o arquivo estiver onde está.
PENDENCIAS = (RESULTADO_PENDENTE, RESULTADO_VENCIDO_PRESO)
RESULTADOS_VALIDOS = frozenset({
    "movido", "vencido", "substituiu", "copia_descartada", "duplicidade", *PENDENCIAS,
})
ROTULO_RESULTADO = {
    "movido": "Renomeado e movido",
    "vencido": "Para vencidos",
    "substituiu": "Substituiu o vencido",
    "copia_descartada": "Cópia descartada",
    "duplicidade": "Duplicidade",
    RESULTADO_PENDENTE: "Pendente na entrada",
    RESULTADO_VENCIDO_PRESO: "Vencido não movido",
}

_CAMPOS_TEXTO = (
    "arquivo_original", "arquivo_novo", "pasta_origem", "pasta_destino", "motivo", "nome",
    "documento_numero", "documento_tipo", "fingerprint_sha256",
)


def _chave_pendencia(ev: Dict[str, Any]) -> str:
    """Um arquivo numa pasta. O nome sozinho não basta: o mesmo nome pode estar
    preso na pasta `B` e pendente na entrada ao mesmo tempo."""
    nome = str(ev.get("arquivo_original") or "")
    return f"{str(ev.get('pasta_origem') or '')}|{nome}" if nome else ""


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _linha(machine_id: str, ev: Dict[str, Any], *, pendente: bool) -> Dict[str, Any]:
    resultado = str(ev.get("resultado") or "")
    if pendente and resultado not in PENDENCIAS:
        resultado = RESULTADO_PENDENTE
    row: Dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "machine_id": machine_id,
        "resultado": resultado,
        "quando": str(ev.get("quando") or "").strip() or _agora(),
        "not_after": (str(ev.get("not_after") or "").strip() or None),
        "resolvido_em": None,
    }
    for campo in _CAMPOS_TEXTO:
        row[campo] = str(ev.get(campo) or "")[:1024]
    return row


def registrar_relatorio(machine_id: str, eventos: List[Dict[str, Any]], pendentes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Guarda os eventos e reconcilia os pendentes. Devolve o que mudou.

    `novos_pendentes` são os que NÃO estavam na lista anterior desta máquina:
    é para esses que o chamador manda o e-mail.
    """
    out = {"eventos": 0, "pendentes": len(pendentes), "novos_pendentes": [], "resolvidos": 0, "gravado": False}
    client = _banco()
    if not client:
        return out

    eventos_ok = [ev for ev in eventos if str(ev.get("resultado") or "") in RESULTADOS_VALIDOS and str(ev.get("resultado")) not in PENDENCIAS]
    linhas = [_linha(machine_id, ev, pendente=False) for ev in eventos_ok]

    try:
        r = (
            client.table(TABELA).select("id, arquivo_original, pasta_origem")
            .eq("machine_id", machine_id).in_("resultado", list(PENDENCIAS)).is_("resolvido_em", "null")
            .execute()
        )
        abertos = {_chave_pendencia(x): str(x.get("id")) for x in (r.data or []) if _chave_pendencia(x)}
    except Exception as e:  # noqa: BLE001
        logger.warning("Entrada: pendentes anteriores ilegíveis (%s); todos os atuais contam como novos.", e)
        abertos = {}

    atuais = {_chave_pendencia(p): p for p in pendentes if _chave_pendencia(p)}
    novos = [p for chave, p in atuais.items() if chave not in abertos]
    resolvidos = [pid for chave, pid in abertos.items() if chave not in atuais]
    linhas += [_linha(machine_id, p, pendente=True) for p in novos]

    try:
        if linhas:
            client.table(TABELA).insert(linhas).execute()
        if resolvidos:
            client.table(TABELA).update({"resolvido_em": _agora()}).in_("id", resolvidos).execute()
    except Exception as e:  # noqa: BLE001
        logger.error("Entrada: falha ao gravar o relatório do agente: %s", e)
        return out

    out.update(eventos=len(eventos_ok), novos_pendentes=novos, resolvidos=len(resolvidos), gravado=True)
    return out


def listar(dias: int = 30, limite: int = 500) -> Dict[str, Any]:
    """Os pendentes abertos (todas as máquinas) e os eventos do período."""
    client = _banco()
    if not client:
        return {"pendentes": [], "eventos": [], "banco": False}
    desde = (datetime.now(timezone.utc) - timedelta(days=max(1, dias))).isoformat()
    try:
        pend = (
            client.table(TABELA).select("*").in_("resultado", list(PENDENCIAS))
            .is_("resolvido_em", "null").order("quando", desc=True).limit(limite).execute()
        ).data or []
        evs = (
            client.table(TABELA).select("*").in_("resultado", [r for r in RESULTADOS_VALIDOS if r not in PENDENCIAS])
            .gte("quando", desde).order("quando", desc=True).limit(limite).execute()
        ).data or []
    except Exception as e:  # noqa: BLE001
        logger.error("Entrada: falha ao ler a tabela: %s", e)
        return {"pendentes": [], "eventos": [], "banco": True, "erro": "A tabela de entrada não respondeu."}
    for lista in (pend, evs):
        for x in lista:
            x["resultado_rotulo"] = ROTULO_RESULTADO.get(str(x.get("resultado") or ""), str(x.get("resultado") or ""))
    return {"pendentes": pend, "eventos": evs, "banco": True}


# ── E-mail aos administradores ────────────────────────────────────────────

def _emails_admins(settings) -> List[str]:
    fixos = alertas_config.destinatarios_configurados(getattr(settings, "alertas_destinatarios", "")) or ()
    if fixos:
        return sorted({e.strip().lower() for e in fixos if e.strip()})
    client = _banco()
    if not client:
        return []
    try:
        r = client.table("users").select("id, email, role, ativo").execute()
    except Exception as e:  # noqa: BLE001
        logger.warning("Entrada: não foi possível listar os administradores: %s", e)
        return []
    return sorted({
        str(c.get("email") or "").strip().lower()
        for c in (r.data or [])
        if conta_ativa(c) and str(c.get("role") or "").strip().lower() == "admin" and str(c.get("email") or "").strip()
    })


def _montar_email(pendentes: List[Dict[str, Any]], pasta: str) -> tuple[str, str]:
    n = len(pendentes)
    presos = sum(1 for p in pendentes if str(p.get("resultado") or "") == RESULTADO_VENCIDO_PRESO)
    na_entrada = n - presos
    assunto = f"[Certificados] {n} arquivo{'s' if n != 1 else ''} pendente{'s' if n != 1 else ''} nas pastas de certificados"
    linhas = "".join(
        f'<tr><td style="padding:6px 8px;border-bottom:1px solid #e5e5ea;">{html.escape(str(p.get("arquivo_original") or "—"))}</td>'
        f'<td style="padding:6px 8px;border-bottom:1px solid #e5e5ea;">{html.escape(str(p.get("pasta_origem") or pasta or "—"))}</td>'
        f'<td style="padding:6px 8px;border-bottom:1px solid #e5e5ea;">{html.escape(ROTULO_RESULTADO.get(str(p.get("resultado") or ""), ""))}</td>'
        f'<td style="padding:6px 8px;border-bottom:1px solid #e5e5ea;">{html.escape(str(p.get("motivo") or ""))}</td></tr>'
        for p in pendentes
    )
    partes = []
    if na_entrada:
        partes.append(f"{na_entrada} arquivo{'s' if na_entrada != 1 else ''} da pasta de entrada não {'abriram' if na_entrada != 1 else 'abriu'} e {'ficaram' if na_entrada != 1 else 'ficou'} lá, com o nome original, até alguém corrigir o nome ou a senha")
    if presos:
        partes.append(f"{presos} certificado{'s' if presos != 1 else ''} vencido{'s' if presos != 1 else ''} não {'puderam' if presos != 1 else 'pôde'} ser movido{'s' if presos != 1 else ''} para a pasta de vencidos e continua{'m' if presos != 1 else ''} na pasta da letra")
    corpo = f"""
    <html>
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color:#f5f5f7; padding:20px; color:#1d1d1f;">
        <div style="max-width:680px;margin:0 auto;background:#ffffff;border-radius:12px;padding:24px;box-shadow:0 4px 12px rgba(0,0,0,0.05);border:1px solid #e5e5ea;">
          <h2 style="margin-top:0;">Pendência{'s' if n != 1 else ''} nas pastas de certificados</h2>
          <p style="color:#6e6e73;margin-top:0;">{html.escape("; ".join(partes))}.</p>
          <table style="width:100%;border-collapse:collapse;font-size:13px;">
            <tr>
              <th style="text-align:left;padding:6px 8px;border-bottom:2px solid #e5e5ea;">Arquivo</th>
              <th style="text-align:left;padding:6px 8px;border-bottom:2px solid #e5e5ea;">Pasta</th>
              <th style="text-align:left;padding:6px 8px;border-bottom:2px solid #e5e5ea;">Situação</th>
              <th style="text-align:left;padding:6px 8px;border-bottom:2px solid #e5e5ea;">Motivo</th>
            </tr>
            {linhas}
          </table>
          <p style="font-size:12px;color:#86868b;margin-top:24px;margin-bottom:0;">
            Você recebe este aviso porque é administrador do portal. A lista completa está em Instalador › Movimentos.
          </p>
        </div>
      </body>
    </html>
    """
    return assunto, corpo


def notificar_pendentes(novos_pendentes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """E-mail aos administradores sobre pendentes NOVOS. Nunca levanta."""
    out = {"pendentes": len(novos_pendentes or []), "destinatarios": 0, "enviados": 0, "erros": 0, "alerts_disabled": False}
    if not novos_pendentes:
        return out
    try:
        settings = load_settings()
    except Exception as e:  # noqa: BLE001
        logger.error("Entrada: sem configuração para avisar dos pendentes: %s", e)
        out["erros"] = 1
        return out
    if not getattr(settings, "smtp_alerts_enabled", False) or not correio.configurado(settings):
        out["alerts_disabled"] = True
        return out
    destinatarios = _emails_admins(settings)
    out["destinatarios"] = len(destinatarios)
    assunto, corpo = _montar_email(novos_pendentes, getattr(settings, "pasta_entrada", "") or "")
    for email in destinatarios:
        try:
            send_smtp_email(
                host=settings.smtp_host, port=settings.smtp_port, user=settings.smtp_user,
                password_enc=settings.smtp_password_encrypted, use_tls=settings.smtp_use_tls,
                use_ssl=settings.smtp_use_ssl, from_email=settings.smtp_from_email,
                to_email=email, subject=assunto, html_content=corpo, settings=settings,
            )
            out["enviados"] += 1
        except Exception as e:  # noqa: BLE001
            out["erros"] += 1
            logger.error("Entrada: falha ao avisar %s dos pendentes: %s", email, e)
    return out


def receber_relatorio(machine_id: str, eventos: List[Dict[str, Any]], pendentes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Grava e, se houver pendente novo, avisa. Para o `/api/agent/entrada`."""
    r = registrar_relatorio(machine_id, eventos, pendentes)
    if r.get("novos_pendentes"):
        r["email"] = notificar_pendentes(r["novos_pendentes"])
    r["novos_pendentes"] = len(r.get("novos_pendentes") or [])
    return r
