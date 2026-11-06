"""Histórico: "Entrou em" / "Saiu em" (06/11/2026).

`cert_history.primeira_data_registrada` já dizia quando a chave apareceu; faltava
dizer quando ela SAIU das pastas. A coluna `ausente_desde` (migration
20261106120000) nasce NULL = "está nas pastas" e o ingest a mantém:

  - chave que veio no inventário: `ausente_desde = NULL` (inclui a que voltou);
  - chave desta máquina, presente, que NÃO veio: `ausente_desde = now()`.

Proteções (nada é marcado, só um WARNING com contagens): inventário vazio,
inventário com menos de 50% das chaves presentes (pasta de rede caída) e chave
que outra máquina reportou por último.

Escritos antes da implementação.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.settings_state as ss
from tests import test_seguranca_lote1 as lote1
from tests.test_notificacoes_novos import _item
from tests.test_seguranca_lote1 import _Fake
from tests.test_seguranca_lote4 import ADMIN, DOC_A, DOC_B, FISCAL_OP, _h  # noqa: F401
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401

RAIZ = Path(__file__).resolve().parents[1]
SQL = RAIZ / "supabase" / "migrations" / "20261106120000_cert_history_ausente_desde.sql"
HTML = (RAIZ / "templates" / "historico.html").read_text(encoding="utf-8")
AGORA = datetime.now(timezone.utc).isoformat()
SCAN = "2026-11-06T10:00:00+00:00"


# ══════════════════════════════════════════════════════════════════════════
# 1. Migration
# ══════════════════════════════════════════════════════════════════════════


def _sql_sem_comentarios() -> str:
    return "\n".join(l for l in SQL.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("--"))


def test_migration_cria_a_coluna_sem_default_e_idempotente() -> None:
    sql = _sql_sem_comentarios()
    assert re.search(r"ADD COLUMN IF NOT EXISTS ausente_desde\s+timestamptz", sql)
    assert not re.search(r"ADD COLUMN (?!IF NOT EXISTS)", sql)
    # DEFAULT preencheria as linhas antigas (lição de 20260930140000).
    assert "DEFAULT" not in sql.upper()


def test_migration_backfill_so_preenche_o_que_esta_vazio_e_velho() -> None:
    sql = " ".join(_sql_sem_comentarios().split())
    assert "UPDATE cert_history SET ausente_desde = ultima_data_registrada" in sql
    assert "ausente_desde IS NULL" in sql, "nunca sobrescrever um ausente_desde que já tem valor"
    assert "ultima_data_registrada < now() - interval '2 days'" in sql


def test_migration_tem_o_bloco_volta_comentado() -> None:
    texto = SQL.read_text(encoding="utf-8")
    volta = texto[texto.index("-- Volta"):]
    assert "-- ALTER TABLE cert_history DROP COLUMN IF EXISTS ausente_desde" in volta


# ══════════════════════════════════════════════════════════════════════════
# 2. Ingest
# ══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def historico(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake({"cert_history": []})
    monkeypatch.setattr(ss, "_banco", lambda: fake)
    return fake


def _linha(it: dict, maquina: str = "srv", ausente: str | None = None) -> dict:
    return {"arquivo_chave": it["arquivo_chave"], "nome_publico": it["nome_publico"],
            "machine_id": maquina, "ausente_desde": ausente}


def _ausencias(fake: _Fake) -> dict:
    return {r["arquivo_chave"]: r.get("ausente_desde") for r in fake.tabelas["cert_history"]}


def test_quem_nao_veio_e_marcado_como_ausente(historico: _Fake) -> None:
    a, b, c = _item("ALFA", "fp-a"), _item("BETA", "fp-b"), _item("GAMA", "fp-c")
    historico.tabelas["cert_history"] += [_linha(a), _linha(b), _linha(c)]

    ss.upsert_cert_history("srv", SCAN, [a, b])

    aus = _ausencias(historico)
    assert aus[a["arquivo_chave"]] is None and aus[b["arquivo_chave"]] is None
    assert aus[c["arquivo_chave"]], "GAMA não veio e devia ficar ausente"


def test_quem_voltou_e_limpo(historico: _Fake) -> None:
    a, b = _item("ALFA", "fp-a"), _item("BETA", "fp-b")
    historico.tabelas["cert_history"] += [_linha(a, ausente="2026-11-01T10:00:00+00:00"), _linha(b)]

    ss.upsert_cert_history("srv", SCAN, [a, b])

    assert _ausencias(historico)[a["arquivo_chave"]] is None


def test_ja_ausente_nao_tem_a_data_sobrescrita(historico: _Fake) -> None:
    a, b = _item("ALFA", "fp-a"), _item("BETA", "fp-b")
    historico.tabelas["cert_history"] += [_linha(a), _linha(b, ausente="2026-11-01T10:00:00+00:00")]

    ss.upsert_cert_history("srv", SCAN, [a])

    assert _ausencias(historico)[b["arquivo_chave"]] == "2026-11-01T10:00:00+00:00"


def test_inventario_vazio_nao_marca_ninguem(historico: _Fake, caplog: pytest.LogCaptureFixture) -> None:
    a = _item("ALFA", "fp-a")
    historico.tabelas["cert_history"].append(_linha(a))

    with caplog.at_level("WARNING"):
        ss.upsert_cert_history("srv", SCAN, [])

    assert _ausencias(historico)[a["arquivo_chave"]] is None
    assert any(r.levelname == "WARNING" and "vazio" in r.getMessage() for r in caplog.records)


def test_inventario_com_menos_da_metade_nao_marca_ninguem(historico: _Fake, caplog: pytest.LogCaptureFixture) -> None:
    itens = [_item(f"C{i}", f"fp-{i}") for i in range(5)]
    historico.tabelas["cert_history"] += [_linha(it) for it in itens]

    with caplog.at_level("WARNING"):
        ss.upsert_cert_history("srv", SCAN, itens[:2])

    assert all(v is None for v in _ausencias(historico).values())
    avisos = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("2" in a and "5" in a for a in avisos), avisos
    # Só contagens no log: o nome do arquivo pode ter a senha.
    assert not any("C0" in a or "C4" in a or "pfx" in a for a in avisos)


def test_outra_maquina_nao_marca_as_chaves_desta(historico: _Fake) -> None:
    a, b = _item("ALFA", "fp-a"), _item("BETA", "fp-b")
    c, d = _item("GAMA", "fp-c"), _item("DELTA", "fp-d")
    historico.tabelas["cert_history"] += [_linha(a), _linha(b), _linha(c, "outra"), _linha(d, "outra")]

    ss.upsert_cert_history("srv", SCAN, [a, b])

    aus = _ausencias(historico)
    assert aus[c["arquivo_chave"]] is None and aus[d["arquivo_chave"]] is None


def test_falha_ao_marcar_nao_derruba_o_ingest(historico: _Fake, monkeypatch: pytest.MonkeyPatch,
                                              caplog: pytest.LogCaptureFixture) -> None:
    a, novo = _item("ALFA", "fp-a"), _item("BETA", "fp-b")
    historico.tabelas["cert_history"].append(_linha(a))

    def _quebra(self, *_a, **_k):
        raise RuntimeError("coluna ausente_desde não existe")

    monkeypatch.setattr(lote1._Query, "update", _quebra)
    with caplog.at_level("WARNING"):
        novos = ss.upsert_cert_history("srv", SCAN, [a, novo])

    assert [n["arquivo_chave"] for n in novos] == [novo["arquivo_chave"]]
    assert len(historico.tabelas["cert_history"]) == 2


# ══════════════════════════════════════════════════════════════════════════
# 3. API
# ══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def banco(banco_base: _Fake) -> _Fake:
    banco_base.tabelas["carteira_excecao"] = []
    return banco_base


def _hist(chave: str, nome: str, doc: str, ausente: str | None) -> dict:
    return {"arquivo_chave": chave * 64, "nome_publico": f"{nome}_{doc}", "nome": nome, "documento": doc,
            "status_ultimo": "ok", "vencimento_certificado": None, "ultima_data_registrada": AGORA,
            "primeira_data_registrada": "2026-10-01T10:00:00+00:00", "ausente_desde": ausente}


@pytest.fixture
def com_saida(banco: _Fake) -> _Fake:
    banco.tabelas["cert_history"] += [
        _hist("1", "ALFA", DOC_A, None),
        _hist("2", "BETA", DOC_B, "2026-11-05T10:00:00+00:00"),
    ]
    return banco


def test_api_devolve_entrou_e_saiu(client: TestClient, com_saida: _Fake) -> None:
    r = client.get("/api/certificados/historico?pagina=1&por_pagina=20", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    por_nome = {i["nome"]: i for i in r.json()["itens"]}
    assert por_nome["ALFA"]["primeira_data_registrada"] == "2026-10-01T10:00:00+00:00"
    assert por_nome["ALFA"]["ausente_desde"] is None
    assert por_nome["BETA"]["ausente_desde"] == "2026-11-05T10:00:00+00:00"


@pytest.mark.parametrize("extra", ["pagina=1&por_pagina=20", "todas_filtradas=true"])
def test_api_filtra_por_situacao(client: TestClient, com_saida: _Fake, extra: str) -> None:
    def nomes(situacao: str) -> list:
        r = client.get(f"/api/certificados/historico?{extra}&situacao={situacao}", headers=_h(*ADMIN))
        assert r.status_code == 200, r.text
        return sorted(i["nome"] for i in r.json()["itens"])

    assert nomes("todos") == ["ALFA", "BETA"]
    assert nomes("nas_pastas") == ["ALFA"]
    assert nomes("sairam") == ["BETA"]


def test_api_situacao_respeita_o_alcance(client: TestClient, com_saida: _Fake) -> None:
    r = client.get("/api/certificados/historico?situacao=nas_pastas", headers=_h(*FISCAL_OP))
    assert r.status_code == 200, r.text
    assert [i["nome"] for i in r.json()["itens"]] == ["ALFA"]
    r = client.get("/api/certificados/historico?situacao=sairam", headers=_h(*FISCAL_OP))
    assert r.json()["itens"] == []


def test_api_situacao_desconhecida_e_422(client: TestClient, com_saida: _Fake) -> None:
    r = client.get("/api/certificados/historico?situacao=qualquer", headers=_h(*ADMIN))
    assert r.status_code == 422


# ══════════════════════════════════════════════════════════════════════════
# 4. Tela
# ══════════════════════════════════════════════════════════════════════════


def test_tela_tem_as_colunas_novas_e_sem_ultima_verificacao() -> None:
    thead = HTML[HTML.index("<thead"):HTML.index("</thead>")]
    cabecalhos = re.findall(r">([^<>]+)</th>", thead)
    assert [c.strip() for c in cabecalhos] == ["Nome", "CNPJ / CPF", "Entrou em", "Saiu em", "Vencimento", "Status"]
    assert "antes de 30/09" in HTML


def test_tela_tem_o_select_de_situacao() -> None:
    assert 'id="filtro-situacao-hist"' in HTML
    for valor, rotulo in (("todos", "Todos"), ("nas_pastas", "Nas pastas"), ("sairam", "Saíram")):
        assert f'<option value="{valor}">{rotulo}</option>' in HTML
    assert "situacao:" in HTML, "a situação vai na consulta"


def test_exportacao_mantem_ultima_verificacao_e_ganha_as_novas() -> None:
    for trecho in ("Última data verificada", "Entrou em", "Saiu em"):
        assert HTML.count(trecho) >= 2, trecho
