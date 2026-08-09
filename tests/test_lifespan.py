"""Ciclo de vida do portal (startup/shutdown via lifespan).

`@app.on_event("startup")` foi migrado para um `asynccontextmanager` passado ao
construtor do FastAPI. A migração é silenciosa por natureza: `TestClient(app)`
sem gerenciador de contexto **não dispara** startup nenhum, então a suíte
inteira passava sem jamais executar o boot. Um erro no lifespan só apareceria
no deploy.

Estes testes entram no contexto de propósito, para que o boot seja exercitado.

Cobrem também o vazamento que existia antes: o `asyncio.create_task` do job de
alertas não tinha contrapartida no shutdown — a task ficava pendurada e, em
reinícios rápidos (o Procfile usa `--max-requests 500`, o worker recicla várias
vezes ao dia), um laço novo subia enquanto o anterior ainda dormia.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient


def test_boot_e_shutdown_completam(client: TestClient) -> None:
    """Entrar e sair do contexto executa lifespan inteiro sem levantar."""
    with client:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["ok"] is True


def test_shutdown_nao_pendura_no_job_de_alertas() -> None:
    """
    O shutdown tem de terminar sozinho, e rápido.

    O `finally` faz `cancel()` e depois espera a task com prazo de 5s. Um
    shutdown saudável é praticamente instantâneo: o cancel chega e o laço morre.

    O orçamento aqui (2s) é deliberadamente **menor** que o prazo de 5s da
    aplicação. Se fosse igual ou maior, o próprio limite do shutdown mascararia
    a falha: sem o `cancel()`, o encerramento gasta os 5s inteiros e termina
    "com sucesso" — foi exatamente o que aconteceu ao testar essa mutação com
    orçamento de 5s, que passou em 15s sem acusar nada. Com 2s, o cancel
    ausente vira falha.
    """
    from app.main import app as fastapi_app, lifespan

    async def sobe_e_desce() -> None:
        async with lifespan(fastapi_app):
            pass

    async def com_limite() -> None:
        await asyncio.wait_for(sobe_e_desce(), timeout=2)

    asyncio.run(com_limite())


def test_lifespan_tolera_filesystem_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    No Vercel o filesystem é read-only e o mkdir do boot falha. Isso não pode
    derrubar o portal — é o motivo do try/except OSError, e a migração para
    lifespan tinha de preservá-lo.
    """
    from pathlib import Path

    from app import config

    def mkdir_proibido(self, *a, **k):  # noqa: ANN001, ARG001
        raise OSError("read-only file system")

    monkeypatch.setattr(Path, "mkdir", mkdir_proibido)

    from app.main import app

    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 200
