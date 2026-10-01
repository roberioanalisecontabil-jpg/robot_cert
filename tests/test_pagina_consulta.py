"""
Revisão das páginas de consulta (01/10/2026) — Dashboard, Histórico, Vencidos
e Duplicidades. Decisões D1 a D3 em docs/revisao-paginas-2026-10.md:

  D1  Vencido é o Cliente cujo certificado vigente venceu, no inventário
      atual: Vencidos e o card do Dashboard contam assim.
  D2  Dashboard é só do Administrador; sai da matriz.
  D3  Histórico continua por arquivo, com a coluna Status.

Defeitos: Duplicidades recortado pelo Alcance; carteira vazia nomeada no
Histórico e em Vencidos; busca por dígitos no Histórico; `atualizado_em`;
403 com rótulo e artigo; faixas do Dashboard fechadas como os rótulos.

Escritos antes da implementação; falhavam em f51ef5e.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app import permissoes
from tests.test_seguranca_lote1 import _Fake
from tests.test_seguranca_lote4 import ADMIN, DOC_A, DOC_B, DOC_C, DOC_L, FISCAL_OP, GESTOR, _docs, _h, _item  # noqa: F401
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401

RAIZ = Path(__file__).resolve().parents[1]
AGORA = datetime.now(timezone.utc)


@pytest.fixture
def banco(banco_base: _Fake) -> _Fake:
    banco_base.tabelas["carteira_excecao"] = []
    return banco_base


# ── D1: vencido = cliente vigente do inventário atual ─────────────────────

def test_vencidos_conta_pelo_cliente_vigente(client: TestClient, banco: _Fake) -> None:
    """DOC_L está expirado; DOC_A ganha um arquivo antigo vencido, mas o
    vigente é válido — o cliente não é vencido."""
    banco.tabelas["cert_snapshots"][0]["items"].append(_item(DOC_A, "f" * 64, status="expirado", venc=AGORA - timedelta(days=10), nome="ALFA ANTIGO"))
    r = client.get("/api/certificados/vencidos?pagina=1&por_pagina=50", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    d = r.json()
    assert _docs(d["itens"]) == {DOC_L}
    assert d["total"] == 1 and d["atualizado_em"] and d["alcance_vazio"] is False
    # Operador sem atribuição: carteira vazia, não "nenhum vencido".
    banco.tabelas["carteira"] = [x for x in banco.tabelas["carteira"] if x["user_id"] != "u-fis"]
    d = client.get("/api/certificados/vencidos", headers=_h(*FISCAL_OP)).json()
    assert d["itens"] == [] and d["alcance_vazio"] is True


def test_dashboard_curva_pelo_cliente_vigente(banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import dashboard as dash
    monkeypatch.setattr(dash, "_banco", lambda: banco)
    banco.tabelas["cert_history"] = [{"vencimento_certificado": (AGORA - timedelta(days=3)).isoformat(), "status_ultimo": "expirado"}]
    banco.tabelas["cert_snapshots"][0]["items"].append(_item(DOC_A, "f" * 64, status="expirado", venc=AGORA - timedelta(days=10), nome="ALFA ANTIGO"))
    a = dash.painel_acervo()
    v = a["vencimento"]
    # Clientes: A (válido, 200 d), B, C (200 d) e L (vencido). O arquivo antigo de A não conta.
    assert v["vencido"] == 1 and v["acima_de_90"] == 3
    assert a["por_status"] == {"expirado": 1}, "a legibilidade continua vindo do histórico de arquivos"


def test_faixas_fechadas_como_os_rotulos() -> None:
    from app import dashboard as dash
    def faixa(dias):
        for nome, minimo, maximo in dash.FAIXAS_VENCIMENTO:
            if minimo is None and dias < 0:
                return nome
            if minimo is not None and dias >= minimo and (maximo is None or dias < maximo):
                return nome
    assert faixa(7) == "ate_7_dias" and faixa(8) == "ate_30_dias"
    assert faixa(30) == "ate_30_dias" and faixa(31) == "ate_60_dias"
    assert faixa(90) == "ate_90_dias" and faixa(91) == "acima_de_90"


# ── D2: Dashboard só admin ────────────────────────────────────────────────

def test_dashboard_e_so_do_administrador(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(permissoes, "_matriz", lambda: {
        "gestor": {**permissoes.PADRAO["gestor"], "dashboard": permissoes.NIVEL_LER}, "user": permissoes.PADRAO["user"]})
    assert permissoes.nivel_de("gestor", "dashboard") == permissoes.NIVEL_NENHUM
    assert client.get("/api/dashboard", headers=_h(*GESTOR)).status_code == 403
    assert client.get("/api/dashboard/renovacoes", headers=_h(*GESTOR)).status_code == 403
    assert client.get("/api/dashboard", headers=_h(*ADMIN)).status_code != 403


# ── Duplicidades recortado pelo Alcance ───────────────────────────────────

def test_duplicidades_respeita_o_alcance(client: TestClient, banco: _Fake) -> None:
    itens = banco.tabelas["cert_snapshots"][0]["items"]
    # DOC_B duplicado (mesmo fingerprint em dois arquivos): só quem alcança B vê.
    itens.append({**_item(DOC_B, "b" * 64, nome="BETA"), "nome_publico": "BETA_copia"})
    r = client.get("/api/certificados/duplicidades", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert r.json()["total_grupos_certificado_igual"] == 1
    r = client.get("/api/certificados/duplicidades", headers=_h(*FISCAL_OP))  # só DOC_A
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["total_grupos_certificado_igual"] == 0 and d["total_itens_analisados"] == 1
    assert d["alcance_vazio"] is False
    banco.tabelas["carteira"] = [x for x in banco.tabelas["carteira"] if x["user_id"] != "u-fis"]
    d = client.get("/api/certificados/duplicidades", headers=_h(*FISCAL_OP)).json()
    assert d["total_itens_analisados"] == 0 and d["alcance_vazio"] is True


# ── Histórico ─────────────────────────────────────────────────────────────

def test_historico_devolve_atualizado_em_e_alcance_vazio(client: TestClient, banco: _Fake) -> None:
    r = client.get("/api/certificados/historico?pagina=1&por_pagina=20", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert r.json()["atualizado_em"] and r.json()["alcance_vazio"] is False
    banco.tabelas["carteira"] = [x for x in banco.tabelas["carteira"] if x["user_id"] != "u-fis"]
    d = client.get("/api/certificados/historico?pagina=1&por_pagina=20", headers=_h(*FISCAL_OP)).json()
    assert d["itens"] == [] and d["alcance_vazio"] is True


def test_historico_busca_por_digitos_do_documento() -> None:
    itens = [{"nome": "ALFA", "documento": "11.111.111/0001-91", "nome_publico": "ALFA.pfx"}]
    assert m._historico_filtrar_busca(itens, "11111111000191") == itens
    assert "documento_numero.ilike" in m._historico_busca_or_filter("1111") if hasattr(m, "_historico_busca_or_filter") else True


# ── 403 com rótulo ────────────────────────────────────────────────────────

def test_403_diz_o_modulo_pelo_nome(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    matriz = {p: {mod: permissoes.NIVEL_NENHUM for mod in permissoes.MODULOS} for p in ("gestor", "user")}
    monkeypatch.setattr(permissoes, "_matriz", lambda: matriz)
    r = client.get("/api/certificados/historico", headers=_h(*FISCAL_OP))
    assert r.status_code == 403 and r.json()["detail"] == "Seu perfil não tem acesso ao Histórico."
    assert set(permissoes.ROTULO_MODULO) == set(permissoes.MODULOS)


# ── Telas ─────────────────────────────────────────────────────────────────

def test_telas_de_consulta_revisadas() -> None:
    dash = (RAIZ / "templates" / "dashboard.html").read_text(encoding="utf-8")
    assert 'href="/?status=prestes_vencer"' in dash and 'href="/vencidos">Ver vencidos' in dash
    assert "Ver arquivos com erro" not in dash and "Ver varreduras" not in dash
    assert "erroEmTodosOsCards" in dash and "d.truncado" in dash
    assert "Clientes com certificado vencido" in dash
    hist = (RAIZ / "templates" / "historico.html").read_text(encoding="utf-8")
    assert "Planilha (CSV)" in hist and "snapshots" not in hist.lower()
    assert ">Status</th>" in hist and "badgeStatusHistorico" in hist
    assert "Sua carteira está vazia" in hist
    venc = (RAIZ / "templates" / "vencidos.html").read_text(encoding="utf-8")
    assert "Planilha (CSV)" in venc and "Empresa" not in venc and "suas empresas" not in venc
    assert "Sua carteira está vazia" in venc and "sem data registrada" in venc
    dup = (RAIZ / "templates" / "duplicidades.html").read_text(encoding="utf-8")
    assert "Empresa" not in dup and "homônimos" in dup
    assert "Copiar nome" in dup and "r.status === 403" in dup
    inicio = (RAIZ / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'get("status")' in inicio
