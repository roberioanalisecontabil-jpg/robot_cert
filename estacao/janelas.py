"""Registro local das janelas em primeiro plano (Frente C: programa e página).

O anotador (SYSTEM) acrescenta uma linha JSON por troca de janela, num arquivo
por SID e por dia UTC; o coletor lê e escolhe as janelas de cada evento 5061.
Cada `anotar` abre, grava e fecha: uma escrita cortada estraga só a última linha.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List

logger = logging.getLogger("estacao.janelas")

PASTA = "janelas"
GUARDA = timedelta(hours=48)
JANELA_ANTES = timedelta(seconds=30)
MAX_ANTERIORES = 2
MAX_TITULO = 300
MAX_PROGRAMA = 64


def _utc(quando: datetime) -> datetime:
    return quando.astimezone(timezone.utc)


def arquivo(raiz: str, sid: str, quando: datetime) -> str:
    return os.path.join(raiz, PASTA, sid, _utc(quando).strftime("%Y%m%d") + ".jsonl")


def anotar(raiz: str, sid: str, quando: datetime, programa: str, titulo: str) -> None:
    caminho = arquivo(raiz, sid, quando)
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    linha = {"t": _utc(quando).isoformat(), "p": programa[:MAX_PROGRAMA], "j": titulo[:MAX_TITULO]}
    with open(caminho, "a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")


def podar(raiz: str, agora: datetime) -> int:
    """Apaga os arquivos de dias que terminaram antes de `agora - GUARDA`."""
    corte = _utc(agora) - GUARDA
    base = os.path.join(raiz, PASTA)
    apagados = 0
    try:
        sids = os.listdir(base)
    except OSError:
        return 0
    for sid in sids:
        pasta = os.path.join(base, sid)
        try:
            nomes = os.listdir(pasta)
        except OSError:
            continue
        for nome in nomes:
            try:
                dia = datetime.strptime(nome, "%Y%m%d.jsonl").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if dia + timedelta(days=1) <= corte:
                try:
                    os.remove(os.path.join(pasta, nome))
                    apagados += 1
                except OSError:
                    logger.warning("nao apagou %s", nome)
    return apagados


def ler(raiz: str, sid: str, ate: datetime) -> List[dict]:
    """Linhas do dia de `ate` e dos 2 anteriores, ordenadas por `t`."""
    linhas: List[dict] = []
    for dias in (2, 1, 0):
        try:
            with open(arquivo(raiz, sid, ate - timedelta(days=dias)), encoding="utf-8") as f:
                for texto in f:
                    try:
                        l = json.loads(texto)
                        if isinstance(l, dict) and isinstance(l["t"], str):
                            datetime.fromisoformat(l["t"])
                            linhas.append(l)
                    except (ValueError, KeyError):
                        continue  # linha cortada no meio de uma escrita
        except OSError:
            continue
    linhas.sort(key=lambda l: datetime.fromisoformat(l["t"]))
    return linhas


def janelas_do_evento(linhas: List[dict], quando: datetime) -> List[dict]:
    """A vigente em `quando` mais até 2 anteriores que ainda estavam na tela nos 30 s antes (fim >= quando-30s), da mais nova à mais velha."""
    q = _utc(quando)
    antes = sorted(
        ((datetime.fromisoformat(l["t"]), l) for l in linhas if datetime.fromisoformat(l["t"]) <= q),
        key=lambda x: x[0],
    )
    if not antes:
        return []
    # o fim de cada anterior é o `t` da linha seguinte
    anteriores = [antes[i] for i in range(len(antes) - 1) if antes[i + 1][0] >= q - JANELA_ANTES]
    saida = [antes[-1]] + anteriores[::-1]
    return [
        {"quando": t.astimezone(timezone.utc).isoformat(), "programa": l.get("p", ""), "titulo": l.get("j", "")}
        for t, l in saida[: 1 + MAX_ANTERIORES]
    ]
