"""Vínculo pessoa–computador (ADR 0002, 07/10/2026).

A bandeja da estação entra com a conta DESTE portal; o dispositivo é a linha
de `agent_devices` (credencial por pessoa e máquina). Este módulo decide se
aquele dispositivo pode receber instalação:

* **Principal**: a máquina de trabalho, uma por pessoa e uma por máquina. É o
  que o Hardlyze mostra como responsável (`principais()`).
* **Empréstimo**: outra máquina, com prazo (fim do dia, 3 ou 7 dias).
* Todo vínculo novo nasce **pendente** até o administrador autorizar.
* **Um acesso por vez**: entrar numa máquina derruba as outras sessões da
  pessoa e a sessão de outra pessoa naquela máquina. O dono principal sempre
  retoma a própria máquina sem autorização; reconectar onde já está
  autorizado também não pede.

Sem banco não há vínculo: as funções levantam `SemBanco` e a rota decide.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TABELA = "computador_vinculo"
FILA = "fila_instalacao"
PRINCIPAL, EMPRESTIMO = "principal", "emprestimo"
PENDENTE, ATIVO, ENCERRADO, RECUSADO = "pendente", "ativo", "encerrado", "recusado"
AUTORIZADO = "autorizado"
# Alagoas não tem horário de verão: o "fim do dia" é às 23:59 de -03:00.
FUSO_DO_ESCRITORIO = timezone(timedelta(hours=-3))
PRAZOS = {"fim_do_dia": None, "3_dias": 3, "7_dias": 7}


class SemBanco(RuntimeError):
    pass


class VinculoInvalido(ValueError):
    pass


def _banco():
    from app.settings_state import _banco as _sb

    sb = _sb()
    if not sb:
        raise SemBanco("Vínculos de computador exigem banco configurado.")
    return sb


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat()


def mac(machine_id: Optional[str]) -> str:
    return (machine_id or "").strip().lower()


def _quando(v: Any) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def fim_do_prazo(prazo: str, agora: Optional[datetime] = None) -> datetime:
    if prazo not in PRAZOS:
        raise VinculoInvalido("Prazo do empréstimo: fim_do_dia, 3_dias ou 7_dias.")
    agora = agora or _agora()
    dias = PRAZOS[prazo]
    if dias is None:
        local = agora.astimezone(FUSO_DO_ESCRITORIO)
        return local.replace(hour=23, minute=59, second=59, microsecond=0).astimezone(timezone.utc)
    return agora + timedelta(days=dias)


# ── Leitura ──────────────────────────────────────────────────────────────

def _vinculos(**filtros: Any) -> List[Dict[str, Any]]:
    q = _banco().table(TABELA).select("*")
    for k, v in filtros.items():
        q = q.eq(k, v)
    return q.execute().data or []


def _encerrar(vinculo_id: Any, motivo: str, estado: str = ENCERRADO) -> None:
    _banco().table(TABELA).update({
        "estado": estado, "encerrado_em": _iso(_agora()), "motivo": motivo[:200],
    }).eq("id", vinculo_id).execute()


def _vigente(v: Dict[str, Any], agora: datetime) -> bool:
    """Ativo e, se empréstimo, dentro do prazo. Vencido é encerrado aqui."""
    if v.get("estado") != ATIVO:
        return False
    if v.get("tipo") == EMPRESTIMO:
        fim = _quando(v.get("expira_em"))
        if fim and fim <= agora:
            _encerrar(v["id"], "Prazo do empréstimo terminou.")
            return False
    return True


def vinculo_vigente(user_id: str, machine_id: str) -> Optional[Dict[str, Any]]:
    """O vínculo que autoriza esta pessoa nesta máquina agora, ou None."""
    agora = _agora()
    for v in _vinculos(user_id=str(user_id), machine_id=mac(machine_id)):
        if _vigente(v, agora):
            return v
    return None


def principal_da_pessoa(user_id: str) -> Optional[Dict[str, Any]]:
    r = [v for v in _vinculos(user_id=str(user_id), tipo=PRINCIPAL, estado=ATIVO)]
    return r[0] if r else None


def principal_da_maquina(machine_id: str) -> Optional[Dict[str, Any]]:
    r = [v for v in _vinculos(machine_id=mac(machine_id), tipo=PRINCIPAL, estado=ATIVO)]
    return r[0] if r else None


def pendente_do_par(user_id: str, machine_id: str) -> Optional[Dict[str, Any]]:
    r = _vinculos(user_id=str(user_id), machine_id=mac(machine_id), estado=PENDENTE)
    return r[0] if r else None


def situacao(user_id: str, machine_id: str) -> Dict[str, Any]:
    """`autorizado` (com o vínculo) ou `pendente`/`sem_pedido`. Sem efeito colateral."""
    v = vinculo_vigente(user_id, machine_id)
    if v:
        return {"autorizacao": AUTORIZADO, "tipo": v["tipo"], "expira_em": v.get("expira_em"), "vinculo_id": v["id"]}
    p = pendente_do_par(user_id, machine_id)
    if p:
        return {"autorizacao": PENDENTE, "tipo": p["tipo"], "vinculo_id": p["id"]}
    return {"autorizacao": "sem_pedido"}


def dispositivo_da_pessoa(user_id: str) -> Optional[Dict[str, Any]]:
    """A sessão ativa da pessoa (um acesso por vez): o dispositivo não revogado."""
    linhas = (_banco().table("agent_devices").select("*").eq("user_id", str(user_id)).execute().data or [])
    vivas = [l for l in linhas if not l.get("revogado_em")]
    vivas.sort(key=lambda l: str(l.get("visto_em") or l.get("criado_em") or ""), reverse=True)
    return vivas[0] if vivas else None


def dispositivo_da_maquina(machine_id: str) -> Optional[Dict[str, Any]]:
    """Quem está na bandeja desta máquina agora (uma pessoa por vez)."""
    linhas = (_banco().table("agent_devices").select("*").eq("machine_id", mac(machine_id)).execute().data or [])
    vivas = [l for l in linhas if not l.get("revogado_em")]
    vivas.sort(key=lambda l: str(l.get("visto_em") or l.get("criado_em") or ""), reverse=True)
    return vivas[0] if vivas else None


def computador_da_pessoa(user_id: str) -> Optional[Dict[str, Any]]:
    """O que o Início mostra: máquina da sessão ativa e se está autorizada."""
    d = dispositivo_da_pessoa(user_id)
    if not d:
        return None
    s = situacao(user_id, d["machine_id"])
    from app import agent_devices

    return {"machine_id": d["machine_id"], "nome": d.get("nome") or d["machine_id"],
            "vivo": agent_devices.esta_vivo(d), **s}


# ── A bandeja entrou ─────────────────────────────────────────────────────

def _revogar_dispositivos(filtro_user: Optional[str] = None, filtro_maquina: Optional[str] = None,
                          exceto_user: Optional[str] = None, exceto_maquina: Optional[str] = None) -> int:
    sb = _banco()
    q = sb.table("agent_devices").select("*")
    if filtro_user:
        q = q.eq("user_id", str(filtro_user))
    if filtro_maquina:
        q = q.eq("machine_id", mac(filtro_maquina))
    n = 0
    for d in q.execute().data or []:
        if d.get("revogado_em"):
            continue
        if exceto_user and str(d.get("user_id")) == str(exceto_user):
            continue
        if exceto_maquina and mac(d.get("machine_id")) == mac(exceto_maquina):
            continue
        sb.table("agent_devices").update({"revogado_em": _iso(_agora())}).eq("id", d["id"]).execute()
        n += 1
    return n


def ao_entrar(user_id: str, machine_id: str, nome: str = "") -> Dict[str, Any]:
    """Chamada depois de `agent_devices.registrar`: aplica as regras do ADR 0002."""
    uid, mid = str(user_id), mac(machine_id)
    # Um acesso por vez: a pessoa sai das outras máquinas...
    _revogar_dispositivos(filtro_user=uid, exceto_maquina=mid)
    for v in _vinculos(user_id=uid, tipo=EMPRESTIMO, estado=ATIVO):
        if mac(v["machine_id"]) != mid:
            _encerrar(v["id"], "A pessoa entrou em outra máquina.")
    # ...e a máquina fica só com ela.
    _revogar_dispositivos(filtro_maquina=mid, exceto_user=uid)
    for v in _vinculos(machine_id=mid, tipo=EMPRESTIMO, estado=ATIVO):
        if str(v["user_id"]) != uid:
            _encerrar(v["id"], "Outra pessoa entrou nesta máquina.")

    s = situacao(uid, mid)
    if s["autorizacao"] in (AUTORIZADO, PENDENTE):
        return s
    # Pedido novo: sugere principal se a pessoa não tem nenhuma, senão empréstimo.
    tipo = EMPRESTIMO if principal_da_pessoa(uid) else PRINCIPAL
    _banco().table(TABELA).insert({
        "user_id": uid, "machine_id": mid, "nome": (nome or mid)[:120], "tipo": tipo,
        "estado": PENDENTE, "pedido_em": _iso(_agora()), "decidido_por": "", "motivo": "",
    }).execute()
    logger.info("Computador: pedido de vínculo %s para %s em %s", tipo, uid, mid)
    return situacao(uid, mid)


# ── Administrador ────────────────────────────────────────────────────────

def _um(vinculo_id: Any) -> Dict[str, Any]:
    r = _banco().table(TABELA).select("*").eq("id", vinculo_id).limit(1).execute().data or []
    if not r:
        raise LookupError("Vínculo não encontrado.")
    return r[0]


def autorizar(vinculo_id: Any, tipo: str, por: str, prazo: Optional[str] = None) -> Dict[str, Any]:
    v = _um(vinculo_id)
    if v["estado"] != PENDENTE:
        raise VinculoInvalido("Só pedido pendente pode ser autorizado.")
    agora = _agora()
    campos: Dict[str, Any] = {"estado": ATIVO, "tipo": tipo, "decidido_por": por, "decidido_em": _iso(agora)}
    if tipo == PRINCIPAL:
        # Troca de verdade: a principal antiga da pessoa e a da máquina vão ao histórico.
        for antigo in (principal_da_pessoa(v["user_id"]), principal_da_maquina(v["machine_id"])):
            if antigo and antigo["id"] != v["id"]:
                _encerrar(antigo["id"], "Substituída por nova máquina principal.")
        campos["expira_em"] = None
    elif tipo == EMPRESTIMO:
        campos["expira_em"] = _iso(fim_do_prazo(prazo or "fim_do_dia", agora))
    else:
        raise VinculoInvalido("Tipo: principal ou emprestimo.")
    _banco().table(TABELA).update(campos).eq("id", v["id"]).execute()
    return _um(v["id"])


def recusar(vinculo_id: Any, por: str) -> Dict[str, Any]:
    v = _um(vinculo_id)
    if v["estado"] != PENDENTE:
        raise VinculoInvalido("Só pedido pendente pode ser recusado.")
    _banco().table(TABELA).update({"estado": RECUSADO, "decidido_por": por, "decidido_em": _iso(_agora()),
                                    "encerrado_em": _iso(_agora())}).eq("id", v["id"]).execute()
    _revogar_dispositivos(filtro_user=v["user_id"], filtro_maquina=v["machine_id"])
    return _um(v["id"])


def desvincular(vinculo_id: Any, por: str) -> Dict[str, Any]:
    v = _um(vinculo_id)
    if v["estado"] != ATIVO:
        raise VinculoInvalido("Só vínculo ativo pode ser desvinculado.")
    _encerrar(v["id"], f"Desvinculado por {por}.")
    _revogar_dispositivos(filtro_user=v["user_id"], filtro_maquina=v["machine_id"])
    return _um(v["id"])


def sair_de_tudo(user_id: str, motivo: str) -> int:
    """Senha redefinida ou conta desativada: derruba as sessões da bandeja."""
    try:
        n = _revogar_dispositivos(filtro_user=str(user_id))
    except Exception:  # noqa: BLE001 — nunca impede a troca de senha nem a desativação
        logger.warning("Não foi possível encerrar as sessões da bandeja de %s", user_id, exc_info=True)
        return 0
    if n:
        logger.info("Computador: %d sessão(ões) da bandeja encerrada(s) para %s (%s)", n, user_id, motivo)
    return n


def listar() -> List[Dict[str, Any]]:
    """Todos os vínculos (o recorte por papel é da rota), com vigência calculada."""
    agora = _agora()
    linhas = _banco().table(TABELA).select("*").execute().data or []
    for v in linhas:
        if v.get("estado") == ATIVO and not _vigente(v, agora):
            v["estado"], v["motivo"] = ENCERRADO, "Prazo do empréstimo terminou."
    linhas.sort(key=lambda v: (v.get("estado") != PENDENTE, str(v.get("pedido_em") or "")), reverse=False)
    return linhas


def principais() -> List[Dict[str, Any]]:
    """Para o Hardlyze: máquina → dono principal."""
    return [{"machine_id": v["machine_id"], "user_id": str(v["user_id"]), "desde": v.get("decidido_em")}
            for v in _vinculos(tipo=PRINCIPAL, estado=ATIVO)]


def importar(logins: List[Dict[str, Any]], usuarios_por_email: Dict[str, str]) -> Dict[str, int]:
    """Transição (ADR 0002): os logins de pessoa do Hardlyze viram PEDIDOS
    pendentes aqui, para o administrador só confirmar.

    `logins`: [{email, machine_id, nome, visto_em}] do Hardlyze.
    `usuarios_por_email`: e-mail → user_id das contas ATIVAS deste portal.
    Sugere principal para a máquina vista por último de cada pessoa sem
    principal; as outras viram empréstimo. Par que já tem vínculo pendente
    ou ativo é pulado. Não cria sessão de bandeja: autorizado o pedido, a
    pessoa ainda entra na bandeja 2.1.0 e cai direto em "autorizado".
    """
    criados = pulados = sem_conta = 0
    por_pessoa: Dict[str, List[Dict[str, Any]]] = {}
    for l in logins:
        uid = usuarios_por_email.get((l.get("email") or "").strip().lower())
        if not uid:
            sem_conta += 1
            continue
        if not mac(l.get("machine_id")):
            continue
        por_pessoa.setdefault(uid, []).append(l)
    for uid, lista in por_pessoa.items():
        lista.sort(key=lambda l: str(l.get("visto_em") or ""), reverse=True)
        tem_principal = principal_da_pessoa(uid) is not None or any(
            v["tipo"] == PRINCIPAL for v in _vinculos(user_id=uid, estado=PENDENTE))
        for l in lista:
            mid = mac(l["machine_id"])
            if vinculo_vigente(uid, mid) or pendente_do_par(uid, mid):
                pulados += 1
                continue
            tipo = EMPRESTIMO if tem_principal else PRINCIPAL
            tem_principal = True
            _banco().table(TABELA).insert({
                "user_id": uid, "machine_id": mid, "nome": (l.get("nome") or mid)[:120], "tipo": tipo,
                "estado": PENDENTE, "pedido_em": _iso(_agora()), "decidido_por": "",
                "motivo": "Importado do Hardlyze (login da bandeja antiga).",
            }).execute()
            criados += 1
    return {"criados": criados, "pulados": pulados, "sem_conta": sem_conta}


# ── Fila de instalação ───────────────────────────────────────────────────

def enfileirar(machine_id: str, token_raw: str, token_id: str, expira_em: datetime) -> None:
    from app.smtp_service import encrypt_password

    _banco().table(FILA).insert({
        "machine_id": mac(machine_id), "token_id": str(token_id), "token_cifrado": encrypt_password(token_raw),
        "criado_em": _iso(_agora()), "expira_em": _iso(expira_em), "entregue_em": None,
    }).execute()


def entregar(machine_id: str) -> List[str]:
    """Tokens pendentes desta máquina, uma vez só (marca entregue)."""
    from app.smtp_service import decrypt_password

    sb = _banco()
    agora = _agora()
    saida: List[str] = []
    for linha in sb.table(FILA).select("*").eq("machine_id", mac(machine_id)).execute().data or []:
        if linha.get("entregue_em"):
            continue
        fim = _quando(linha.get("expira_em"))
        if fim and fim <= agora:
            continue
        sb.table(FILA).update({"entregue_em": _iso(agora)}).eq("id", linha["id"]).execute()
        token = decrypt_password(linha["token_cifrado"])
        if token:
            saida.append(token)
    return saida
