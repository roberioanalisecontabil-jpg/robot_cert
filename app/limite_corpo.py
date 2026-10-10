"""Teto de tamanho do corpo da requisição, ANTES de qualquer rota ler (auditoria
de 10/10/2026, fastapi-get_request_handler:request-body-buffered-before-auth-
without-size-cap).

O FastAPI lê o corpo inteiro — `request.json()` para modelos, `request.form()`
para upload — antes de resolver as dependências. Autenticação, rate limit e o
`max_length` do Pydantic só rodam DEPOIS: um anônimo mandava um JSON de
gigabytes para /api/login e o processo inteiro (um worker) segurava tudo na
memória; num upload, o Starlette gravava o arquivo em disco temporário antes do
401. Nem o uvicorn nem o Caddyfile versionado tinham teto (lote 5 deixara isso
para o Caddy, que nunca recebeu o `request_body max_size`).

Middleware ASGI puro, o primeiro a ver a requisição: recusa pelo
`Content-Length` declarado e, sem ele (chunked), conta os bytes que passam e
para no teto. Os tetos são por rota: pequeno por padrão, maior só onde o
agente ou as importações precisam.
"""

from __future__ import annotations

import json
from typing import Awaitable, Callable, Dict, Tuple

MB = 1024 * 1024

# Prefixo do caminho → teto em bytes. O mais específico que casar vence.
TETOS: Tuple[Tuple[str, int], ...] = (
    ("/api/ingest", 64 * MB),                     # inventário do agente (até 20.000 itens)
    ("/api/agent/entrada", 16 * MB),              # relatório da Entrada (até 5.000 eventos)
    ("/api/cert-installer/upload-pfx", 4 * MB),   # PFX em base64 (1,5 MB) + campos
    ("/api/users/import", 6 * MB),                # planilha (5 MB, ver comum.LIMITE_UPLOAD_BYTES)
    ("/api/carteira/importar", 6 * MB),
)
TETO_PADRAO = 1 * MB

DETALHE = "Requisição grande demais."


def teto_para(caminho: str) -> int:
    melhor, tam = TETO_PADRAO, -1
    for prefixo, teto in TETOS:
        if caminho.startswith(prefixo) and len(prefixo) > tam:
            melhor, tam = teto, len(prefixo)
    return melhor


class _Excedeu(Exception):
    pass


class LimiteDeCorpo:
    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Dict, receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        teto = teto_para(scope.get("path") or "")
        cabecalhos = dict(scope.get("headers") or [])
        declarado = cabecalhos.get(b"content-length")
        if declarado is not None:
            try:
                if int(declarado) > teto:
                    await _recusar(send)
                    return
            except ValueError:
                await _recusar(send, 400, "Content-Length inválido.")
                return

        recebido = 0
        respondeu = False

        async def receive_contado():
            nonlocal recebido
            msg = await receive()
            if msg.get("type") == "http.request":
                recebido += len(msg.get("body") or b"")
                if recebido > teto:
                    raise _Excedeu()
            return msg

        async def send_marcado(msg):
            nonlocal respondeu
            if msg.get("type") == "http.response.start":
                respondeu = True
            await send(msg)

        try:
            await self.app(scope, receive_contado, send_marcado)
        except _Excedeu:
            if not respondeu:
                await _recusar(send)


async def _recusar(send: Callable, status: int = 413, detalhe: str = DETALHE) -> None:
    corpo = json.dumps({"detail": detalhe}).encode("utf-8")
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(corpo)).encode())]})
    await send({"type": "http.response.body", "body": corpo})
