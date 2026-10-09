"""O que cada sessão alcança no acervo — Frente 3, leva 3 (09/10/2026).

Saiu de `app/main.py` sem mudar comportamento: o recorte pela carteira
(ADR 0001; desde 08/10/2026 o Início mostra tudo e marca `instalavel`) e a
consulta "este certificado está no cofre?". Usado pelo Início, pelos
detalhes do certificado, pelo SIEG e pelas listas recortadas.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Set

from fastapi import Depends, HTTPException

from app import auth, cert_installer, permissoes
from app.sessao import _user_id_da_sessao, require_auth

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


ERRO_SEM_ALCANCE = (
    "Você não lidera nenhum departamento, então não é Gestor e não há a "
    "quem atribuir clientes. Peça a um administrador para designá-lo em "
    "Usuários › Departamentos."
)


async def require_admin_ou_gestor(
    token: auth.TokenData = Depends(require_auth),
) -> auth.TokenData:
    """
    Quem pode montar carteira: admin, ou quem lidera ao menos um departamento
    — que, desde o ADR 0001, é a definição de Gestor.

    A matriz de permissões (`require_modulo("carteiras", ...)` nas rotas) diz
    SE o papel alcança Carteiras; esta guarda cuida do outro eixo, a
    LIDERANÇA, que diz DE QUEM. Cada rota ainda confere o alvo com
    `cert_installer.pode_gerir`: Gestor só edita a carteira de Operador dos
    departamentos que lidera.

    Quem lidera nada é recusado aqui mesmo, com uma mensagem que diz o que
    fazer. Deixá-lo entrar numa tela onde toda ação falha depois seria pior: o
    sintoma viraria "não consigo salvar nada".
    """
    papel = (token.role or "").strip().lower()
    if papel in cert_installer.PAPEIS_COM_ALCANCE_TOTAL:
        return token

    # O PAPEL deixou de ser decidido aqui em 20/08. Antes era um literal
    # (`papel != "gestor"`), agora quem diz se o papel alcanca Carteiras e a
    # matriz de permissoes, declarada nas rotas com `require_modulo`. Esta
    # guarda cuida so do outro eixo: a LIDERANCA, que diz de quem.
    #
    # Separar os dois e o que torna a tela util. Com o literal, marcar
    # "Carteiras: Ver e editar" para outro papel nao adiantaria nada — a guarda
    # recusaria assim mesmo, e a tela estaria prometendo o que nao entrega.

    uid = _user_id_da_sessao(token)
    try:
        if uid and cert_installer.departamentos_que_lidera(uid):
            return token
    except cert_installer.AlcanceIndisponivel:
        # 503, e não 403: "não consegui verificar" não é "você não pode". Um
        # 403 aqui faria o líder acreditar que perdeu a permissão.
        raise HTTPException(
            status_code=503,
            detail="Não foi possível verificar seus departamentos. Tente de novo.",
        )
    raise HTTPException(status_code=403, detail=ERRO_SEM_ALCANCE)


def _exigir_alcance(token: auth.TokenData, alvo_id: str) -> None:
    """
    Barreira por PESSOA. `require_admin_ou_gestor` só diz que o ator pode montar
    carteiras; esta diz de quem.

    Sem ela, um líder do Fiscal montaria a carteira de alguém do Contábil
    apenas trocando o `user_id` na chamada — a tela filtra, mas a tela não é a
    barreira.
    """
    try:
        if cert_installer.pode_gerir(_user_id_da_sessao(token) or "", token.role or "", alvo_id):
            return
    except cert_installer.AlcanceIndisponivel:
        raise HTTPException(
            status_code=503,
            detail="Não foi possível verificar seu alcance. Tente de novo.",
        )
    raise HTTPException(
        status_code=403,
        detail=(
            "Esta pessoa não está em um departamento que você lidera — ou é "
            "Gestor, e a carteira de um Gestor só o administrador edita."
        ),
    )


def _papel_do_alvo(user_id: str) -> str:
    """O papel da pessoa cuja carteira se está editando. Falha fechada: sem
    conseguir ler, 503 — decidir "é Operador" no escuro trataria as Exceções
    de um Gestor como Atribuições."""
    # O mesmo banco das demais funções de carteira (`cert_installer._banco`),
    # para a tela e a barreira lerem a mesma fonte.
    sb = cert_installer._banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Banco não configurado")
    papel = _papel_da_conta(sb, user_id)
    if papel is None:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada.")
    if papel in permissoes.PAPEIS_TOTAIS:
        # A lista da tela já o esconde; isto fecha o link direto (?operador=).
        raise HTTPException(status_code=422, detail="Administrador tem alcance total e não tem carteira.")
    return papel


def _papel_da_conta(sb, user_id: str) -> Optional[str]:
    try:
        r = sb.table("users").select("role").eq("id", user_id).limit(1).execute()
        linhas = r.data or []
        return (linhas[0].get("role") or "").strip().lower() if linhas else None
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao ler o papel atual de %s", user_id)
        return None
