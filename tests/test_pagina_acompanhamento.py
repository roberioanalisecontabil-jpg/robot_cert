"""
Revisão da página Acompanhamento (01/10/2026) — I4 fechado, A1 a A3 e defeitos.

  I4  A seleção fica dentro do Alcance: recortada ao gravar e ao ler, no
      painel, no sino e no job de e-mail.
  A1  Sino e e-mail avisam por Cliente, pelo certificado vigente (app/vigencia.py).
  A2  "Quero receber aviso" desligado vale também para o e-mail de novos.
  A3  KPIs do painel não mudam com a busca.

Defeitos: preferência sem linha de seleção passa a ser gravada; opções
distinguem alcance vazio de erro; 403 com acento; "Ver instalações" do
Dashboard aponta para a trilha; vocabulário Cliente.

Escritos antes da implementação; falhavam em 84e36e3.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app import vigencia
from tests.test_seguranca_lote1 import _Fake
from tests.test_seguranca_lote4 import ADMIN, DOC_A, DOC_B, DOC_C, DOC_L, FISCAL_OP, GESTOR, _h, _item  # noqa: F401
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401

RAIZ = Path(__file__).resolve().parents[1]
SEL = "/api/colaborador/certificados/selecionados"
AGORA = datetime.now(timezone.utc)


@pytest.fixture
def banco(banco_base: _Fake) -> _Fake:
    banco_base.tabelas["carteira_excecao"] = []
    banco_base.tabelas["colaborador_cert_selecoes"] = []
    return banco_base


# ── I4: seleção dentro do Alcance ─────────────────────────────────────────

def test_selecao_e_recortada_ao_gravar_e_ao_ler(client: TestClient, banco: _Fake) -> None:
    """u-fis só tem DOC_A atribuído. Pede A e B: grava só A."""
    r = client.put(SEL, json={"documentos": [DOC_A, DOC_B]}, headers=_h(*FISCAL_OP))
    assert r.status_code == 200, r.text
    assert r.json()["documentos"] == [DOC_A] and r.json()["fora_do_alcance"] == 1
    # A linha gravada tinha A; o gestor tira A do operador: A some da leitura,
    # mas a linha fica (preferência, não acesso) e volta se o alcance voltar.
    client.delete(f"/api/carteira/u-fis/{DOC_A}", headers=_h(*ADMIN))
    assert client.get(SEL, headers=_h(*FISCAL_OP)).json()["documentos"] == []
    assert client.get("/api/colaborador/certificados/painel", headers=_h(*FISCAL_OP)).json()["itens"] == []
    client.post("/api/carteira", json={"user_id": "u-fis", "documentos": [DOC_A]}, headers=_h(*ADMIN))
    assert client.get(SEL, headers=_h(*FISCAL_OP)).json()["documentos"] == [DOC_A]


def test_sino_do_operador_respeita_o_alcance(client: TestClient, banco: _Fake) -> None:
    # u-fis seleciona A (que tem) e, por fora do portal, a linha ganha B.
    banco.tabelas["colaborador_cert_selecoes"] = [{"user_id": "u-fis", "documentos": [DOC_A, DOC_B], "notificar_email": True}]
    # Faz A e B vencerem em 10 dias para entrarem no sino.
    for it in banco.tabelas["cert_snapshots"][0]["items"]:
        if it.get("documento_numero") in (DOC_A, DOC_B):
            it["not_after"] = (AGORA + timedelta(days=10)).isoformat()
    r = client.get("/api/colaborador/notificacoes", headers=_h(*FISCAL_OP))
    assert r.status_code == 200, r.text
    docs = {"".join(c for c in (n.get("documento") or "") if c.isdigit()) for n in r.json().get("notificacoes", r.json().get("itens", []))}
    assert DOC_A in docs and DOC_B not in docs


def test_opcoes_dizem_quando_o_alcance_esta_vazio(client: TestClient, banco: _Fake) -> None:
    banco.tabelas["carteira"] = [r for r in banco.tabelas["carteira"] if r["user_id"] != "u-fis"]
    d = client.get("/api/colaborador/certificados/opcoes", headers=_h(*FISCAL_OP)).json()
    assert d["itens"] == [] and d["alcance_vazio"] is True
    assert client.get("/api/colaborador/certificados/opcoes", headers=_h(*GESTOR)).json()["alcance_vazio"] is False


# ── A1: certificado vigente por Cliente ───────────────────────────────────

def test_vigente_por_documento_prefere_o_valido_mais_longo() -> None:
    antigo = {"documento_numero": DOC_A, "status": "expirado", "not_after": (AGORA - timedelta(days=30)).isoformat(), "fingerprint_sha256": "velho"}
    novo = {"documento_numero": DOC_A, "status": "ok", "not_after": (AGORA + timedelta(days=300)).isoformat(), "fingerprint_sha256": "novo"}
    ilegivel = {"documento_numero": DOC_A, "status": "erro", "not_after": None, "fingerprint_sha256": "ruim"}
    sem_doc = {"documento_numero": None, "status": "ok", "not_after": (AGORA + timedelta(days=5)).isoformat(), "fingerprint_sha256": "x"}
    saida = vigencia.vigentes_por_documento([antigo, ilegivel, novo, sem_doc], AGORA)
    assert [i["fingerprint_sha256"] for i in saida] == ["novo", "x"]
    # Só vencidos: fica o que venceu por último.
    mais_velho = {**antigo, "not_after": (AGORA - timedelta(days=400)).isoformat(), "fingerprint_sha256": "mais-velho"}
    assert vigencia.vigentes_por_documento([mais_velho, antigo], AGORA)[0]["fingerprint_sha256"] == "velho"


def test_sino_nao_avisa_o_arquivo_antigo_de_cliente_renovado(client: TestClient, banco: _Fake) -> None:
    """Admin vê tudo no sino, mas 'tudo' é um certificado por cliente."""
    itens = banco.tabelas["cert_snapshots"][0]["items"]
    itens.append(_item(DOC_A, "f" * 64, status="expirado", venc=AGORA - timedelta(days=10), nome="ALFA ANTIGO"))
    r = client.get("/api/colaborador/notificacoes", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    corpo = r.json()
    lista = corpo.get("notificacoes") or corpo.get("itens") or []
    assert not any(n.get("fingerprint_sha256") == "f" * 64 for n in lista), "o arquivo antigo do cliente renovado não vence de novo"


# ── A2: a preferência vale para os novos ──────────────────────────────────

def test_email_de_novos_respeita_quero_receber_aviso(banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import novos_certificados as nc
    monkeypatch.setattr(nc, "_contas_ativas", lambda: [
        {"id": "u-fis", "email": "fis@x.com", "role": "user", "ativo": True},
        {"id": "u-sol", "email": "solto@x.com", "role": "user", "ativo": True},
    ])
    monkeypatch.setattr(nc, "load_preferencia_alerta", lambda uid: {"notificar_email": uid != "u-fis", "alerta_marcos_ignorados": ""})
    monkeypatch.setattr(nc, "documentos_ao_alcance", lambda uid, papel: {DOC_A} if uid == "u-fis" else {DOC_B})
    novos = [{"documento_numero": DOC_A, "nome": "ALFA"}, {"documento_numero": DOC_B, "nome": "BETA"}]
    settings = type("S", (), {"alertas_destinatarios": ""})()
    dest = nc._destinatarios(settings, novos)
    assert "fis@x.com" not in dest, "desligou o aviso: não recebe nem os novos"
    assert [n["documento_numero"] for n in dest["solto@x.com"]] == [DOC_B]


# ── Preferência sem linha de seleção ──────────────────────────────────────

def test_preferencia_e_gravada_mesmo_sem_selecao(client: TestClient, banco: _Fake) -> None:
    r = client.put("/api/colaborador/alertas/preferencia", json={"notificar_email": False, "marcos_ignorados": "7"}, headers=_h(*FISCAL_OP))
    assert r.status_code == 200, r.text
    linhas = [l for l in banco.tabelas["colaborador_cert_selecoes"] if l["user_id"] == "u-fis"]
    assert len(linhas) == 1 and linhas[0]["notificar_email"] is False and linhas[0]["documentos"] == []
    # A seleção gravada depois não apaga a preferência.
    client.put(SEL, json={"documentos": [DOC_A]}, headers=_h(*FISCAL_OP))
    linhas = [l for l in banco.tabelas["colaborador_cert_selecoes"] if l["user_id"] == "u-fis"]
    assert len(linhas) == 1 and linhas[0]["documentos"] == [DOC_A] and linhas[0]["notificar_email"] is False


# ── Textos e tela ─────────────────────────────────────────────────────────

def test_403_com_acento(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import permissoes
    matriz = {p: {mod: permissoes.NIVEL_NENHUM for mod in permissoes.MODULOS} for p in ("gestor", "user")}
    monkeypatch.setattr(permissoes, "_matriz", lambda: matriz)
    r = client.get("/api/colaborador/certificados/painel", headers=_h(*FISCAL_OP))
    assert r.status_code == 403 and r.json()["detail"] == "Seu perfil não tem acesso ao Acompanhamento."


def test_tela_de_acompanhamento_revisada() -> None:
    html = (RAIZ / "templates" / "colaborador_certificados.html").read_text(encoding="utf-8")
    assert "Empresa" not in html and "suas empresas" not in html
    assert "atualizarIndicadores(painelItens)" in html, "A3: KPIs fixos"
    assert "Nenhum cliente atribuído a você" in html and "_opcoesErro" in html
    assert "aplicarNivel" in html and "soVer" in html
    assert "no dia do vencimento" not in html and "quando vencer" in html
    dash = (RAIZ / "templates" / "dashboard.html").read_text(encoding="utf-8")
    assert 'href="/instalador?aba=trilha">Ver instalações' in dash
