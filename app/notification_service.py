import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from app.settings_state import load_settings, load_colaborador_selecao, get_latest_snapshot

logger = logging.getLogger(__name__)

# Janela de ação: quantos dias para frente (expirando) e para trás (vencido há
# pouco) um alerta é considerado acionável. Fora dela o certificado continua
# listado e contabilizado, mas não conta para o badge do sino — 486 certificados
# vencidos há 1 a 2 anos num contador que nunca baixa deixam de ser sinal.
JANELA_ACAO_DIAS = 30

# Teto de itens devolvidos ao sino. O dropdown tem 320x400px; devolver 519 itens
# custava 167 KB por requisição e enterrava o que importa. O restante continua
# acessível em /vencidos.
NOTIF_MAX_ITENS = 50


def _chave_dedup(item: Dict[str, Any]) -> str:
    """
    Identidade do certificado para deduplicação.
    O mesmo certificado aparece em vários arquivos (é o que a página
    /duplicidades documenta), e o sino mostrava uma linha por arquivo.
    """
    fp = (item.get("fingerprint_sha256") or "").strip()
    if fp:
        return "fp:" + fp
    # Sem fingerprint (certificado ilegível), cai para a identidade de negócio.
    return "id:{}|{}|{}".format(
        (item.get("nome") or "").strip().lower(),
        (item.get("documento") or "").strip(),
        (item.get("vencimento") or "").strip(),
    )


def get_active_alerts(
    user_email: str, user_role: str, user_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Lista de alertas ativos (expirando ou vencidos) para o sino do portal,
    deduplicada por certificado e ordenada por urgência real.

    - Admins: alertas de todos os certificados do sistema.
    - Users: apenas dos certificados que selecionaram para acompanhar.
    """
    from app.main import _list_certificados_payload, _parse_iso_utc

    settings = load_settings()
    now = datetime.now(timezone.utc)

    snap = get_latest_snapshot()
    payload = _list_certificados_payload(settings, snap, "auto")
    itens = payload.get("itens") or []

    user_email_clean = (user_email or "").strip().lower()
    is_admin = (user_role or "").strip().lower() == "admin"

    selected_docs = []
    if not is_admin:
        selected_docs = load_colaborador_selecao(user_email_clean, user_id)
        selected_docs = ["".join(c for c in d if c.isdigit()) for d in selected_docs]

    alerts: List[Dict[str, Any]] = []

    for it in itens:
        venc_iso = it.get("not_after")
        if not venc_iso:
            continue

        try:
            v_dt = _parse_iso_utc(venc_iso)
        except Exception:
            continue

        if not is_admin:
            doc_digitos = "".join(c for c in (it.get("documento_numero") or "") if c.isdigit())
            if not doc_digitos:
                doc_digitos = "".join(c for c in (it.get("documento_formatado") or "") if c.isdigit())
            if doc_digitos not in selected_docs:
                continue

        dias = (v_dt.date() - now.date()).days
        nome = it.get("nome") or it.get("display_name") or "Certificado sem nome"

        if v_dt < now:
            tipo = "expired"
            dias_abs = abs(dias)
            if dias_abs == 0:
                mensagem = f"O certificado '{nome}' venceu hoje."
            elif dias_abs == 1:
                mensagem = f"O certificado '{nome}' venceu ontem."
            else:
                mensagem = f"O certificado '{nome}' venceu há {dias_abs} dias."
        elif 0 <= dias <= JANELA_ACAO_DIAS:
            tipo = "expiring"
            if dias == 0:
                mensagem = f"O certificado '{nome}' vence hoje."
            elif dias == 1:
                mensagem = f"O certificado '{nome}' vence amanhã."
            else:
                mensagem = f"O certificado '{nome}' vence em {dias} dias."
        else:
            continue

        alerts.append(
            {
                "fingerprint_sha256": it.get("fingerprint_sha256"),
                "nome": nome,
                "documento": it.get("documento_formatado") or it.get("documento_numero") or "Sem documento",
                "tipo": tipo,
                "vencimento": venc_iso,
                "dias_restantes": dias,
                "mensagem": mensagem,
                "acionavel": abs(dias) <= JANELA_ACAO_DIAS,
            }
        )

    # Deduplicação: o mesmo certificado em N arquivos vira 1 alerta, com a
    # contagem de arquivos preservada para não esconder a duplicidade.
    unicos: Dict[str, Dict[str, Any]] = {}
    for a in alerts:
        k = _chave_dedup(a)
        if k in unicos:
            unicos[k]["ocorrencias"] += 1
        else:
            a["ocorrencias"] = 1
            unicos[k] = a
    alerts = list(unicos.values())

    # Ordenação por urgência real.
    # Antes: vencidos primeiro, por dias_restantes crescente — como vencidos têm
    # dias negativos, isso punha o MAIS ANTIGO no topo (o que venceu há 2,5 anos)
    # e empurrava os "expirando" para o fim da lista.
    # Agora: expirando primeiro (dá para evitar a interrupção), do mais próximo
    # ao mais distante; depois vencidos, do mais recente ao mais antigo.
    alerts.sort(
        key=lambda x: (
            0 if x.get("tipo") == "expiring" else 1,
            x.get("dias_restantes") if x.get("tipo") == "expiring" else -x.get("dias_restantes", 0),
        )
    )

    return alerts


def build_notifications_payload(
    user_email: str, user_role: str, user_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Monta a resposta de /api/colaborador/notificacoes: lista limitada + totais.

    Os totais vão separados dos itens para que o portal possa mostrar
    "33 expirando · 486 vencidos" sem receber os 519 registros.
    """
    alerts = get_active_alerts(user_email, user_role, user_id)

    total_expirando = sum(1 for a in alerts if a.get("tipo") == "expiring")
    total_vencidos = sum(1 for a in alerts if a.get("tipo") == "expired")
    # Badge do sino: só o que está dentro da janela de ação.
    total_acionavel = sum(1 for a in alerts if a.get("acionavel"))
    agrupados = sum(int(a.get("ocorrencias") or 1) - 1 for a in alerts)

    itens = alerts[:NOTIF_MAX_ITENS]

    return {
        "itens": itens,
        "total": len(alerts),
        "total_expirando": total_expirando,
        "total_vencidos": total_vencidos,
        "total_acionavel": total_acionavel,
        "janela_acao_dias": JANELA_ACAO_DIAS,
        "exibidos": len(itens),
        "truncado": len(alerts) > len(itens),
        "arquivos_duplicados_agrupados": agrupados,
    }
