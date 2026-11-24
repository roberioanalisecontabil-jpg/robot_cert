"""Chave de API de leitura para administrador (24/11/2026).

A chave vale como o admin que a criou, e só para leitura: `require_auth`
recusa qualquer método que não seja GET/HEAD, e `require_agent_or_admin`
recusa a chave (rotas da máquina: cofre, fila do agente). O texto claro existe
uma vez, na criação; o banco guarda só o sha256, como `machine_credentials`.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app import settings_state

logger = logging.getLogger(__name__)

TABELA = "api_chaves"
# O prefixo separa a chave do JWT no mesmo cabeçalho Bearer.
PREFIXO = "cg_ro_"
DIAS_MAXIMO = 365
# shortcut: carimba o último uso no máximo uma vez por minuto; trocar por fila
# se o volume de chamadas crescer.
CARIMBO_A_CADA = timedelta(minutes=1)


class SemBanco(RuntimeError):
    pass


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _hash(segredo: str) -> str:
    return hashlib.sha256((segredo or "").strip().encode("utf-8")).hexdigest()


def _quando(v: Any) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    s = str(v).strip().replace("Z", "+00:00")
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _sb():
    sb = settings_state._banco()
    if not sb:
        raise SemBanco("Banco não configurado.")
    return sb


def _publica(linha: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in linha.items() if k != "segredo_hash"}


def criar(user_id: str, nome: str, dias: int) -> Dict[str, Any]:
    """Cria a chave. Devolve a linha sem hash e o `segredo` em claro, uma vez."""
    nome = (nome or "").strip()[:80]
    if not nome:
        raise ValueError("Dê um nome à chave.")
    if not 1 <= int(dias) <= DIAS_MAXIMO:
        raise ValueError(f"Validade entre 1 e {DIAS_MAXIMO} dias.")
    segredo = PREFIXO + secrets.token_urlsafe(32)
    linha = {
        "nome": nome, "user_id": user_id, "segredo_hash": _hash(segredo),
        "criada_em": _agora().isoformat(), "expira_em": (_agora() + timedelta(days=int(dias))).isoformat(),
    }
    salva = (_sb().table(TABELA).insert(linha).execute().data or [linha])[0]
    logger.info("Chave de API %s criada para %s.", salva.get("id"), user_id)
    return {**_publica(salva), "segredo": segredo}


def autenticar(segredo: str, ip: str = "") -> Optional[Dict[str, Any]]:
    """A linha da chave viva, ou None (inexistente, revogada ou vencida)."""
    if not (segredo or "").startswith(PREFIXO):
        return None
    sb = _sb()
    alvo = _hash(segredo)
    linhas = sb.table(TABELA).select("*").eq("segredo_hash", alvo).limit(1).execute().data or []
    if not linhas or not hmac.compare_digest(str(linhas[0].get("segredo_hash") or ""), alvo):
        return None
    linha = linhas[0]
    agora = _agora()
    if linha.get("revogada_em"):
        return None
    expira = _quando(linha.get("expira_em"))
    if expira and expira <= agora:
        return None
    ultimo = _quando(linha.get("ultimo_uso_em"))
    if ultimo is None or agora - ultimo >= CARIMBO_A_CADA or (ip and ip != linha.get("ultimo_ip")):
        try:
            sb.table(TABELA).update({"ultimo_uso_em": agora.isoformat(), "ultimo_ip": ip or None}).eq("id", linha["id"]).execute()
        except Exception:  # noqa: BLE001
            # Falhar no carimbo não nega acesso a quem apresentou chave válida.
            logger.exception("Falha ao carimbar o uso da chave %s", linha.get("id"))
    return linha


def listar() -> List[Dict[str, Any]]:
    linhas = _sb().table(TABELA).select("*").order("criada_em", desc=True).execute().data or []
    return [_publica(l) for l in linhas]


def revogar(chave_id: str) -> bool:
    r = (_sb().table(TABELA).update({"revogada_em": _agora().isoformat()})
         .eq("id", chave_id).is_("revogada_em", "null").execute())
    return bool(r.data)
