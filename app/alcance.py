"""O que cada sessão alcança no acervo — Frente 3, leva 3 (09/10/2026).

Saiu de `app/main.py` sem mudar comportamento: o recorte pela carteira
(ADR 0001; desde 08/10/2026 o Início mostra tudo e marca `instalavel`) e a
consulta "este certificado está no cofre?". Usado pelo Início, pelos
detalhes do certificado, pelo SIEG e pelas listas recortadas.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Set

from fastapi import HTTPException

from app import auth, cert_installer
from app.sessao import _user_id_da_sessao

logger = logging.getLogger("app.main")


def _documentos_ao_alcance(token: auth.TokenData) -> Optional[Set[str]]:
    """O que esta sessão pode LER, em documentos. `None` = tudo.

    Um ponto só para todas as leituras do acervo (achados #5, #32): antes o
    portal impedia INSTALAR fora da carteira e deixava LER a base inteira de
    clientes. Sem banco configurado (modo local de arquivos) não há
    diretório de usuários nem carteira — e nem login que emita sessão — então
    não há por onde recortar; a leitura segue como sempre seguiu.
    """
    from app.settings_state import _banco

    papel = (token.role or "").strip().lower()
    if papel in cert_installer.PAPEIS_COM_ALCANCE_TOTAL or papel == "agent":
        return None
    if not _banco():
        return None
    try:
        return cert_installer.documentos_ao_alcance(_user_id_da_sessao(token) or "", papel)
    except (cert_installer.CarteiraIndisponivel, cert_installer.AlcanceIndisponivel) as e:
        logger.warning("Alcance de leitura indisponível para %s: %s", token.email, e)
        raise HTTPException(status_code=503, detail="Não foi possível verificar sua carteira. Tente de novo.")


def _no_alcance(it: dict, alcance: Optional[Set[str]]) -> bool:
    if alcance is None:
        return True
    doc = cert_installer.so_digitos(it.get("documento_numero") or it.get("documento_digitos") or it.get("documento"))
    return bool(doc and doc in alcance)


def _marcar_instalaveis(itens: List[dict], alcance: Optional[Set[str]]) -> None:
    """`instalavel` em cada item do Início: está na carteira de quem pergunta."""
    for it in itens:
        it["instalavel"] = _no_alcance(it, alcance)


def _recortar_pela_carteira(itens: List[dict], alcance: Optional[Set[str]]) -> List[dict]:
    """Só os itens cujo documento está no alcance. Item sem documento não é
    de ninguém e fica de fora para quem não tem alcance total."""
    if alcance is None:
        return itens
    saida = []
    for it in itens:
        doc = cert_installer.so_digitos(it.get("documento_numero") or it.get("documento_digitos") or it.get("documento"))
        if doc and doc in alcance:
            saida.append(it)
    return saida


def _no_cofre(fingerprint: str) -> Optional[bool]:
    """Há PFX deste certificado no cofre? `None` = não deu para saber."""
    from app.settings_state import _banco

    client = _banco()
    if not client:
        return None
    try:
        r = client.table("cert_pfx_store").select("id").eq("fingerprint", fingerprint).limit(1).execute()
        return bool(r.data)
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao consultar o cofre para o modal de detalhes")
        return None
