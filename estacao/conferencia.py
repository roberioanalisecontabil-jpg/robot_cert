"""Conferência de remoção (Frente B, 14/11/2026), do lado da bandeja.

Spec: docs/superpowers/specs/2026-11-13-carteira-certificados-remocao-uso-design.md,
"Frente B". A bandeja manda ao portal o que há no `CurrentUser\\My` e o
resultado das remoções da rodada anterior; o portal responde o que sai. Daqui
só sai o que o portal mandou E que esta rodada viu no repositório. Qualquer
falha (portal fora, 403, 503, repositório ilegível) não remove nada, e os
resultados pendentes vão de novo na próxima rodada.

Esta função nunca encerra nem apaga a conta: um 403 do sem-conta é a chave da
máquina que não confere, não a sessão da pessoa.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any, Callable

from estacao import chave_maquina, repositorio
from estacao import conta as cc

LOGGER = logging.getLogger(__name__)

TETO = 500  # o portal recusa listas maiores (422)

REMOVIDO = "Certificado {nome} removido: saiu da sua carteira."
REMOVIDO_SEM_CONTA = " Entre na bandeja e peça de novo no portal, se precisar."
SEM_LOGIN = ("Entre na bandeja do CertGuard. Sem login, os certificados da empresa "
             "serão retirados deste computador em {N} dias.")
AVISO = "O certificado {nome} será retirado deste computador em {N} dias: {motivo}."
VENCIMENTO = "O acesso ao certificado {nome} vence em {N} dias. Fale com seu gestor."

# (tipo, ...) -> dia do último aviso: prazo e vencimento, no máximo um por dia.
_AVISADO_EM: dict[tuple, date] = {}


def _usuario_windows() -> str:
    return f"{os.getenv('USERDOMAIN', '')}\\{os.getenv('USERNAME', '')}"


def conferir(sessao, versao: str, avisar: Callable[[str], None], hoje: date,
             pendentes: list[dict], machine_id: str) -> list[dict]:
    """Uma rodada. Devolve os resultados a mandar na próxima (ou `pendentes`,
    se esta rodada não chegou ao portal)."""
    itens = repositorio.listar()
    if not itens:
        # Falha do PowerShell também vira []: mandar lista vazia faria o
        # portal dar por resolvido o que está pendente.
        return pendentes
    por_sha = {i.sha256.lower(): i for i in itens}
    # shortcut: acima de 500 certificados no perfil, o resto fica de fora da rodada.
    corpo: dict[str, Any] = {"usuario_windows": _usuario_windows(),
                             "certificados": sorted(por_sha)[:TETO], "resultados": pendentes[:TETO]}
    conectado = cc.esta_conectado()
    sem_login = False
    if conectado:
        url = cc.portal_da_conta() + "/api/estacao/conferencia"
        cabecalhos = cc.cabecalhos(versao)
    else:
        dono = cc.ultimo_dono() or {}
        mid = dono.get("machine_id") or machine_id
        if not mid or mid == "unknown":
            return pendentes
        corpo.update(machine_id=mid, chave=chave_maquina.ler(), segredo=dono.get("segredo"))
        sem_login = not dono.get("segredo")
        portal = (dono.get("portal") or cc.portal_da_conta()).strip().rstrip("/")
        url = portal + "/api/estacao/conferencia/sem-conta"
        cabecalhos = {"Content-Type": "application/json", "X-Agent-Version": versao}
    try:
        r = sessao.post(url, json=corpo, headers=cabecalhos, timeout=30)
        if r.status_code != 200:
            LOGGER.warning("Conferência de remoção: portal respondeu %s.", r.status_code)
            return pendentes
        resposta = r.json() or {}
    except Exception as e:  # noqa: BLE001
        LOGGER.warning("Conferência de remoção: portal indisponível agora: %s", e)
        return pendentes

    resultados: list[dict] = []
    remover = resposta.get("remover") if isinstance(resposta, dict) else None
    for ordem in remover if isinstance(remover, list) else []:
        if not isinstance(ordem, dict):
            continue
        item = por_sha.pop(str(ordem.get("fingerprint") or "").lower(), None)
        if item is None:  # o portal mandou o que esta rodada não viu: ignora
            continue
        ok, erro = repositorio.remover(item)
        resultados.append({"fingerprint": item.sha256.lower(), "ok": ok, "erro": str(erro or "")[:500]})
        LOGGER.info("Remoção de %s (%s): %s", item.thumbprint, ordem.get("motivo"), "ok" if ok else erro)
        if ok:
            texto = REMOVIDO.format(nome=ordem.get("nome") or item.nome)
            avisar(texto if conectado else texto + REMOVIDO_SEM_CONTA)

    try:
        _avisos(resposta, sem_login, hoje, avisar)
    except Exception:  # noqa: BLE001 — aviso malformado não pode perder os resultados acima
        LOGGER.exception("Conferência de remoção: avisos ilegíveis na resposta")
    return resultados


def _uma_vez_por_dia(chave: tuple, hoje: date) -> bool:
    if _AVISADO_EM.get(chave) == hoje:
        return False
    _AVISADO_EM[chave] = hoje
    return True


def _avisos(resposta: dict, sem_login: bool, hoje: date, avisar: Callable[[str], None]) -> None:
    """Prazo e vencimento: cada aviso no máximo uma vez por dia."""
    avisos = resposta.get("avisos") or []
    if sem_login and avisos:
        if _uma_vez_por_dia(("sem_login",), hoje):
            avisar(SEM_LOGIN.format(N=max(int(a.get("dias") or 0) for a in avisos)))
    else:
        for a in avisos:
            if _uma_vez_por_dia(("aviso", str(a.get("motivo")), str(a.get("documento"))), hoje):
                avisar(AVISO.format(nome=a.get("nome") or a.get("documento"), N=a.get("dias"),
                                    motivo=a.get("motivo")))

    for v in resposta.get("vencendo") or []:
        doc = str(v.get("documento"))
        try:
            dias = (date.fromisoformat(str(v.get("vence_em"))[:10]) - hoje).days
        except ValueError:
            continue
        if _uma_vez_por_dia(("vencendo", doc), hoje):
            avisar(VENCIMENTO.format(nome=v.get("nome") or doc, N=dias))
