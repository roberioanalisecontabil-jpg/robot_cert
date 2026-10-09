"""Utilidades das rotas — Frente 3, leva 4 (09/10/2026).

Saíram de `app/main.py` sem mudar comportamento, porque mais de um router
usa: leitura de planilha com teto (lote 5 da auditoria: o que não tem teto
derruba o portal inteiro, que roda num worker só), a mensagem de erro que
manda ao log, e a máscara de CNPJ/CPF.
"""

from __future__ import annotations

import unicodedata
from typing import Any, List

from fastapi import HTTPException, Request

from app.cert_scanner import formatar_cnpj_cpf


def _norm_header(v: str) -> str:
    s = unicodedata.normalize("NFD", str(v or "").strip().lower())
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s


LIMITE_UPLOAD_BYTES = 5 * 1024 * 1024


MAX_LINHAS_IMPORT = 2000


ERRO_UPLOAD_GRANDE = f"Arquivo muito grande (limite de {LIMITE_UPLOAD_BYTES // (1024 * 1024)} MB)."


ERRO_LINHAS_DEMAIS = f"Planilha com mais de {MAX_LINHAS_IMPORT} linhas. Divida o arquivo."


async def _ler_upload_limitado(request: Request, file: Any) -> bytes:
    """Lê o arquivo enviado sem receber mais do que o teto (achado #11).

    Antes: `await file.read()` bufferizava o corpo inteiro (o Starlette manda
    para disco) e só DEPOIS o tamanho era conferido — um POST de 2 GB era
    recebido até o fim para responder 413. Aqui a recusa vem em dois tempos:
    pelo `Content-Length` declarado, antes de ler qualquer byte; e de novo
    durante a leitura, porque o cabeçalho é declaração do cliente.
    """
    try:
        declarado = int(request.headers.get("content-length") or 0)
    except ValueError:
        declarado = 0
    if declarado > LIMITE_UPLOAD_BYTES + 4096:
        raise HTTPException(status_code=413, detail=ERRO_UPLOAD_GRANDE)
    partes: List[bytes] = []
    total = 0
    while True:
        pedaco = await file.read(64 * 1024)
        if not pedaco:
            break
        total += len(pedaco)
        if total > LIMITE_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=ERRO_UPLOAD_GRANDE)
        partes.append(pedaco)
    return b"".join(partes)


ERRO_INTERNO_VEJA_LOG = "A operação falhou no servidor. Veja o log para o detalhe."


def _documento_formatado(digitos: str) -> str:
    """CNPJ (14) ou CPF (11) com máscara; qualquer outro tamanho volta como veio."""
    tipo = "cnpj" if len(digitos or "") == 14 else "cpf" if len(digitos or "") == 11 else None
    return formatar_cnpj_cpf(digitos, tipo) or (digitos or "")
