"""Registro de uso dos certificados (Frente C).

Diz QUE o certificado foi usado, QUANDO e POR QUEM; nunca qual programa ou site.
Os eventos 5061 chegam da bandeja com o contêiner da chave; o `uso_conteiner`
liga o contêiner ao certificado do acervo, e o uso que chega antes do mapa
espera com `fingerprint` nulo até o mapa chegar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from app import computadores as comp
from app.remocao import _cliente, do_acervo

# shortcut: -03:00 fixo; o Brasil não tem horário de verão desde 2019, trocar por
# zoneinfo se voltar.
BRASILIA = timezone(timedelta(hours=-3))
GUARDA = timedelta(days=5 * 365)
PENDENTE = timedelta(days=30)


@dataclass
class Evento:
    record_id: int
    quando: datetime  # UTC
    sid: str
    usuario: str
    conteiner: str


def hora_de(quando: datetime) -> datetime:
    return comp._quando(quando).astimezone(BRASILIA).replace(minute=0, second=0, microsecond=0)


def _iso(d: datetime) -> str:
    # Tudo gravado em UTC: o mesmo formato em toda coluna mantém a comparação coerente.
    return comp._quando(d).astimezone(timezone.utc).isoformat()


def registrar_mapa(machine_id: str, sid: str, usuario_windows: str, user_id: Optional[str],
                   conteineres: Dict[str, str], agora: datetime) -> int:
    """Grava contêiner -> fingerprint e resolve o uso que estava esperando por ele."""
    if not conteineres:
        return 0
    mid = comp.mac(machine_id)
    client = _cliente()
    client.table("uso_conteiner").upsert(
        [{"machine_id": mid, "sid": sid, "conteiner": c, "fingerprint": str(fp).strip().lower(),
          "usuario_windows": usuario_windows, "user_id": user_id, "atualizado_em": _iso(agora)}
         for c, fp in conteineres.items()],
        on_conflict="machine_id,sid,conteiner").execute()
    # shortcut: lê e grava sem trava; há um coletor por máquina (protegido pelo
    # `_unica()` da tarefa). Trocar por trava de linha se isso mudar.
    pendentes = [r for r in (client.table("uso_certificado").select("*")
                             .eq("machine_id", mid).eq("sid", sid).is_("fingerprint", "null")
                             .execute().data or []) if r.get("conteiner") in conteineres]
    if not pendentes:
        return 0
    fps = {c: str(conteineres[c]).strip().lower() for c in {r["conteiner"] for r in pendentes}}
    acervo = do_acervo(list(fps.values()))
    resolvidas = 0
    for r in pendentes:
        fp = fps[r["conteiner"]]
        if fp not in acervo:
            continue
        client.table("uso_certificado").update(
            {"fingerprint": fp, "documento": acervo[fp], "user_id": user_id}).eq("id", r["id"]).execute()
        resolvidas += 1
    return resolvidas


def registrar_usos(machine_id: str, eventos: List[Evento], auditoria: str, agora: datetime) -> int:
    mid = comp.mac(machine_id)
    client = _cliente()
    grupos: Dict[Tuple[str, str, datetime], List[Evento]] = {}
    for e in eventos:
        grupos.setdefault((e.sid, e.conteiner, hora_de(e.quando)), []).append(e)

    mapa: Dict[Tuple[str, str], dict] = {}
    for sid in {k[0] for k in grupos}:
        for r in (client.table("uso_conteiner").select("*").eq("machine_id", mid).eq("sid", sid)
                  .execute().data or []):
            mapa[(sid, r["conteiner"])] = r
    acervo = do_acervo([r["fingerprint"] for r in mapa.values()])

    gravadas = 0
    for (sid, conteiner, hora), evs in grupos.items():
        # shortcut: lê e grava sem trava (um coletor por máquina), como em registrar_mapa.
        atual = (client.table("uso_certificado").select("*").eq("machine_id", mid).eq("sid", sid)
                 .eq("conteiner", conteiner).eq("hora", _iso(hora)).execute().data or [None])[0]
        # O reenvio de um lote não soma de novo: só conta o que passa do último record_id.
        novos = [e for e in evs if atual is None or e.record_id > int(atual["ultimo_record"])]
        if not novos:
            continue
        quando = [comp._quando(e.quando) for e in novos]
        primeiro, ultimo = min(quando), max(quando)
        if atual:
            primeiro = min(primeiro, comp._quando(atual["primeiro_em"]))
            ultimo = max(ultimo, comp._quando(atual["ultimo_em"]))
        linha = {
            "machine_id": mid, "sid": sid, "usuario_windows": novos[-1].usuario,
            "conteiner": conteiner, "hora": _iso(hora),
            "primeiro_em": _iso(primeiro), "ultimo_em": _iso(ultimo),
            "quantidade": (int(atual["quantidade"]) if atual else 0) + len(novos),
            "ultimo_record": max(e.record_id for e in novos), "recebido_em": _iso(agora),
        }
        if atual:
            linha["ultimo_record"] = max(linha["ultimo_record"], int(atual["ultimo_record"]))
        else:
            m = mapa.get((sid, conteiner)) or {}
            fp = str(m.get("fingerprint") or "").strip().lower()
            # Fora do acervo conta como não resolvido: fica pendente e some em 30 dias.
            if fp in acervo:
                linha.update(fingerprint=fp, documento=acervo[fp], user_id=m.get("user_id"))
            else:
                linha.update(fingerprint=None, documento=None, user_id=None)
        client.table("uso_certificado").upsert(
            linha, on_conflict="machine_id,sid,conteiner,hora").execute()
        gravadas += 1

    client.table("uso_coleta").upsert(
        {"machine_id": mid, "ultima_em": _iso(agora), "auditoria": auditoria},
        on_conflict="machine_id").execute()
    return gravadas


def limpar(agora: datetime) -> None:
    client = _cliente()
    client.table("uso_certificado").delete().lt("hora", _iso(agora - GUARDA)).execute()
    (client.table("uso_certificado").delete().is_("fingerprint", "null")
     .lt("recebido_em", _iso(agora - PENDENTE)).execute())
