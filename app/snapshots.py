"""Expurgo de `cert_snapshots` (03/10/2026).

Uma linha por máquina por varredura, com o inventário inteiro em `items`
(~1 MB cada no ANALISESRV), e nada a tirava desde abril. O que importa por
mais tempo já mora em `cert_history` (estado atual por arquivo, com a data de
primeiro registro) e na trilha; o snapshot serve a "quando esse arquivo mudou"
e às renovações do Dashboard, que leem dois.

**A última varredura de cada máquina nunca é apagada**, por mais velha que
seja: se o agente parar por seis meses, o portal continua mostrando o último
inventário conhecido em vez de uma tela vazia. Apagar por idade sem essa
guarda é a mesma armadilha de falha-aberta que o expurgo do cofre evita.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app import settings_state

logger = logging.getLogger(__name__)

RETENCAO_PADRAO_DIAS = 180
LOTE_DELETE = 200


def retencao_dias() -> int:
    """`SNAPSHOTS_RETENCAO_DIAS` no ambiente; 0 desliga. Padrão 180."""
    bruto = os.getenv("SNAPSHOTS_RETENCAO_DIAS", "").strip()
    if not bruto:
        return RETENCAO_PADRAO_DIAS
    try:
        return max(0, int(bruto))
    except ValueError:
        logger.warning("SNAPSHOTS_RETENCAO_DIAS inválido (%r); usando %d", bruto, RETENCAO_PADRAO_DIAS)
        return RETENCAO_PADRAO_DIAS


def _instante(valor: Any) -> Optional[datetime]:
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    s = str(valor or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def expurgar(dias: Optional[int] = None) -> Dict[str, Any]:
    """Apaga snapshots anteriores à retenção, preservando o mais recente de
    cada máquina. Devolve o que fez, para o job reportar."""
    if dias is None:
        dias = retencao_dias()
    if not dias or dias <= 0:
        return {"executado": False, "motivo": "retenção desligada (0 = guardar tudo)"}

    client = settings_state._banco()  # em tempo de chamada: o teste troca o banco
    if not client:
        return {"executado": False, "motivo": "Banco não configurado"}

    agora = datetime.now(timezone.utc)
    corte_dt = agora - timedelta(days=dias)
    corte = corte_dt.isoformat()
    try:
        r = client.table("cert_snapshots").select("id, machine_id, scanned_at").execute()
        linhas: List[dict] = list(r.data or [])
    except Exception as e:  # noqa: BLE001
        logger.exception("Falha ao listar cert_snapshots para expurgo")
        return {"executado": False, "motivo": str(e)}

    # O mais recente de cada máquina fica, seja qual for a idade.
    mais_recente: Dict[str, tuple] = {}
    for l in linhas:
        m = str(l.get("machine_id") or "default")
        d = _instante(l.get("scanned_at"))
        if d is None:
            continue
        if m not in mais_recente or d > mais_recente[m][0]:
            mais_recente[m] = (d, str(l.get("id")))
    preservados = {id_ for _, id_ in mais_recente.values()}

    alvo = [
        str(l.get("id"))
        for l in linhas
        if str(l.get("id")) not in preservados
        and (_instante(l.get("scanned_at")) or agora) < corte_dt
    ]
    apagados = 0
    try:
        for i in range(0, len(alvo), LOTE_DELETE):
            fatia = alvo[i : i + LOTE_DELETE]
            client.table("cert_snapshots").delete().in_("id", fatia).execute()
            apagados += len(fatia)
    except Exception as e:  # noqa: BLE001
        logger.exception("Falha no expurgo de cert_snapshots")
        return {"executado": False, "motivo": str(e), "apagados": apagados}

    logger.info("Expurgo de cert_snapshots: %d anteriores a %s (preservado o último de %d máquina(s))",
                apagados, corte, len(preservados))
    return {
        "executado": True,
        "apagados": apagados,
        "corte": corte,
        "retencao_dias": dias,
        "preservados": len(preservados),
    }

