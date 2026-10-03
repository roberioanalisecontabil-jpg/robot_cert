"""
Revisão da página Instalador (01/10/2026) — decisões P1 a P3 e defeitos.

  P1  Instalador é só do Administrador; sai da matriz (como Usuários).
  P2  Rotas sem chamador saem: available, logs, cleanup.
  P3  "Expurgar trilha" expurga só a trilha; atividade e cofre ficam no job diário (`cron_alerts`).

Defeitos: vencidos e ilegíveis sem botão "Reativar"; etapa em que parou
marcada; validade do pedido = a configurada; trilha avisa quando cortou;
vocabulário Servidor/Estação.

Escritos antes da implementação; falhavam em 3e0f6a7.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app import permissoes
from tests.test_seguranca_lote1 import _Fake
from tests.test_seguranca_lote4 import ADMIN, FISCAL_OP, GESTOR, _h  # noqa: F401
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture
def banco(banco_base: _Fake) -> _Fake:
    banco_base.tabelas["carteira_excecao"] = []
    return banco_base


# ── P1 ────────────────────────────────────────────────────────────────────

def test_instalador_e_so_do_administrador(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        permissoes, "_matriz",
        lambda: {"gestor": {**permissoes.PADRAO["gestor"], "instalador": permissoes.NIVEL_EDITAR},
                 "user": permissoes.PADRAO["user"]},
    )
    assert permissoes.nivel_de("gestor", "instalador") == permissoes.NIVEL_NENHUM
    assert "instalador" in permissoes.MODULOS_SO_ADMIN and "instalador" not in permissoes.MODULOS_GOVERNADOS
    for rota in ("/api/cert-installer/diagnostico", "/api/cert-installer/trilha", "/api/cert-installer/expurgo-previa"):
        assert client.get(rota, headers=_h(*GESTOR)).status_code == 403, rota
    assert client.post("/api/cert-installer/vault-optin", json={"fingerprint": "a" * 64, "machine_id": "srv"},
                       headers=_h(*GESTOR)).status_code == 403
    # O administrador entra.
    assert client.get("/api/cert-installer/trilha", headers=_h(*ADMIN)).status_code == 200


# ── P2 ────────────────────────────────────────────────────────────────────

def test_rotas_sem_chamador_sumiram(client: TestClient, banco: _Fake) -> None:
    assert client.get("/api/cert-installer/available", headers=_h(*ADMIN)).status_code in (404, 405)
    assert client.get("/api/cert-installer/logs", headers=_h(*ADMIN)).status_code in (404, 405)
    assert client.post("/api/cert-installer/cleanup", headers=_h(*ADMIN)).status_code in (404, 405)


# ── P3 ────────────────────────────────────────────────────────────────────

def test_expurgar_trilha_so_expurga_a_trilha(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas = []
    monkeypatch.setattr(m.cert_installer, "expurgar_install_log", lambda *a, **k: chamadas.append("trilha") or {"apagados": 0})
    monkeypatch.setattr(m.atividade, "expurgar", lambda *a, **k: chamadas.append("atividade") or {})
    monkeypatch.setattr(m.cert_installer, "expurgar_cofre", lambda *a, **k: chamadas.append("cofre") or {})
    r = client.post("/api/cert-installer/expurgar-log", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert chamadas == ["trilha"]
    assert set(r.json()) == {"install_log"}
    # O job diário continua cuidando dos outros (em `_expurgo_diario`, que o
    # laço do lifespan e o cron chamam — 03/10/2026).
    fonte = (RAIZ / "app" / "main.py").read_text(encoding="utf-8")
    i = fonte.index("def _expurgo_diario")
    trecho = fonte[i:fonte.index("\n@app.", i)]
    assert "atividade.expurgar" in trecho and "expurgar_cofre" in trecho and "snapshots.expurgar" in trecho
    assert "_expurgo_diario" in fonte[fonte.index("async def daily_alerts_job_loop"):fonte.index("async def novos_por_hora_loop")]


# ── Trilha avisa quando cortou ────────────────────────────────────────────

def test_trilha_diz_quando_o_teto_cortou(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    def _cadeias(limite, desde, user_email=None, apenas_com_falha=False):
        return [{"token_id": "t", "eventos": [{"event": "SOLICITADO"}] * limite, "desfecho": "incompleto",
                 "parou_em": "SOLICITADO", "certificados": 1, "target_machine": "pc"}]
    monkeypatch.setattr(m.cert_installer, "cadeias_de_instalacao", _cadeias)
    monkeypatch.setattr(m.cert_installer, "resumo_das_cadeias", lambda c: {"total": 1, "concluidas": 0, "falhadas": 0})
    r = client.get("/api/cert-installer/trilha?limite=10", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert r.json()["truncado"] is True
    monkeypatch.setattr(m.cert_installer, "cadeias_de_instalacao", lambda **k: [])
    assert client.get("/api/cert-installer/trilha", headers=_h(*ADMIN)).json()["truncado"] is False


# ── Tela ──────────────────────────────────────────────────────────────────

def test_tela_do_instalador_revisada() -> None:
    html = (RAIZ / "templates" / "instalador.html").read_text(encoding="utf-8")
    assert "Fora da custódia" in html and "foraPorEstado" in html
    assert '(parouAqui ? "is-feita" : "is-feita")' not in html and "is-falha" in html
    assert "enviado por e-mail" not in html
    assert "Retenção da trilha" in html and "Retenção do log" not in html
    assert "Máquina: " not in html and ">Estação<" in html and "Servidor: " in html
    assert "nesta máquina" not in html and "desta máquina" not in html
    assert 'Number(dias) < 90' in html
    assert "data.truncado" in html
    assert "HTTP ${rOptin.status}" not in html
    assert "Oitava tela" not in html
    css = (RAIZ / "static" / "aguia-instalador.css").read_text(encoding="utf-8")
    assert ".cg-inst-cab__acoes" not in css
