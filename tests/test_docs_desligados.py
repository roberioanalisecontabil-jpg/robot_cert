"""
A documentação da API não é pública — a menos que alguém a ligue.

Achado do levantamento de superfície anônima de 01/09/2026: `/openapi.json`
descrevia as ~97 rotas (nomes, parâmetros, shapes de payload) para qualquer
visitante sem sessão — o único dado que uma visita anônima levava do portal.
O INVENT já desligava por padrão (ENABLE_DOCS); isto é a paridade.

O modo de falha que este teste evita é silencioso: ninguém consulta /docs em
produção de propósito, então a exposição voltaria sem sintoma nenhum se a
instanciação do FastAPI perdesse os `docs_url=None` numa refatoração.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import pytest


@pytest.mark.parametrize("rota", ["/docs", "/redoc", "/openapi.json"])
def test_docs_desligados_por_padrao(client: TestClient, rota: str) -> None:
    assert client.get(rota).status_code == 404


def test_a_variavel_e_a_mesma_do_invent() -> None:
    """Os dois portais se configuram pela MESMA variável (ENABLE_DOCS), de
    propósito: quem implanta um já sabe operar o outro. Divergir o nome aqui
    quebraria essa expectativa sem aviso."""
    import inspect

    from app import config

    fonte = inspect.getsource(config)
    assert 'ENABLE_DOCS' in fonte
