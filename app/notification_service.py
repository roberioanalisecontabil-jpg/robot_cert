import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from app import alertas_config
from app.cert_installer import documentos_ao_alcance
from app.settings_state import (
    carregar_notificacoes_lidas,
    chaves_registradas_recentemente,
    get_latest_snapshot,
    load_colaborador_selecao,
    load_settings,
)

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

# "Novo": apareceu na pasta há menos de tantos dias (30/09/2026). Depois disso
# o certificado continua no Início como qualquer outro; o aviso é sobre o
# evento de ter chegado, e evento velho não é aviso.
JANELA_NOVOS_DIAS = 7


def _so_digitos(valor: Any) -> str:
    return "".join(c for c in str(valor or "") if c.isdigit())


def _documento_do_item(it: Dict[str, Any]) -> str:
    return _so_digitos(it.get("documento_numero")) or _so_digitos(it.get("documento_formatado"))


def _alcance_para_novos(user_id: Optional[str], role: str) -> Optional[set]:
    """Documentos cujos certificados novos esta pessoa vê: a carteira (o que
    ela pode instalar). `None` = todos. Um certificado que acabou de chegar
    nunca está na seleção de Acompanhamento — é por isso que o recorte dos
    novos é a carteira, e não a seleção. Carteira ilegível = nenhum novo, e o
    sino segue de pé."""
    try:
        return documentos_ao_alcance(user_id or "", role)
    except Exception as e:  # noqa: BLE001 - CarteiraIndisponivel/AlcanceIndisponivel
        logger.warning("Sem os certificados novos para %s: %s", user_id or "?", e)
        return set()


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

    A assimetria é DELIBERADA, e foi reconfirmada em 20/08/2026 quando o
    "Li todos" foi implementado. A alternativa — o sino do admin seguir a
    seleção dele em Acompanhamento — foi considerada e recusada: um admin que
    não selecionou nada ficaria com o sino vazio, e ninguém no portal veria os
    certificados vencendo. A visão geral é o que faz este sino servir para
    administrar o portal em vez de só a própria carteira.

    O acúmulo que motivou a dúvida (58 itens) é problema de leitura, e quem
    resolve isso é o "Li todos" — não estreitar o escopo.
    """
    from app.main import _list_certificados_payload, _parse_iso_utc

    settings = load_settings()
    now = datetime.now(timezone.utc)
    # Os marcos do portal, uma leitura só para a lista inteira.
    marcos = alertas_config.marcos_efetivos(getattr(settings, "alertas_marcos", ""))

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

    # ── Novos na pasta ─────────────────────────────────────────────────────
    recentes = chaves_registradas_recentemente(JANELA_NOVOS_DIAS)
    if recentes:
        alcance = None if is_admin else _alcance_para_novos(user_id, user_role)
        # Fingerprints que já existem num arquivo ANTIGO: uma cópia ou um
        # arquivo renomeado tem chave nova, mas não é certificado novo.
        fps_antigos = {
            str(it.get("fingerprint_sha256") or "").strip().lower()
            for it in itens
            if it.get("fingerprint_sha256") and str(it.get("arquivo_chave") or "") not in recentes
        }
        for it in itens:
            quando = recentes.get(str(it.get("arquivo_chave") or ""))
            if not quando:
                continue
            fp_item = str(it.get("fingerprint_sha256") or "").strip().lower()
            if fp_item and fp_item in fps_antigos:
                continue
            if alcance is not None and _documento_do_item(it) not in alcance:
                continue
            nome = it.get("nome") or it.get("display_name") or "Certificado sem nome"
            try:
                dias_na_pasta = (now.date() - _parse_iso_utc(quando).date()).days
            except Exception:  # noqa: BLE001
                dias_na_pasta = 0
            if dias_na_pasta <= 0:
                mensagem = f"O certificado '{nome}' foi adicionado à pasta hoje."
            elif dias_na_pasta == 1:
                mensagem = f"O certificado '{nome}' foi adicionado à pasta ontem."
            else:
                mensagem = f"O certificado '{nome}' foi adicionado à pasta há {dias_na_pasta} dias."
            venc_iso = it.get("not_after")
            dias_venc: Optional[int] = None
            if venc_iso:
                try:
                    dias_venc = (_parse_iso_utc(venc_iso).date() - now.date()).days
                except Exception:  # noqa: BLE001
                    dias_venc = None
            alerts.append(
                {
                    "chave": f"{it.get('fingerprint_sha256') or nome}|novo",
                    "fingerprint_sha256": it.get("fingerprint_sha256"),
                    "nome": nome,
                    "documento": it.get("documento_formatado") or it.get("documento_numero") or "Sem documento",
                    "tipo": "novo",
                    "vencimento": venc_iso,
                    "dias_restantes": dias_venc,
                    "registrado_em": quando,
                    "dias_na_pasta": dias_na_pasta,
                    "mensagem": mensagem,
                    "acionavel": True,
                }
            )

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

        # MESMA chave do antispam de e-mail (`alert_state`), de propósito: o
        # sino e o e-mail passam a concordar sobre o que é "um aviso". Marcar
        # como lido esconde ESTE limiar; ao cruzar o próximo, o certificado
        # reaparece sozinho — que é a diferença entre "li isso" e "não me avise
        # mais sobre este certificado".
        marco = "expired" if tipo == "expired" else f"expiring:{alertas_config.marco_de(dias, marcos)}"
        chave = f"{it.get('fingerprint_sha256') or nome}|{marco}"

        alerts.append(
            {
                "chave": chave,
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
        # "Novo" e "vencendo" do mesmo certificado são dois avisos, não um.
        k = ("novo:" if a.get("tipo") == "novo" else "") + _chave_dedup(a)
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
    # Novos antes de tudo (30/09/2026): são o evento mais recente e o mais
    # fácil de perder de vista; do que chegou por último ao mais antigo.
    def _ordem(x: Dict[str, Any]):
        tipo = x.get("tipo")
        if tipo == "novo":
            return (0, x.get("dias_na_pasta") or 0, "")
        if tipo == "expiring":
            return (1, x.get("dias_restantes") or 0, "")
        return (2, -(x.get("dias_restantes") or 0), "")

    alerts.sort(key=_ordem)

    return alerts


TIPOS_DE_AVISO = ("novo", "expiring", "expired")


def build_notifications_payload(
    user_email: str, user_role: str, user_id: Optional[str] = None,
    tipo: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Monta a resposta de /api/colaborador/notificacoes: lista limitada + totais.

    Os totais vão separados dos itens para que o portal possa mostrar
    "33 expirando · 486 vencidos" sem receber os 519 registros.

    O que a pessoa já marcou como lido sai da lista E dos totais. Deixá-lo nos
    totais faria o badge continuar aceso depois de "li todos" — que é
    exatamente o que o botão existe para resolver.
    """
    alerts = get_active_alerts(user_email, user_role, user_id)

    lidas = carregar_notificacoes_lidas(user_id)
    if lidas:
        alerts = [a for a in alerts if a.get("chave") not in lidas]

    total_novos = sum(1 for a in alerts if a.get("tipo") == "novo")
    total_expirando = sum(1 for a in alerts if a.get("tipo") == "expiring")
    total_vencidos = sum(1 for a in alerts if a.get("tipo") == "expired")
    # Badge do sino: só o que está dentro da janela de ação.
    total_acionavel = sum(1 for a in alerts if a.get("acionavel"))
    agrupados = sum(int(a.get("ocorrencias") or 1) - 1 for a in alerts)

    # Filtro do sino (30/09/2026). O teto de 50 é sobre a LISTA DEVOLVIDA:
    # sem o recorte no servidor, "Vencidos 72" abria vazio quando os 50
    # primeiros eram novos e expirando — o chip prometia o que o cliente não
    # tinha. Os totais continuam os do conjunto inteiro, para os chips.
    recorte = [a for a in alerts if a.get("tipo") == tipo] if tipo in TIPOS_DE_AVISO else alerts
    itens = recorte[:NOTIF_MAX_ITENS]

    return {
        "itens": itens,
        "tipo": tipo if tipo in TIPOS_DE_AVISO else None,
        "total": len(alerts),
        "total_novos": total_novos,
        "total_expirando": total_expirando,
        "total_vencidos": total_vencidos,
        "total_acionavel": total_acionavel,
        "janela_acao_dias": JANELA_ACAO_DIAS,
        "janela_novos_dias": JANELA_NOVOS_DIAS,
        "exibidos": len(itens),
        "truncado": len(recorte) > len(itens),
        "arquivos_duplicados_agrupados": agrupados,
    }
