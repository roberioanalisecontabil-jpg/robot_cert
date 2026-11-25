"""Wiki da API de leitura reorganizada (revisão editorial de 25/11/2026).

As tabelas de parâmetros saem do OpenAPI do portal (`wiki.parametros_api`):
toda consulta citada existe, todo parâmetro tem descrição e nenhum exemplo
de JSON leva reticências."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.rotas import wiki
from tests.test_seguranca_lote4 import ADMIN, _h, banco  # noqa: F401

PASTA = Path(__file__).resolve().parent.parent / "templates" / "wiki"
PAGINAS_API = [p.chave for p in wiki.PAGINAS if p.tema == "api"]


def test_tema_api_na_ordem_tutoriais_depois_referencia() -> None:
    assert PAGINAS_API == ["api-visao-geral", "api-chaves", "api-consultar", "api-integracoes",
                           "api-certificados", "api-consultas", "api-erros"]


@pytest.mark.parametrize("pagina", PAGINAS_API)
def test_pagina_abre_com_data_e_sem_parametro_sem_descricao(client, banco, pagina) -> None:
    r = client.get(f"/wiki-certguard?pagina={pagina}", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert "Atualizado em" in r.text
    assert "wiki-sem-descricao" not in r.text, pagina


def test_toda_consulta_da_tabela_existe_no_portal() -> None:
    for f in PASTA.glob("api-*.html"):
        for caminho in re.findall(r'parametros\("([^"]+)"', f.read_text(encoding="utf-8")):
            from app.main import app
            assert caminho in app.openapi()["paths"], (f.name, caminho)


def test_parametros_saem_do_openapi() -> None:
    p = {x["nome"]: x for x in wiki.parametros_api("/api/certificados/vencidos")}
    assert p["ordem"]["valores"] == "asc, desc" and p["ordem"]["padrao"] == "desc"
    assert p["por_pagina"]["tipo"] == "Inteiro" and p["por_pagina"]["valores"] == "De 1 a 2000"
    assert p["todas_filtradas"]["padrao"] == "false"
    d = {x["nome"]: x for x in wiki.parametros_api("/api/certificados/{fingerprint}/detalhes")}
    assert d["fingerprint"]["na_rota"] and d["fingerprint"]["obrigatorio"]
    assert d["fingerprint"]["valores"] == "64 caracteres hexadecimais"
    assert wiki.parametros_api("/api/nao-existe") == []
    assert all(x["nome"] != "X-API-Key" for x in wiki.parametros_api("/api/dashboard"))


def test_exemplos_json_sem_reticencias() -> None:
    for f in PASTA.glob("api-*.html"):
        for bloco in re.findall(r"<pre><code>(\{.*?)</code></pre>", f.read_text(encoding="utf-8"), re.S):
            assert "..." not in bloco and "…" not in bloco, f.name


def test_metodos_bloqueados_citam_patch() -> None:
    texto = (PASTA / "api-visao-geral.html").read_text(encoding="utf-8")
    for m in ("POST", "PUT", "PATCH", "DELETE"):
        assert f"<code>{m}</code>" in texto, m
