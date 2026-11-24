"""Registro de uso dos certificados (Frente C).

Diz QUE o certificado foi usado, QUANDO e POR QUEM. O programa e o título da
janela em primeiro plano vêm do anotador da estação (até 3 por evento) e só o
administrador os vê.
Os eventos 5061 chegam da bandeja com o contêiner da chave; o `uso_conteiner`
liga o contêiner ao certificado do acervo, e o uso que chega antes do mapa
espera com `fingerprint` nulo até o mapa chegar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from app import computadores as comp
from app.remocao import _cliente, do_acervo

# shortcut: -03:00 fixo; o Brasil não tem horário de verão desde 2019, trocar por
# zoneinfo se voltar.
BRASILIA = timezone(timedelta(hours=-3))
GUARDA = timedelta(days=5 * 365)
PENDENTE = timedelta(days=30)
LISTAGEM_CERTS = 3
LISTAGEM_INTERVALO = timedelta(seconds=2)


@dataclass
class Evento:
    record_id: int
    quando: datetime  # UTC
    sid: str
    usuario: str
    conteiner: str
    janelas: List[dict] = field(default_factory=list)  # quando, programa, titulo; índice = ordem


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


def _gravar_janelas(client, mid: str, uso_id, eventos: List[Evento]) -> None:
    # Também dos eventos já contados: o reenvio completa o que faltou, sem duplicar.
    # Chave por linha de uso: o record_id recomeça quando o log de Segurança é limpo.
    linhas = [{"uso_id": uso_id, "machine_id": mid, "record_id": e.record_id, "ordem": i,
               "evento_em": _iso(e.quando), "quando": _iso(j["quando"]),
               "programa": j["programa"], "titulo": j["titulo"]}
              for e in eventos for i, j in enumerate(e.janelas)]
    if linhas:
        client.table("uso_janela").upsert(
            linhas, on_conflict="uso_id,record_id,ordem", ignore_duplicates=True).execute()


def sem_listagens(eventos: List[Evento]) -> List[Evento]:
    """Tira as aberturas em rajada: a mesma pessoa abrindo LISTAGEM_CERTS ou mais
    chaves diferentes com no máximo LISTAGEM_INTERVALO entre uma e a seguinte.
    É o programa montando a lista de escolha (o SPED abre todas), não um uso; o
    5061 não diz qual foi assinada, então a rajada inteira sai. A abertura
    isolada (navegador, assinador comum) é a seleção e fica."""
    # shortcut: a rajada partida entre dois lotes da coleta (a cada 5 min) não é
    # vista inteira; juntar com o fim do lote anterior se isso aparecer.
    fora = set()
    por_sid: Dict[str, List[Evento]] = {}
    for e in eventos:
        por_sid.setdefault(e.sid, []).append(e)
    for evs in por_sid.values():
        evs = sorted(evs, key=lambda e: comp._quando(e.quando))
        bloco: List[Evento] = []
        for e in evs + [None]:
            if e is not None and bloco and comp._quando(e.quando) - comp._quando(bloco[-1].quando) <= LISTAGEM_INTERVALO:
                bloco.append(e)
                continue
            if len({b.conteiner for b in bloco}) >= LISTAGEM_CERTS:
                fora.update(id(b) for b in bloco)
            bloco = [e] if e is not None else []
    return [e for e in eventos if id(e) not in fora]


def registrar_usos(machine_id: str, eventos: List[Evento], auditoria: str, agora: datetime) -> int:
    mid = comp.mac(machine_id)
    client = _cliente()
    eventos = sem_listagens(eventos)
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
            _gravar_janelas(client, mid, atual["id"], evs)
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
        salva = client.table("uso_certificado").upsert(
            linha, on_conflict="machine_id,sid,conteiner,hora").execute().data
        _gravar_janelas(client, mid, salva[0]["id"], evs)
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
