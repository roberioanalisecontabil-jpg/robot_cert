"""Rotas da atualização automática do Certguard Análise (1.1.0, 20/10/2026).

Abertas, sem credencial, como o ADR 0003 decidiu: quem pede é a tarefa
agendada da estação, que roda como SYSTEM e não tem a conta da pessoa. A
garantia é a assinatura do pacote, conferida na estação; o portal só entrega
o que está publicado em `app/atualizacao_estacao.py`. O teto por endereço
segura quem quiser usar o download de 30 MB para encher o link.

O evento é a exceção: ele leva a chave da máquina, e só a máquina com a chave
fixada no portal (ADR 0002) registra o que aconteceu.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import atualizacao_estacao as publicacao
from app import computadores, taxa
from app.sessao import _ip_do_cliente

logger = logging.getLogger("app.main")
router = APIRouter()

# Uma estação confere na partida, a cada 6 h e no fim de cada instalação.
_TETO_MANIFESTO = (60, 600)
_TETO_ARQUIVO = (20, 3600)
_TETO_EVENTO = (20, 600)


def _limitar(request: Request, prefixo: str, teto: tuple) -> None:
    if not taxa.permitir(f"{prefixo}:{_ip_do_cliente(request)}", *teto):
        raise HTTPException(status_code=429, detail="Muitas requisições. Aguarde alguns minutos.")


@router.get("/api/estacao/atualizacao")
def manifesto_vigente(request: Request):
    """O pacote assinado vigente; 204 quando ainda não há versão publicada."""
    _limitar(request, "atualizacao", _TETO_MANIFESTO)
    try:
        pacote = publicacao.vigente()
    except publicacao.PublicacaoIlegivel:
        raise HTTPException(status_code=503, detail="Versão publicada ilegível.") from None
    if pacote is None:
        return Response(status_code=204)
    return pacote


@router.get("/api/estacao/atualizacao/arquivo/{sha256}")
def instalador_vigente(sha256: str, request: Request):
    """O instalador do pacote vigente, pelo hash que a estação já conferiu.
    Só o vigente: a cópia para voltar atrás fica na própria estação."""
    _limitar(request, "atualizacao-arquivo", _TETO_ARQUIVO)
    try:
        caminho = publicacao.instalador(sha256)
    except publicacao.PublicacaoIlegivel:
        raise HTTPException(status_code=503, detail="Instalador publicado não encontrado.") from None
    if caminho is None:
        raise HTTPException(status_code=404, detail="Esse instalador não é o vigente.")
    return FileResponse(str(caminho), media_type="application/octet-stream", filename=caminho.name)


class EventoDeAtualizacao(BaseModel):
    machine_id: str = Field(min_length=1, max_length=64)
    chave: str = Field(min_length=1, max_length=256)
    de: str = Field(default="", max_length=20)
    para: str = Field(min_length=1, max_length=20)
    resultado: str = Field(pattern=r"^(atualizou|voltou|falhou)$")
    detalhe: str = Field(default="", max_length=500)


_TEXTO = {
    "atualizou": "Certguard Análise atualizado de {de} para {para}.",
    "voltou": "Certguard Análise voltou para {para}: a versão {de} não subiu. {detalhe}",
    "falhou": "Atualização do Certguard Análise para {para} falhou: {detalhe}",
}


@router.post("/api/estacao/atualizacao/evento")
def evento_de_atualizacao(corpo: EventoDeAtualizacao, request: Request) -> dict:
    """A estação conta o que aconteceu; fica no log do portal."""
    _limitar(request, "atualizacao-evento", _TETO_EVENTO)
    if not computadores._maquina_provada(corpo.machine_id, computadores.hash_da_chave(corpo.chave)):
        raise HTTPException(status_code=403, detail="Chave da máquina não confere.")
    texto = _TEXTO[corpo.resultado].format(de=corpo.de or "?", para=corpo.para, detalhe=corpo.detalhe).strip()
    nivel = logger.info if corpo.resultado == "atualizou" else logger.warning
    nivel("Computador %s: %s", computadores.mac(corpo.machine_id), texto)
    return {"ok": True}
