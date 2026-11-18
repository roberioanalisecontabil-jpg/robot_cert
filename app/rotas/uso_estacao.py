"""Coleta do uso dos certificados pela bandeja (Frente C).

A bandeja manda os eventos 5061 do log de Segurança, com a chave da máquina
fixada no portal (ADR 0002). A gravação e a regra de resolução moram em
`app/uso.py`.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Annotated, List, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BeforeValidator, BaseModel, Field, StringConstraints

from app import computadores, uso
from app.rotas.atualizacao import _limitar

logger = logging.getLogger("app.main")
router = APIRouter()

_TETO_USO = (30, 600)
_LIMPEZA_A_CADA = 24 * 3600
_FORA = "Não foi possível gravar agora."
# shortcut: marcador em memória do processo; reiniciar o serviço roda a limpeza de novo, o que é inofensivo.
_ultima_limpeza = 0.0


def _sem_nul(v):
    # Postgres `text` recusa NUL e psycopg não codifica surrogate solto. Roda ANTES da
    # validação: o pydantic recusa o surrogate e a resposta 422 estoura ao ecoá-lo.
    if not isinstance(v, str):
        return v
    return v.encode("utf-16", "surrogatepass").decode("utf-16", "replace").replace("\x00", "")


class JanelaDeUso(BaseModel):
    quando: datetime
    programa: Annotated[str, BeforeValidator(_sem_nul)] = Field(max_length=64)
    titulo: Annotated[str, BeforeValidator(_sem_nul)] = Field(max_length=300)


class EventoDeUso(BaseModel):
    record_id: int = Field(ge=0)
    quando: datetime
    sid: str = Field(min_length=1, max_length=184)
    usuario: Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=256)]
    conteiner: str = Field(min_length=1, max_length=512)
    janelas: List[JanelaDeUso] = Field(default_factory=list, max_length=3)


class LoteDeUso(BaseModel):
    machine_id: str = Field(min_length=1, max_length=64)
    chave: str = Field(min_length=1, max_length=256)
    auditoria: Literal["ligada", "desligada", "desconhecida"]
    eventos: List[EventoDeUso] = Field(max_length=2000)


def _limpar_se_for_hora(agora: datetime) -> None:
    global _ultima_limpeza
    if time.monotonic() - _ultima_limpeza < _LIMPEZA_A_CADA and _ultima_limpeza:
        return
    _ultima_limpeza = time.monotonic()
    try:
        uso.limpar(agora)
    except Exception:  # noqa: BLE001
        logger.exception("Uso: limpeza falhou")


@router.post("/api/estacao/uso")
def registrar(corpo: LoteDeUso, request: Request) -> dict:
    _limitar(request, "uso", _TETO_USO)
    try:
        provada = computadores._maquina_provada(corpo.machine_id, computadores.hash_da_chave(corpo.chave))
    except Exception:  # noqa: BLE001
        logger.exception("Uso: chave de %s ilegível", computadores.mac(corpo.machine_id))
        raise HTTPException(status_code=503, detail=_FORA) from None
    if not provada:
        raise HTTPException(status_code=403, detail="Chave da máquina não confere.")
    agora = datetime.now(timezone.utc)
    try:
        gravadas = uso.registrar_usos(
            corpo.machine_id,
            [uso.Evento(e.record_id, e.quando, e.sid, e.usuario, e.conteiner,
                        [j.model_dump() for j in e.janelas]) for e in corpo.eventos],
            corpo.auditoria, agora)
    except Exception:  # noqa: BLE001
        logger.exception("Uso: gravação de %s falhou", computadores.mac(corpo.machine_id))
        raise HTTPException(status_code=503, detail=_FORA) from None
    _limpar_se_for_hora(agora)
    return {"ok": True, "gravadas": gravadas}
