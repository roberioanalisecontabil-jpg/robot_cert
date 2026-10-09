"""Departamentos e Níveis de acesso — Frente 3, leva 5 (09/10/2026).

Saiu de `app/main.py` sem mudar comportamento: setores, líderes (quem é
Gestor deriva da liderança, ADR 0001) e a matriz de permissões por papel.
Tudo de administrador.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app import auth, nomes, papeis, permissoes
from app.sessao import conta_ativa, require_admin, require_auth

logger = logging.getLogger("app.main")
router = APIRouter()


# ══════════════════════════════════════════════════════════════════════════
# Departamentos
#
# O departamento recorta quem cada líder pode liberar. Criar, renomear e
# apagar setor é de ADMIN: quem define os setores define, por consequência, o
# alcance de cada líder — deixar isso com o próprio líder o deixaria ampliar o
# próprio alcance criando setores e se pondo neles.
# ══════════════════════════════════════════════════════════════════════════


class DepartamentoBody(BaseModel):
    nome: str


class DepartamentoLideresBody(BaseModel):
    lideres: List[str] = Field(default_factory=list)


def _nome_de_departamento(nome: str) -> str:
    limpo = (nome or "").strip()
    if not limpo:
        raise HTTPException(status_code=422, detail="O nome do departamento é obrigatório.")
    if len(limpo) > 80:
        raise HTTPException(status_code=422, detail="Nome muito longo (máximo 80 caracteres).")
    return limpo


# `require_admin`, e nao `require_admin_ou_gestor`: a unica tela que consome
# isto hoje e /usuarios, que ja e de admin. Quando o lider precisar ver os
# proprios setores (etapa 4), a rota certa e outra, escopada a ele -- esta
# devolve TODOS os departamentos, e alcance total nao e o do lider.
@router.get("/api/departamentos", dependencies=[Depends(require_admin)])
def listar_departamentos() -> List[dict]:
    """
    Departamentos com os gestores, quantas pessoas ativas têm e quantas inativas.

    A contagem vem junto porque é o que responde "posso apagar este?" sem um
    segundo clique — e apagar um setor com gente dentro deixa essas pessoas
    sem departamento, o que ninguém quer descobrir depois.
    """
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        return []
    try:
        deps = sb.table("departamento").select("id, nome, criado_em").execute().data or []
        lids = sb.table("departamento_lider").select("departamento_id, user_id").execute().data or []
        pessoas = sb.table("users").select("id, full_name, email, departamento_id, ativo, role").execute().data or []
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao listar departamentos")
        raise HTTPException(status_code=503, detail="Não foi possível listar os departamentos.")

    por_id = {str(u["id"]): u for u in pessoas}
    # `membros` conta so ATIVOS (decisao de 01/10/2026): a pergunta que a
    # coluna responde e "quem fica sem gestor se eu apagar", e inativo nao fica
    # sem nada. Os inativos vao a parte, para a tela mostrar se quiser.
    membros: Dict[str, int] = defaultdict(int)
    inativos: Dict[str, int] = defaultdict(int)
    for u in pessoas:
        if u.get("departamento_id"):
            if conta_ativa(u):
                membros[str(u["departamento_id"])] += 1
            else:
                inativos[str(u["departamento_id"])] += 1

    lideres: Dict[str, List[dict]] = defaultdict(list)
    for l in lids:
        u = por_id.get(str(l.get("user_id")))
        if not u:
            continue
        lideres[str(l.get("departamento_id"))].append({
            "id": str(u["id"]),
            "nome": u.get("full_name") or u.get("email"),
            "nome_exibicao": nomes.nome_pessoa(u.get("full_name") or u.get("email")),
            "ativo": bool(conta_ativa(u)),
        })

    saida = []
    for d in deps:
        did = str(d["id"])
        saida.append({
            "id": did,
            "nome": d.get("nome"),
            "criado_em": d.get("criado_em"),
            "lideres": sorted(lideres.get(did, []), key=lambda x: x["nome"] or ""),
            "membros": membros.get(did, 0),
            "inativos": inativos.get(did, 0),
        })
    return sorted(saida, key=lambda x: (x["nome"] or "").lower())


@router.post("/api/departamentos", dependencies=[Depends(require_admin)])
def criar_departamento(body: DepartamentoBody) -> dict:
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Sistema sem banco configurado.")
    nome = _nome_de_departamento(body.nome)
    try:
        r = sb.table("departamento").insert({"nome": nome}).execute()
    except Exception as e:  # noqa: BLE001
        # O índice único é sobre lower(btrim(nome)). A mensagem crua do
        # PostgREST diria "duplicate key value violates unique constraint", que
        # não ajuda quem está olhando um campo de texto.
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(status_code=409, detail=f"Já existe um departamento chamado {nome}.")
        logger.exception("Falha ao criar departamento")
        raise HTTPException(status_code=400, detail="Não foi possível criar o departamento.")
    return {"ok": True, "id": str((r.data or [{}])[0].get("id", ""))}


@router.put("/api/departamentos/{dep_id}", dependencies=[Depends(require_admin)])
def renomear_departamento(dep_id: str, body: DepartamentoBody) -> dict:
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Sistema sem banco configurado.")
    nome = _nome_de_departamento(body.nome)
    try:
        sb.table("departamento").update({"nome": nome}).eq("id", dep_id).execute()
    except Exception as e:  # noqa: BLE001
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(status_code=409, detail=f"Já existe um departamento chamado {nome}.")
        logger.exception("Falha ao renomear departamento %s", dep_id)
        raise HTTPException(status_code=400, detail="Não foi possível renomear o departamento.")
    return {"ok": True}


@router.delete("/api/departamentos/{dep_id}", dependencies=[Depends(require_admin)])
def apagar_departamento(dep_id: str) -> dict:
    """
    Apaga o departamento. As pessoas dele ficam SEM departamento, não são
    apagadas — é o `ON DELETE SET NULL` da migration, e a escolha é
    deliberada: perder o vínculo é corrigível na tela, perder as contas não.
    Até serem enquadradas, só o Administrador atribui a elas.

    As lideranças caem junto (`ON DELETE CASCADE`), e com elas o papel: quem
    só liderava este departamento deixa de ser Gestor (ADR 0001).
    """
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Sistema sem banco configurado.")
    try:
        lideres = {
            str(l.get("user_id"))
            for l in (sb.table("departamento_lider").select("user_id").eq("departamento_id", dep_id).execute().data or [])
            if l.get("user_id")
        }
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao ler os gestores do departamento %s", dep_id)
        raise HTTPException(status_code=503, detail="Não foi possível ler os gestores do departamento. Tente de novo.")
    try:
        # As lideranças saem explicitamente, e não só pelo CASCADE: é delas que
        # `papeis.rederivar` lê quem ainda lidera algo, e a leitura não pode
        # depender de o banco ter propagado a exclusão.
        sb.table("departamento_lider").delete().eq("departamento_id", dep_id).execute()
        sb.table("departamento").delete().eq("id", dep_id).execute()
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao apagar departamento %s", dep_id)
        raise HTTPException(status_code=400, detail="Não foi possível apagar o departamento.")
    return {"ok": True, "papeis": papeis.rederivar(sb, lideres)}


@router.put("/api/departamentos/{dep_id}/lideres", dependencies=[Depends(require_admin)])
def definir_lideres(dep_id: str, body: DepartamentoLideresBody) -> dict:
    """
    Substitui a lista de Gestores do departamento — e, com ela, o papel.

    Quem entra na lista vira Gestor; quem sai dela e não lidera mais nenhum
    departamento volta a Operador (`papeis.rederivar`, ADR 0001). O
    Administrador pode constar sem mudar de papel.

    Substitui em vez de somar porque a tela mostra a lista inteira: se o
    servidor só acrescentasse, tirar alguém exigiria uma rota a mais e a tela
    passaria a mentir sobre o que salvou.
    """
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Sistema sem banco configurado.")

    ids = [str(x).strip() for x in (body.lideres or []) if str(x).strip()]
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="A mesma pessoa aparece duas vezes na lista.")
    try:
        antes = {
            str(l.get("user_id"))
            for l in (sb.table("departamento_lider").select("user_id").eq("departamento_id", dep_id).execute().data or [])
            if l.get("user_id")
        }
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="Não foi possível ler os gestores atuais. Tente de novo.")

    if ids:
        try:
            achados = sb.table("users").select("id, role, ativo").execute().data or []
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=503, detail="Não foi possível validar os gestores agora.")
        por_id = {str(u["id"]): u for u in achados}
        for uid in ids:
            u = por_id.get(uid)
            if not u:
                raise HTTPException(status_code=422, detail="Um dos gestores escolhidos não existe.")
            if not conta_ativa(u):
                # Líder desativado não entra no portal, então o setor ficaria
                # com um responsável que não consegue liberar nada — a mesma
                # situação de não ter líder, mas parecendo resolvida.
                raise HTTPException(
                    status_code=422,
                    detail="Não é possível designar uma conta desativada como gestor.",
                )

    try:
        sb.table("departamento_lider").delete().eq("departamento_id", dep_id).execute()
        if ids:
            sb.table("departamento_lider").insert(
                [{"departamento_id": dep_id, "user_id": uid} for uid in ids]
            ).execute()
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao definir os gestores")
        raise HTTPException(status_code=400, detail="Não foi possível gravar os gestores.")
    return {"ok": True, "lideres": len(ids), "papeis": papeis.rederivar(sb, antes | set(ids))}


class PermissoesBody(BaseModel):
    matriz: Dict[str, Dict[str, str]]


# `require_admin`, e NAO `require_modulo("usuarios", editar)`. A diferenca e
# elevacao de privilegio: quem edita a matriz pode se dar qualquer acesso, entao
# amarrar isto ao proprio modulo Usuarios deixaria um gestor com escrita em
# Usuarios se autoconceder Configuracao e Instalador. Quem concede tem que estar
# acima do que concede.
@router.get("/api/permissoes/trilha", dependencies=[Depends(require_admin)])
def get_trilha_permissoes(limite: int = Query(30, ge=1, le=200)) -> dict:
    """Histórico de concessão e revogação de acesso.

    `require_admin` pelo mesmo motivo da matriz: a trilha diz quem alcança o
    quê e quem decidiu isso. Gatear pela própria matriz deixaria um gestor com
    escrita em Usuários lendo — e depois reescrevendo — o registro das próprias
    concessões.

    Nunca falha: `ler_trilha` devolve lista vazia quando não há de onde ler. A
    aba de Níveis de acesso não pode parar de funcionar porque o histórico
    ficou indisponível.
    """
    return {"itens": permissoes.ler_trilha(limite)}


@router.get("/api/permissoes", dependencies=[Depends(require_admin)])
def get_permissoes() -> dict:
    """A matriz para a tela: o que cada papel configuravel alcanca hoje."""
    try:
        return {
            "modulos": [
                {
                    "id": m,
                    # Os niveis que ESTE modulo aceita. Sem rota de escrita,
                    # `editar` nao e oferecido — seria configurar uma diferenca
                    # que nao existe.
                    "niveis": list(permissoes.niveis_de_modulo(m)),
                    # Modulo ainda nao ligado a rota nenhuma: a tela precisa
                    # dizer isso, senao oferece um controle que nao governa.
                    "governado": m in permissoes.MODULOS_GOVERNADOS,
                    # So o administrador: a celula aparece travada em "Nao
                    # entra", com o motivo, em vez de "ainda nao governado".
                    "so_admin": m in permissoes.MODULOS_SO_ADMIN,
                }
                for m in permissoes.MODULOS
            ],
            "niveis": list(permissoes.NIVEIS),
            "papeis": list(permissoes.PAPEIS_CONFIGURAVEIS),
            # Informativo: a tela mostra a coluna de admin travada, para
            # responder "cade o admin?" antes de alguem perguntar.
            "papeis_totais": list(permissoes.PAPEIS_TOTAIS),
            "matriz": {
                papel: permissoes.matriz_para_papel(papel)
                for papel in permissoes.PAPEIS_CONFIGURAVEIS
            },
        }
    except permissoes.PermissoesIndisponiveis as e:
        logger.error("Permissoes indisponiveis: %s", e)
        raise HTTPException(status_code=503, detail="Não foi possível ler as permissões. Tente de novo.")


# `require_auth`, e nao `require_admin`: cada um le a PROPRIA linha, e e o que o
# menu precisa para se montar. Nao expoe a matriz dos outros papeis — quem quer
# ver a matriz inteira usa `GET /api/permissoes`, que exige admin.
@router.get("/api/permissoes/minhas", dependencies=[Depends(require_auth)])
def get_minhas_permissoes(token: auth.TokenData = Depends(require_auth)) -> dict:
    """O que o papel de quem chama alcanca, modulo a modulo."""
    try:
        return {"modulos": permissoes.matriz_para_papel(token.role or "")}
    except permissoes.PermissoesIndisponiveis as e:
        # 503, e nao um dicionario vazio: vazio faria o menu sumir inteiro e
        # parecer que a pessoa perdeu todos os acessos. O front trata o erro
        # mantendo o menu que ja estava.
        logger.error("Permissoes indisponiveis: %s", e)
        raise HTTPException(status_code=503, detail="Não foi possível ler suas permissões. Tente de novo.")


@router.put("/api/permissoes", dependencies=[Depends(require_admin)])
def put_permissoes(body: PermissoesBody, token: auth.TokenData = Depends(require_auth)) -> dict:
    """Grava a matriz inteira. Ver `permissoes.gravar` para o porque de inteira."""
    try:
        salva = permissoes.gravar(body.matriz, alterado_por=(token.email or ""))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except permissoes.PermissoesIndisponiveis as e:
        logger.error("Permissoes indisponiveis ao gravar: %s", e)
        raise HTTPException(status_code=503, detail="Não foi possível gravar a matriz. Tente de novo.")
    return {"ok": True, "matriz": salva}
