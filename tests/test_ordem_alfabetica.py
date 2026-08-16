"""Ordem alfabética da listagem de certificados.

Até 16/08/2026 a lista não era ordenada por ninguém. Saía na ordem em que o
agente varre o disco, e ele percorre **pasta por pasta**: o resultado eram
vários blocos alfabéticos emendados — um por subpasta, mais os vencidos no fim.
Na base real do ANALISESRV eram **6 blocos em 560 itens**, o que de longe
parece ordem alfabética e de perto não é: os primeiros nomes saíam certos e
depois a lista "voltava para o A".

**O teste que mais importa aqui é o `test_ordena_antes_de_paginar`.** A tabela
pagina no servidor. Ordenar no navegador ordenaria só os itens da página
visível, e a lista *pareceria* certa enquanto continuasse errada entre páginas
— que é pior que estar visivelmente errada, porque ninguém procura o defeito.
"""

from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

import app.main as m


def _item(nome: str, **extra: Any) -> Dict[str, Any]:
    base = {
        "nome": nome,
        "display_name": nome,
        "file_name": f"{nome}.pfx",
        "fingerprint_sha256": (nome or "x").ljust(64, "0")[:64],
        "status": "ok",
        "documento_numero": "00000000000000",
        "not_after": "2027-01-01T00:00:00Z",
    }
    base.update(extra)
    return base


@pytest.fixture
def inventario(monkeypatch: pytest.MonkeyPatch) -> List[Dict[str, Any]]:
    """
    Reproduz a forma real: dois blocos alfabéticos emendados, como o agente
    entrega ao varrer duas subpastas.
    """
    itens = [
        _item("ANALISE ASSESSORIA"),
        _item("MERCADO CENTRAL"),
        _item("ZELIA MARIA"),
        # segunda subpasta — recomeça no A
        _item("ACLECIO EVANGELISTA"),
        _item("Ágata Comercio"),      # acento e caixa mista
        _item("BOI PRIME"),
    ]
    monkeypatch.setattr(m, "get_latest_snapshot", lambda: {
        "machine_id": "SRV", "scanned_at": "2026-08-16T10:00:00Z",
        "source_folder": "F:/x", "expired_folder": "F:/y", "items": itens,
    })
    return itens


def _nomes(client: TestClient, **params: Any) -> List[str]:
    q = "&".join(f"{k}={v}" for k, v in params.items())
    r = client.get(f"/api/certificados?fonte=auto{'&' + q if q else ''}")
    assert r.status_code == 200, r.text
    return [i["nome"] for i in r.json()["itens"]]


# ──────────────────────────────────────────────────────────────────────────
# 1. A ordem
# ──────────────────────────────────────────────────────────────────────────

def test_lista_sai_em_ordem_alfabetica(client: TestClient, inventario) -> None:
    assert _nomes(client) == [
        "ACLECIO EVANGELISTA",
        "Ágata Comercio",
        "ANALISE ASSESSORIA",
        "BOI PRIME",
        "MERCADO CENTRAL",
        "ZELIA MARIA",
    ]


def test_acento_nao_manda_o_nome_para_o_fim(client: TestClient, inventario) -> None:
    """
    "Ágata" tem de cair entre ACLECIO e ANALISE. Comparando bytes crus, todo
    nome acentuado iria parar depois do Z — e num acervo brasileiro isso é
    metade da lista fora de lugar.
    """
    nomes = _nomes(client)
    assert nomes.index("Ágata Comercio") == nomes.index("ACLECIO EVANGELISTA") + 1


def test_caixa_nao_afeta_a_ordem(client: TestClient, inventario) -> None:
    """Maiúsculas antes de minúsculas agruparia por como o arquivo foi salvo."""
    nomes = _nomes(client)
    assert nomes.index("Ágata Comercio") < nomes.index("BOI PRIME")


def test_sem_nome_vai_para_o_fim(client: TestClient, monkeypatch) -> None:
    """
    Ordenar por string vazia jogaria os ilegíveis para o topo, e a primeira
    página da lista seria justamente o que o robô não conseguiu ler.
    """
    itens = [
        {"nome": "", "display_name": "", "file_name": "", "status": "erro"},
        _item("ZELIA MARIA"),
        _item("ANALISE ASSESSORIA"),
    ]
    monkeypatch.setattr(m, "get_latest_snapshot", lambda: {
        "machine_id": "SRV", "scanned_at": "2026-08-16T10:00:00Z",
        "source_folder": "", "expired_folder": "", "items": itens,
    })
    assert _nomes(client) == ["ANALISE ASSESSORIA", "ZELIA MARIA", ""]


# ──────────────────────────────────────────────────────────────────────────
# 2. Antes da paginação — o ponto que faz a diferença
# ──────────────────────────────────────────────────────────────────────────

def test_ordena_antes_de_paginar(client: TestClient, inventario) -> None:
    """
    Cada página continua de onde a anterior parou.

    Ordenar depois de paginar (ou no navegador) daria páginas internamente
    ordenadas e desconexas entre si: a página 2 recomeçaria no A. A lista
    *pareceria* certa em cada tela e continuaria errada no conjunto — e é assim
    que o defeito sobrevive, porque ninguém o procura.
    """
    p1 = _nomes(client, pagina=1, por_pagina=3)
    p2 = _nomes(client, pagina=2, por_pagina=3)

    assert p1 == ["ACLECIO EVANGELISTA", "Ágata Comercio", "ANALISE ASSESSORIA"]
    assert p2 == ["BOI PRIME", "MERCADO CENTRAL", "ZELIA MARIA"]
    assert p1 + p2 == sorted(p1 + p2, key=lambda n: m.chave_alfabetica({"nome": n}))


def test_ordem_sobrevive_ao_filtro(client: TestClient, inventario) -> None:
    """Filtrar não pode reembaralhar o que sobrou."""
    nomes = _nomes(client, pagina=1, por_pagina=50, busca="a")
    assert nomes == sorted(nomes, key=lambda n: m.chave_alfabetica({"nome": n}))


def test_exportacao_tambem_sai_ordenada(client: TestClient, inventario) -> None:
    """
    A exportação usa o mesmo payload. Um PDF com a lista embaralhada é pior que
    a tela: some com o contexto e ninguém tem como conferir.
    """
    nomes = _nomes(client, todas_filtradas="true")
    assert nomes == sorted(nomes, key=lambda n: m.chave_alfabetica({"nome": n}))


# ──────────────────────────────────────────────────────────────────────────
# 3. A chave, isolada
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("item,esperado", [
    ({"nome": "ACME"}, (0, "acme")),
    ({"nome": "Ágata"}, (0, "agata")),
    ({"nome": "", "display_name": "Fallback"}, (0, "fallback")),
    ({"nome": "", "display_name": "", "file_name": "arquivo.pfx"}, (0, "arquivo.pfx")),
    ({"nome": "   "}, (1, "")),
    ({}, (1, "")),
])
def test_chave_alfabetica(item: dict, esperado: tuple) -> None:
    assert m.chave_alfabetica(item) == esperado
