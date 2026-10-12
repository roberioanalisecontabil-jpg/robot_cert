"""Dashboard — Frente 3, leva 12 (12/10/2026).

Saiu de `app/main.py` sem mudar comportamento: as duas rotas do Dashboard
(visão geral e renovações). O cálculo continua em `app/dashboard.py`; a
página `/dashboard` fica em main.py com as outras páginas.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from app.sessao import require_admin

logger = logging.getLogger("app.main")
router = APIRouter()


@router.get("/api/dashboard", dependencies=[Depends(require_admin)])
def dashboard_visao_geral(dias: int = Query(30, ge=1, le=365)) -> dict:
    """
    Os painéis baratos do dashboard, numa chamada (~1s).

    Separado das renovações de propósito: aquele precisa de dois snapshots
    completos (~1 MB) e os outros sete somam poucas dezenas de KB. Fazer o
    barato esperar o caro atrasaria toda a tela pelo painel menos urgente.
    """
    from app import dashboard

    return dashboard.visao_geral(dias)


@router.get("/api/dashboard/renovacoes", dependencies=[Depends(require_admin)])
def dashboard_renovacoes(
    dias: int = Query(30, ge=1, le=365),
    machine_id: str = Query("ANALISESRV", min_length=1),
) -> dict:
    """
    Renovações: o inventário de hoje contra o de N dias atrás.

    Sai de `cert_snapshots`, não de `cert_history` — aquela é
    `upsert(on_conflict="arquivo_chave")` e guarda só o estado atual, então o valor
    anterior já foi sobrescrito e a conta daria zero.

    A resposta traz `referencia`: as varreduras têm lacunas, e pedir 30 dias
    pode devolver a comparação com uma de 54 dias atrás. Apresentar isso como
    "últimos 30 dias" seria mentira.
    """
    from app import dashboard

    return dashboard.painel_renovacoes(dias=dias, machine_id=machine_id)
