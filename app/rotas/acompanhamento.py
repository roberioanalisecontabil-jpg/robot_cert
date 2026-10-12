"""Acompanhamento — Frente 3, leva 11 (12/10/2026).

Saiu de `app/main.py` sem mudar comportamento: a seleção de certificados que
a pessoa acompanha (opções, ler, gravar), o painel, marcar notificações como
lidas e a preferência de alerta por e-mail.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import alertas_config, auth, correio, nomes, permissoes
from app.alcance import _documentos_ao_alcance, _recortar_pela_carteira
from app.notification_service import get_active_alerts
from app.rotas.certificados import _doc_norm, _lista_base_docs_historico
from app.sessao import _parse_iso_utc, _user_id_da_sessao, require_auth, require_modulo
from app.settings_state import (
    GravacaoNaoPersistida,
    load_colaborador_selecao,
    load_preferencia_alerta,
    load_settings,
    marcar_notificacoes_lidas,
    save_colaborador_selecao,
    save_preferencia_alerta,
)

logger = logging.getLogger("app.main")
router = APIRouter()


def _painel_docs_selecionados(doc_ids: List[str]) -> List[dict]:
    base = _lista_base_docs_historico()
    by_doc = {str(it.get("documento_digitos")): it for it in base}
    now = datetime.now(timezone.utc)
    out: List[dict] = []
    for d in doc_ids:
        it = by_doc.get(d)
        if not it:
            out.append(
                {
                    "documento_digitos": d,
                    "documento": d,
                    "nome": "Não encontrado no inventário atual",
                    "status": "nao_encontrado",
                    "vencimento_certificado": None,
                    "dias_restantes": None,
                }
            )
            continue
        v_iso = it.get("vencimento_certificado")
        v_dt = _parse_iso_utc(v_iso) if v_iso else datetime.min.replace(tzinfo=timezone.utc)
        dias = (v_dt.date() - now.date()).days if v_iso else None
        
        status_ult = str(it.get("status_ultimo") or "").lower()
        if status_ult == "expirado" or (v_iso and v_dt < now):
            status = "vencido"
        elif status_ult == "erro":
            status = "erro"
        elif status_ult == "fora_do_padrao":
            status = "fora_do_padrao"
        elif v_iso and dias is not None and 0 <= dias <= 30:
            status = "expirando"
        else:
            status = "ativo"

        out.append(
            {
                "documento_digitos": d,
                "documento": it.get("documento") or d,
                "nome": it.get("nome") or "—",
                "status": status,
                "vencimento_certificado": v_iso,
                "dias_restantes": dias,
            }
        )
    out.sort(
        key=lambda x: (
            0 if x.get("status") == "vencido" else 1,
            x.get("dias_restantes") if x.get("dias_restantes") is not None else 10**9,
        )
    )
    return out




def _dias_texto(d: Optional[int]) -> str:
    """"em 114 dias" / "vence hoje" / "há 3 dias": a coluna de número solto sai."""
    from app import texto as _texto
    if d is None:
        return ""
    if d == 0:
        return "vence hoje"
    if d < 0:
        return "há " + _texto.plural(-d, "dia")
    return "em " + _texto.plural(d, "dia")


class ColaboradorSelecaoBody(BaseModel):
    documentos: List[str] = Field(default_factory=list)


def _selecao_no_alcance(token: auth.TokenData, docs: List[str]) -> List[str]:
    """A seleção de Acompanhamento fica dentro do Alcance (decisão I4).

    Recortada ao gravar E ao ler: um Documento que saiu do Alcance (Exceção,
    Atribuição retirada, troca de Papel) deixa de aparecer no painel, no sino
    e no e-mail. A linha gravada não é apagada — se o Alcance voltar, a
    escolha volta junto; é preferência, não acesso.
    """
    alcance = _documentos_ao_alcance(token)
    if alcance is None:
        return list(docs)
    return [d for d in docs if d in alcance]


@router.get("/api/colaborador/certificados/opcoes", dependencies=[Depends(require_modulo("acompanhamento"))])
def colaborador_opcoes_certificados(token: auth.TokenData = Depends(require_auth)) -> dict:
    # O universo de clientes ia para todo mundo com `acompanhamento: ler`
    # (padrão de user e gestor) — o mesmo furo do #5 por outro caminho.
    alcance = _documentos_ao_alcance(token)
    itens = _recortar_pela_carteira(_lista_base_docs_historico(), alcance)
    now = datetime.now(timezone.utc)
    out = []
    for it in itens:
        v_iso = it.get("vencimento_certificado")
        v_dt = _parse_iso_utc(v_iso) if v_iso else datetime.min.replace(tzinfo=timezone.utc)
        dias = (v_dt.date() - now.date()).days if v_iso else None
        
        status_ult = str(it.get("status_ultimo") or "").lower()
        if status_ult == "expirado" or (v_iso and v_dt < now):
            status = "vencido"
        elif status_ult == "erro":
            status = "erro"
        elif status_ult == "fora_do_padrao":
            status = "fora_do_padrao"
        elif v_iso and dias is not None and 0 <= dias <= 30:
            status = "expirando"
        else:
            status = "ativo"
            
        out.append({
            **it,
            "status": status,
            "nome_exibicao": nomes.nome_exibicao(it.get("nome")),
            "dias_restantes": dias,
            "dias_texto": _dias_texto(dias),
        })
    # Operador sem Atribuição: a lista vem vazia porque ninguém lhe deu
    # cliente, não porque o inventário está vazio. A tela diz coisas diferentes.
    from app import texto as _texto
    return {
        "itens": out,
        "total": len(out),
        "alcance_vazio": isinstance(alcance, set) and not alcance,
        "textos": {"total": _texto.plural(len(out), "cliente ao seu alcance", "clientes ao seu alcance")},
    }


@router.get("/api/colaborador/certificados/selecionados", dependencies=[Depends(require_modulo("acompanhamento"))])
def colaborador_get_selecionados(token: auth.TokenData = Depends(require_auth)) -> dict:
    email = (token.email or "").strip().lower()
    docs = _selecao_no_alcance(token, load_colaborador_selecao(email, _user_id_da_sessao(token)))
    return {"documentos": docs, "total": len(docs)}


@router.put("/api/colaborador/certificados/selecionados", dependencies=[Depends(require_modulo("acompanhamento", permissoes.NIVEL_EDITAR))])
def colaborador_put_selecionados(
    body: ColaboradorSelecaoBody, token: auth.TokenData = Depends(require_auth)
) -> dict:
    email = (token.email or "").strip().lower()
    pedidos = sorted({_doc_norm(x) for x in body.documentos if _doc_norm(x)})
    docs = _selecao_no_alcance(token, pedidos)
    save_colaborador_selecao(email, docs, _user_id_da_sessao(token))
    return {"ok": True, "documentos": docs, "total": len(docs), "fora_do_alcance": len(pedidos) - len(docs)}


@router.get("/api/colaborador/certificados/painel", dependencies=[Depends(require_modulo("acompanhamento"))])
def colaborador_painel_certificados(token: auth.TokenData = Depends(require_auth)) -> dict:
    email = (token.email or "").strip().lower()
    docs = _selecao_no_alcance(token, load_colaborador_selecao(email, _user_id_da_sessao(token)))
    itens = _painel_docs_selecionados(docs)
    from app import texto as _texto
    for it in itens:
        it["nome_exibicao"] = nomes.nome_exibicao(it.get("nome"))
        it["dias_texto"] = _dias_texto(it.get("dias_restantes"))
    total = len(itens)
    return {
        "itens": itens,
        "total": total,
        # Com poucos itens a lista inteira cabe na tela e a busca é ruído.
        "mostrar_busca": total > 10,
        "textos": {
            "total": _texto.plural(total, "certificado acompanhado", "certificados acompanhados"),
        },
    }


@router.post(
    "/api/colaborador/notificacoes/lidas",
    dependencies=[Depends(require_auth)],
)
def marcar_notificacoes_como_lidas(token: auth.TokenData = Depends(require_auth)) -> dict:
    """"Li todos": esconde os avisos que estão no sino AGORA.

    O servidor decide o que marcar, e não a tela. Se a lista viesse do cliente,
    um aviso que apareceu entre o carregamento do dropdown e o clique seria
    marcado como lido sem nunca ter sido visto — e some sem deixar rastro.

    `require_auth`, sem módulo (decisão I5): marcar como lido é preferência de
    exibição de quem está lendo, e o sino está em toda página.
    """
    uid = _user_id_da_sessao(token)
    # `get_active_alerts` e não o payload: o payload corta em 50 itens para o
    # dropdown, e marcar só os 50 deixaria o badge aceso depois de "li todos" —
    # o botão pareceria não ter funcionado. O badge conta o acionável inteiro,
    # então é o acionável inteiro que precisa ser marcado.
    alertas = get_active_alerts(token.email or "", token.role or "", uid)
    chaves = [a.get("chave") for a in alertas if a.get("chave") and a.get("acionavel")]
    try:
        marcadas = marcar_notificacoes_lidas(uid, chaves)
    except GravacaoNaoPersistida as e:
        logger.error("Notificações lidas não persistidas: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Não foi possível marcar como lido. Veja o log do servidor.",
        )
    return {"marcadas": marcadas}


class NotificacaoLidaBody(BaseModel):
    chave: str = Field(min_length=1, max_length=200)


@router.post(
    "/api/colaborador/notificacoes/lida",
    dependencies=[Depends(require_auth)],
)
def marcar_notificacao_como_lida(body: NotificacaoLidaBody, token: auth.TokenData = Depends(require_auth)) -> dict:
    """Marca UM aviso como lido (pedido de 30/09/2026: além do "Li todos").

    A chave vem da tela, mas só vale se estiver entre os avisos acionáveis
    desta pessoa AGORA — o servidor confere antes de gravar. Sem isso, a rota
    aceitaria marcar como lida qualquer chave inventada (inofensivo para os
    outros, porque a marca é por usuário, mas lixo na tabela).
    """
    uid = _user_id_da_sessao(token)
    chave = body.chave.strip()
    alertas = get_active_alerts(token.email or "", token.role or "", uid)
    validas = {a.get("chave") for a in alertas if a.get("chave") and a.get("acionavel")}
    if chave not in validas:
        raise HTTPException(status_code=404, detail="Este aviso não está entre os seus avisos pendentes.")
    try:
        marcadas = marcar_notificacoes_lidas(uid, [chave])
    except GravacaoNaoPersistida as e:
        logger.error("Notificação lida não persistida: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Não foi possível marcar como lido. Veja o log do servidor.",
        )
    return {"marcadas": marcadas}


class PreferenciaAlertaBody(BaseModel):
    notificar_email: bool = Field(default=True)
    # Marcos que a pessoa DISPENSA. Ver a migration 20260820200000 para o
    # porquê de guardar as recusas em vez das aceitações.
    marcos_ignorados: str = Field(default="")


@router.get(
    "/api/colaborador/alertas/preferencia",
    dependencies=[Depends(require_modulo("acompanhamento"))],
)
def obter_preferencia_alerta(token: auth.TokenData = Depends(require_auth)) -> dict:
    """A preferência da pessoa, mais os marcos que o portal realmente dispara.

    Os dois juntos numa resposta só: a tela monta uma caixa por marco DO
    PORTAL, e não uma lista fixa. Marco que o administrador acrescentar aparece
    para todo mundo, ligado — porque o que se guarda é a recusa.
    """
    pref = load_preferencia_alerta(_user_id_da_sessao(token))
    s = load_settings()
    marcos = alertas_config.marcos_efetivos(s.alertas_marcos)
    ignorados = set(alertas_config.marcos_ignorados(pref["alerta_marcos_ignorados"] or ""))
    efetivos = [m for m in marcos if m not in ignorados]
    # Frase pronta para a tela ("60, 30, 15 e 7 dias antes e no dia do
    # vencimento"): os prazos por extenso, não "4 prazos".
    if efetivos:
        lista = [str(m) for m in efetivos]
        antes = (", ".join(lista[:-1]) + " e " + lista[-1]) if len(lista) > 1 else lista[0]
        frase = antes + (" dia antes" if len(lista) == 1 and efetivos[0] == 1 else " dias antes") + " e quando vencer"
    else:
        frase = "só quando vencer"
    return {
        "notificar_email": pref["notificar_email"],
        "marcos_ignorados": pref["alerta_marcos_ignorados"],
        "marcos_do_portal": list(marcos),
        "marcos_efetivos": efetivos,
        "destinatario": (token.email or "").strip().lower(),
        "texto": frase,
        # Sem SMTP configurado, nenhuma preferência muda nada — e a tela
        # precisa dizer isso em vez de prometer e-mails que não saem.
        "envio_ativo": bool(s.smtp_alerts_enabled and correio.configurado(s)),
    }


@router.put(
    "/api/colaborador/alertas/preferencia",
    dependencies=[Depends(require_modulo("acompanhamento", permissoes.NIVEL_EDITAR))],
)
def salvar_preferencia_alerta(
    body: PreferenciaAlertaBody, token: auth.TokenData = Depends(require_auth)
) -> dict:
    try:
        ignorados = alertas_config.formatar_marcos(
            alertas_config.parse_marcos(body.marcos_ignorados)
        )
    except alertas_config.ConfiguracaoInvalida as e:
        raise HTTPException(status_code=422, detail=str(e))

    try:
        save_preferencia_alerta(
            _user_id_da_sessao(token), body.notificar_email, ignorados
        )
    except GravacaoNaoPersistida as e:
        logger.error("Preferência de alerta não persistida: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Não foi possível gravar a preferência. Veja o log do servidor.",
        )
    return obter_preferencia_alerta(token)
