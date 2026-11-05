"""Virada da senha da bandeja para os domínios da Microsoft.

Quando toda bandeja do CertGuard vista nos últimos 30 dias já está na versão
que entra pela Microsoft (e há ao menos uma), a senha deixa de valer no
registro da bandeja para esses domínios. A marca fica em `bandeja_virada`
(linha única: a chave primária é a trava entre processos) e não se desfaz
sozinha; sem `configurado()` ela não vale.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app import agent_devices, config, microsoft_entra

logger = logging.getLogger(__name__)

VERSAO_NOVA = (1, 2, 0)
JANELA_DIAS = 30
TABELA = "bandeja_virada"
PREFIXO = "certguard-"


def _quando(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def situacao(dispositivos: List[Dict[str, Any]], agora: datetime) -> Dict[str, Any]:
    corte = agora - timedelta(days=JANELA_DIAS)
    na_nova, segurando = 0, []
    for d in dispositivos:
        versao = d.get("versao") or ""
        visto = _quando(d.get("visto_em"))
        if d.get("revogado_em") or not versao.startswith(PREFIXO) or visto is None or visto < corte:
            continue
        v = agent_devices._versao_tupla(versao[len(PREFIXO):])
        if v is None:
            continue
        if v < VERSAO_NOVA:
            segurando.append(d)
        else:
            na_nova += 1
    return {"na_nova": na_nova, "segurando": segurando}


def pronta(s: Dict[str, Any]) -> bool:
    return s["na_nova"] >= 1 and not s["segurando"]


def desligada_em(sb: Any = None) -> Optional[str]:
    try:
        if sb is None:
            from app.settings_state import _banco
            sb = _banco()
        linhas = sb.table(TABELA).select("desligada_em").eq("id", 1).limit(1).execute().data or []
        return str(linhas[0]["desligada_em"]) if linhas else None
    except Exception as e:
        logger.warning(f"Não li a marca da virada da bandeja: {e}")
        return None


def senha_bloqueada(email: str) -> bool:
    return microsoft_entra.configurado() and microsoft_entra.dominio_liberado(email) and desligada_em() is not None


def conferir(sb: Any = None) -> Dict[str, Any]:
    if not microsoft_entra.configurado():
        return {"ligada": False}
    if sb is None:
        from app.settings_state import _banco
        sb = _banco()
    ja = desligada_em(sb)
    if ja:
        return {"desligada_em": ja}
    linhas = sb.table("agent_devices").select(
        "id, user_id, machine_id, nome, versao, visto_em, revogado_em").execute().data or []
    s = situacao(linhas, datetime.now(timezone.utc))
    if not pronta(s):
        return {"desligada_em": None, "na_nova": s["na_nova"], "segurando": len(s["segurando"])}
    try:
        sb.table(TABELA).insert({"id": 1, "versao": "1.2.0", "desligada_em": datetime.now(timezone.utc).isoformat()}).execute()
    except Exception as e:
        # Outro processo inseriu primeiro: a chave primária é a trava, e quem perde não avisa.
        logger.info(f"Virada da bandeja já gravada por outro processo: {e}")
        return {"desligada_em": desligada_em(sb)}
    from app import microsoft_conferencia

    microsoft_conferencia._enviar_ti(
        "A senha da bandeja foi desligada para os domínios da Microsoft",
        [f"Desligada em {datetime.now().strftime('%d/%m/%Y %H:%M')}.",
         f"Domínios: {', '.join(sorted(config.MICROSOFT_DOMINIOS))}.",
         "Quem é de fora dos domínios continua com e-mail e senha."],
    )
    return {"desligada_em": desligada_em(sb)}
