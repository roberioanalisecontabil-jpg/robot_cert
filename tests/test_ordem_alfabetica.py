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


# ══════════════════════════════════════════════════════════════════════════
# Ordenação escolhida pelo cabeçalho (21/08/2026)
# ══════════════════════════════════════════════════════════════════════════
#
# A mesma invariante do topo deste arquivo, agora para a ordem que a pessoa
# escolhe: precisa acontecer no SERVIDOR e ANTES da paginação. E uma segunda,
# que só aparece quando a ordem deixa de ser sempre a mesma: **o que falta vai
# para o fim, nas duas direções.** Ordenar por vencimento com os sem-data no
# topo daria uma primeira página inteira de arquivos ilegíveis — o oposto do
# útil, que é exatamente o que `chave_alfabetica` já evitava para o nome.

def _com_data(nome: str, emissao: str, venc: str, doc: str = "1", status: str = "ok") -> dict:
    return {
        "nome": nome, "display_name": nome, "status": status,
        "not_before": emissao, "not_after": venc,
        "documento_numero": doc, "documento_formatado": doc,
        "file_name": nome + ".pfx", "fingerprint_sha256": "fp-" + nome,
    }


@pytest.fixture
def acervo_para_ordenar(monkeypatch: pytest.MonkeyPatch):
    itens = [
        _com_data("CARLOS", "2026-03-01T00:00:00Z", "2027-03-01T00:00:00Z", "300"),
        _com_data("ana", "2026-01-01T00:00:00Z", "2027-05-01T00:00:00Z", "100"),
        _com_data("Bruno", "2026-02-01T00:00:00Z", "2027-01-01T00:00:00Z", "200"),
        _com_data("SEM DATA", "", "", "400"),
    ]
    monkeypatch.setattr(m, "_list_certificados_payload", lambda *a, **k: {"itens": list(itens)})
    return itens


def _admin() -> dict:
    from app import auth
    return {"Authorization": f"Bearer {auth.create_access_token({'sub': 'admin@x.com', 'role': 'admin'})}"}


def _nomes_da_url(client, url: str) -> list:
    r = client.get(url, headers=_admin())
    assert r.status_code == 200, r.text
    return [it["nome"] for it in r.json()["itens"]]


def test_sem_o_parametro_a_ordem_de_fabrica_continua(client, acervo_para_ordenar) -> None:
    """Alfabética por titular, sem acento e sem caixa — o que já valia."""
    assert _nomes_da_url(client, "/api/certificados?pagina=1&por_pagina=50") == [
        "ana", "Bruno", "CARLOS", "SEM DATA"
    ]


def test_ordena_por_vencimento_nas_duas_direcoes(client, acervo_para_ordenar) -> None:
    asc = _nomes_da_url(client, "/api/certificados?pagina=1&por_pagina=50&ordenar=vencimento&direcao=asc")
    des = _nomes_da_url(client, "/api/certificados?pagina=1&por_pagina=50&ordenar=vencimento&direcao=desc")
    assert asc[:3] == ["Bruno", "CARLOS", "ana"]
    assert des[:3] == ["ana", "CARLOS", "Bruno"]


def test_o_que_falta_vai_para_o_fim_nas_duas_direcoes(client, acervo_para_ordenar) -> None:
    """A invariante que decide se a primeira página é útil."""
    for direcao in ("asc", "desc"):
        nomes = _nomes_da_url(
            client, f"/api/certificados?pagina=1&por_pagina=50&ordenar=vencimento&direcao={direcao}"
        )
        assert nomes[-1] == "SEM DATA", (direcao, nomes)


def test_ordena_antes_de_paginar_tambem_na_ordem_escolhida(client, acervo_para_ordenar) -> None:
    """O teste que mais importa, repetido para a ordem escolhida.

    Com 2 por página e ordem decrescente de vencimento, a PRIMEIRA página tem
    de trazer os dois maiores. Ordenar depois de paginar traria os dois
    primeiros da ordem alfabética, ordenados entre si — e a lista pareceria
    certa página a página.
    """
    p1 = _nomes_da_url(client, "/api/certificados?pagina=1&por_pagina=2&ordenar=vencimento&direcao=desc")
    assert p1 == ["ana", "CARLOS"], p1


def test_coluna_desconhecida_nao_derruba_a_tela(client, acervo_para_ordenar) -> None:
    """Recusar daria uma tabela que simplesmente não carrega, e o sintoma —
    tela vazia — não diria que o problema é o parâmetro."""
    assert _nomes_da_url(client, "/api/certificados?pagina=1&por_pagina=50&ordenar=inventada") == [
        "ana", "Bruno", "CARLOS", "SEM DATA"
    ]


def test_ordenar_compoe_com_filtro_e_exclusao(client, monkeypatch) -> None:
    """As três decisões são independentes e precisam continuar sendo."""
    itens = [
        _com_data("ZEBRA", "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z", "1"),
        _com_data("ALFA", "2026-01-01T00:00:00Z", "2027-02-01T00:00:00Z", "2"),
        _com_data("ILEGIVEL", "", "", "3", status="fora_do_padrao"),
    ]
    monkeypatch.setattr(m, "_list_certificados_payload", lambda *a, **k: {"itens": list(itens)})
    nomes = _nomes_da_url(
        client,
        "/api/certificados?pagina=1&por_pagina=50&ordenar=nome&direcao=desc&ocultar_ilegiveis=true",
    )
    assert nomes == ["ZEBRA", "ALFA"]
