"""Entrar com a Microsoft: decide qual conta do CertGuard uma identidade da
Microsoft vira — ligar a existente, criar uma de operador ou recusar.

Sensível a tomada de conta: o `oid` é o vínculo estável e nunca é
sobrescrito; e-mail e UPN só servem para a PRIMEIRA ligação, e qualquer
dúvida (duas contas, oid de outra pessoa) recusa em vez de adivinhar.

Spec: docs/superpowers/specs/2026-11-04-login-microsoft-design.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional, Union

from app import auth
from app.db_pg import DbError
from app.microsoft_entra import Identidade, dominio_liberado
from app.smtp_service import encrypt_password


@dataclass
class Recusa:
    motivo: Literal["dominio", "convidado", "oid_diferente", "ambiguo", "desativada"]


def _um(sb: Any, coluna: str, valor: str) -> Optional[Dict[str, Any]]:
    rows = sb.table("users").select("*").eq(coluna, valor).limit(1).execute().data or []
    return rows[0] if rows else None


def _por_email(sb: Any, email: str) -> Optional[Dict[str, Any]]:
    return _um(sb, "email", email) if email else None


def _criar(sb: Any, ident: Identidade, email: str) -> tuple[Dict[str, Any], bool]:
    """Devolve (conta, criada_aqui). `criada_aqui` é False se outra requisição
    venceu a corrida: quem avisa os admins só pode ser quem criou de fato."""
    from app.acessorias import _hash_sem_senha

    criada = True
    try:
        sb.table("users").insert({
            "email": email,
            "full_name": ident.nome,
            "role": "user",
            "ativo": True,
            "origem": "microsoft",
            "password_hash": _hash_sem_senha(),
        }).execute()
    except DbError as e:
        if e.code != "23505":  # só violação de unicidade; o resto propaga
            raise
        # Corrida: outra requisição criou a mesma conta entre a busca e o
        # insert (e-mail único). Equivale a ON CONFLICT DO NOTHING: relê.
        criada = False
    return _por_email(sb, email) or {}, criada


def resolver_conta(sb: Any, ident: Identidade, refresh: str) -> Union[tuple[Dict[str, Any], bool], Recusa]:
    if ident.convidado:
        return Recusa("convidado")
    upn = (ident.upn or "").strip().lower()
    email = (ident.email or "").strip().lower()
    if not (dominio_liberado(upn) or dominio_liberado(email)):
        return Recusa("dominio")

    criada = False
    user = _um(sb, "microsoft_oid", ident.oid)
    if user is None:
        a, b = _por_email(sb, upn), _por_email(sb, email)
        if a and b and str(a.get("id")) != str(b.get("id")):
            return Recusa("ambiguo")
        user = a or b
        if user is not None and user.get("microsoft_oid"):
            return Recusa("oid_diferente")
        if user is None:
            # O e-mail da conta é o que está em domínio liberado: senão a
            # busca futura por ele não casaria com o UPN.
            user, criada = _criar(sb, ident, upn if dominio_liberado(upn) else email)
            if not user:
                return Recusa("ambiguo")

    if not auth.conta_ativa(user):
        return Recusa("desativada")

    mudanca: Dict[str, Any] = {
        "microsoft_conferido_em": datetime.now(timezone.utc).isoformat(),
        "microsoft_sem_conferencia": not refresh,
    }
    if not user.get("microsoft_oid"):
        mudanca["microsoft_oid"] = ident.oid
    if refresh:
        mudanca["microsoft_refresh_cifrado"] = encrypt_password(refresh)
    sb.table("users").update(mudanca).eq("id", user["id"]).execute()
    user.update(mudanca)
    return user, criada


def pode_usar_reserva(user: Dict[str, Any]) -> bool:
    """Senha + app como reserva se a Microsoft cair: só admin que já tem as
    duas pontas (vínculo Microsoft e app autenticador)."""
    return (
        str(user.get("role") or "").strip().lower() == "admin"
        and auth.conta_ativa(user)
        and bool(user.get("microsoft_oid"))
        and bool(user.get("totp_ativado_em"))
    )
