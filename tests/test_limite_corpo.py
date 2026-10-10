"""Teto de corpo antes de qualquer leitura (auditoria de 10/10/2026).

O que se prova: o portal recusa um corpo grande ANTES de lê-lo inteiro, inclusive
sem autenticação e sem `Content-Length` (envio em pedaços), e as rotas que
precisam de corpo grande continuam aceitando o tamanho delas.
"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app import limite_corpo


def test_login_com_corpo_grande_e_recusado_antes_da_autenticacao(client: TestClient) -> None:
    gordo = '{"email":"a@x.com","password":"' + "x" * (2 * limite_corpo.MB) + '"}'
    r = client.post("/api/login", content=gordo, headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_upload_anonimo_grande_e_recusado_antes_de_ir_para_o_disco(client: TestClient) -> None:
    r = client.post("/api/users/import", files={"file": ("u.csv", b"a" * (7 * limite_corpo.MB), "text/csv")})
    assert r.status_code == 413


def test_tetos_por_rota() -> None:
    assert limite_corpo.teto_para("/api/login") == limite_corpo.TETO_PADRAO
    assert limite_corpo.teto_para("/api/ingest") == 64 * limite_corpo.MB
    assert limite_corpo.teto_para("/api/carteira/importar") == 6 * limite_corpo.MB


def _rodar(corpo_em_pedacos, caminho="/api/login"):
    """Chama o middleware direto, sem Content-Length, contando quanto o app leu."""
    lido = {"bytes": 0}
    enviados = []

    async def app(scope, receive, send):
        while True:
            msg = await receive()
            lido["bytes"] += len(msg.get("body") or b"")
            if not msg.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    pedacos = list(corpo_em_pedacos)

    async def receive():
        corpo = pedacos.pop(0) if pedacos else b""
        return {"type": "http.request", "body": corpo, "more_body": bool(pedacos)}

    async def send(msg):
        enviados.append(msg)

    scope = {"type": "http", "path": caminho, "headers": []}
    asyncio.run(limite_corpo.LimiteDeCorpo(app)(scope, receive, send))
    return lido["bytes"], enviados[0]["status"]


def test_envio_em_pedacos_sem_content_length_para_no_teto() -> None:
    pedaco = b"x" * (256 * 1024)
    lido, status = _rodar([pedaco] * 40)  # 10 MB declarados em lugar nenhum
    assert status == 413
    assert lido <= limite_corpo.TETO_PADRAO + len(pedaco)


def test_corpo_dentro_do_teto_passa() -> None:
    lido, status = _rodar([b"{}"])
    assert status == 200 and lido == 2
