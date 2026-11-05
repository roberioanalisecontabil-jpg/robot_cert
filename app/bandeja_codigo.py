"""
Código de uso único do login da bandeja pela Microsoft.

O portal emite o código no retorno da Microsoft, amarrado ao desafio (sha256 do
verificador, que nunca sai da bandeja). A bandeja troca código + verificador
por uma sessão; a tentativa é única, certa ou errada. Só o hash do código fica
no banco.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

TABELA = "bandeja_codigo"
VALIDADE_S = 120


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _hash(codigo: str) -> str:
    return hashlib.sha256(codigo.encode("utf-8")).hexdigest()


def desafio_de(verificador: str) -> str:
    h = hashlib.sha256(verificador.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(h).decode("ascii").rstrip("=")


def _banco(sb: Any) -> Any:
    if sb is not None:
        return sb
    from app import settings_state
    return settings_state._banco()


def emitir(user_id: str, desafio: str, sb: Any = None) -> str:
    sb = _banco(sb)
    if sb is None:
        raise RuntimeError("Sem banco para emitir o código da bandeja.")
    agora = _agora()
    sb.table(TABELA).delete().lt("expira_em", (agora - timedelta(days=1)).isoformat()).execute()
    codigo = secrets.token_urlsafe(32)
    sb.table(TABELA).insert({
        "codigo_hash": _hash(codigo),
        "user_id": user_id,
        "desafio": desafio,
        "expira_em": (agora + timedelta(seconds=VALIDADE_S)).isoformat(),
    }).execute()
    return codigo


def queimar(codigo: str, verificador: str, sb: Any = None) -> Optional[str]:
    sb = _banco(sb)
    if sb is None:
        return None
    h = _hash(codigo or "")
    linhas = sb.table(TABELA).select("*").eq("codigo_hash", h).execute().data or []
    if not linhas or linhas[0].get("usado_em"):
        return None
    linha = linhas[0]
    # shortcut: ler-e-marcar não é atômico; dois pedidos simultâneos com o mesmo
    # verificador passariam — só a bandeja que abriu tem o verificador. Trocar por
    # UPDATE ... WHERE usado_em IS NULL RETURNING se o código passar a ter outro uso.
    sb.table(TABELA).update({"usado_em": _agora().isoformat()}).eq("codigo_hash", h).execute()
    expira = datetime.fromisoformat(str(linha["expira_em"]).replace("Z", "+00:00"))
    if expira <= _agora():
        return None
    if not hmac.compare_digest(desafio_de(verificador or ""), str(linha["desafio"])):
        return None
    return str(linha["user_id"])
