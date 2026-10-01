"""
Papel derivado da liderança de Departamento (ADR 0001, 01/10/2026).

Só o Administrador é escolhido à mão. Quem lidera ao menos um Departamento é
Gestor; quem não lidera nenhum é Operador. Nomear alguém Gestor de um
Departamento o promove; tirar a última liderança o rebaixa. Um Administrador
pode liderar sem deixar de ser Administrador.

Derivar em vez de validar: dois campos (papel e liderança) com uma regra de
coerência entre eles admitem o estado inconsistente e só o barram na hora de
salvar. Com um campo decidindo o outro, o estado não existe.

Toda troca de papel esvazia a carteira (Atribuições e Exceções) e derruba as
sessões abertas da pessoa (`users.sessao_versao`): o papel viaja no token, e
um Operador recém-promovido continuaria a ver só a carteira antiga até o
token vencer — ou pior, um Gestor rebaixado continuaria a ver tudo.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Set

from app import cert_installer

logger = logging.getLogger(__name__)

ADMIN = "admin"
GESTOR = cert_installer.PAPEL_GESTOR
OPERADOR = cert_installer.PAPEL_OPERADOR

PAPEL_GESTOR_E_DERIVADO = (
    "O papel Gestor não se escolhe aqui: é de quem lidera um departamento. "
    "Em Usuários › Departamentos, designe a pessoa como Gestor do departamento."
)
DEPARTAMENTO_OBRIGATORIO = (
    "Escolha o departamento da pessoa. Sem ele, nenhum Gestor consegue "
    "atribuir clientes a ela."
)


def _quem_lidera(sb: Any, user_ids: Iterable[str]) -> Set[str]:
    ids = [str(u) for u in user_ids if u]
    if not ids:
        return set()
    r = sb.table("departamento_lider").select("user_id").in_("user_id", ids).execute()
    return {str(l.get("user_id")) for l in (r.data or []) if l.get("user_id")}


def lidera(sb: Any, user_id: str) -> bool:
    r = sb.table("departamento_lider").select("departamento_id").eq("user_id", str(user_id)).limit(1).execute()
    return bool(r.data)


def papel_efetivo(sb: Any, user_id: str, pedido: str) -> str:
    """O papel que de fato se grava quando alguém pede `pedido` para esta conta.

    Administrador fica Administrador. Qualquer outro pedido vira Gestor se a
    pessoa lidera um departamento, Operador se não — o pedido de "Operador"
    para quem lidera não rebaixa ninguém; o que rebaixa é tirar a liderança.
    """
    p = (pedido or OPERADOR).strip().lower()
    if p == ADMIN:
        return ADMIN
    return GESTOR if user_id and lidera(sb, user_id) else OPERADOR


def apos_troca_de_papel(sb: Any, user_id: str) -> Dict[str, Any]:
    """Esvazia a carteira e derruba as sessões. Nunca levanta: a conta já foi
    gravada com o papel novo; falhar aqui vira aviso na resposta e no log."""
    saida: Dict[str, Any] = {}
    try:
        saida.update(cert_installer.esvaziar_carteira(str(user_id)))
    except Exception as e:  # noqa: BLE001
        logger.exception("Papel de %s trocado, mas a carteira não foi esvaziada", user_id)
        saida["erro"] = "A conta foi salva, mas a carteira não pôde ser esvaziada. Confira em Carteiras."
    try:
        r = sb.table("users").select("sessao_versao").eq("id", str(user_id)).limit(1).execute()
        linhas = r.data or []
        atual = int((linhas[0].get("sessao_versao") if linhas else 0) or 0)
        sb.table("users").update({"sessao_versao": atual + 1}).eq("id", str(user_id)).execute()
        saida["sessoes_derrubadas"] = True
    except Exception:  # noqa: BLE001
        logger.exception("Papel de %s trocado, mas as sessões não foram derrubadas", user_id)
        saida["sessoes_derrubadas"] = False
    return saida


def rederivar(sb: Any, user_ids: Iterable[str]) -> List[Dict[str, Any]]:
    """Aplica a regra a estas pessoas e devolve o que mudou.

    Chamado depois de qualquer alteração em `departamento_lider`: definir os
    Gestores de um departamento, apagar um departamento. Nunca levanta pela
    pessoa individual — a liderança já foi gravada; o papel que não pôde ser
    ajustado vira linha com `erro` para a tela mostrar.
    """
    ids = sorted({str(u) for u in user_ids if u})
    if not ids:
        return []
    try:
        contas = sb.table("users").select("id, email, role").in_("id", ids).execute().data or []
        lideres = _quem_lidera(sb, ids)
    except Exception:  # noqa: BLE001
        logger.exception("Não foi possível rederivar os papéis de %s", ids)
        return [{"id": i, "erro": "Não foi possível conferir o papel desta pessoa."} for i in ids]

    mudancas: List[Dict[str, Any]] = []
    for u in contas:
        uid = str(u.get("id"))
        papel = (u.get("role") or "").strip().lower()
        if papel == ADMIN:
            continue
        if uid in lideres and papel != GESTOR:
            novo = GESTOR
        elif uid not in lideres and papel == GESTOR:
            novo = OPERADOR
        else:
            continue
        try:
            sb.table("users").update({"role": novo}).eq("id", uid).execute()
        except Exception:  # noqa: BLE001
            logger.exception("Falha ao gravar o papel %s em %s", novo, uid)
            mudancas.append({"id": uid, "email": u.get("email"), "erro": "Não foi possível gravar o papel novo."})
            continue
        mudancas.append({
            "id": uid,
            "email": u.get("email"),
            "de": papel,
            "para": novo,
            **apos_troca_de_papel(sb, uid),
        })
    return mudancas
