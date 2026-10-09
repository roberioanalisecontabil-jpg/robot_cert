"""
Revisão das páginas Configuração e Login/sessão (02/10/2026) — decisões L1 a L4.

  L1  Configuração é só do Administrador; sai da matriz. O agente continua
      lendo /api/settings pela chave de API.
  L2  Sem token a página nem monta: ui-common.js redireciona para
      /login?next=… antes de qualquer fetch; o servidor segue sem guarda nas
      rotas HTML (limitação aceita: o token vive no localStorage).
  L3  "Fonte dos dados" sai (sempre "auto"); a URL é só do agent_config.json.
  L4  "Disparar agora" dispara tudo (resumo e pessoais), com texto honesto.

Defeitos: senha mínima 12 na tela; "Sair" com senha provisória revoga;
remetente validado; prévia pelo certificado vigente; 401 x 403; gate de
administrador num ponto só (data-so-admin); login com fonte local, `next`,
erro 422 legível e aviso de sessão encerrada.
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


# ── L1 ────────────────────────────────────────────────────────────────────

def test_configuracao_e_so_do_administrador(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(permissoes, "_matriz", lambda: {
        "gestor": {**permissoes.PADRAO["gestor"], "configuracao": permissoes.NIVEL_EDITAR}, "user": permissoes.PADRAO["user"]})
    assert "configuracao" in permissoes.MODULOS_SO_ADMIN
    assert permissoes.nivel_de("gestor", "configuracao") == permissoes.NIVEL_NENHUM
    assert client.get("/api/settings", headers=_h(*GESTOR)).status_code == 403
    assert client.put("/api/settings", json={}, headers=_h(*GESTOR)).status_code == 403
    assert client.post("/api/settings/alerts/trigger", headers=_h(*GESTOR)).status_code == 403
    assert client.get("/api/settings", headers=_h(*ADMIN)).status_code != 403


# ── Sair com senha provisória revoga ──────────────────────────────────────

def test_logout_passa_com_senha_provisoria() -> None:
    assert "/api/logout" in m.ROTAS_COM_SENHA_PROVISORIA


def test_remetente_invalido_e_recusado(client: TestClient, banco: _Fake) -> None:
    corpo = {**m.SettingsBody().model_dump(), "smtp_from_email": "nao-e-email"}
    r = client.put("/api/settings", json=corpo, headers=_h(*ADMIN))
    assert r.status_code == 422 and "remetente" in r.json()["detail"], r.text


def test_codigo_morto_do_login_antigo_saiu() -> None:
    assert not hasattr(m, "_conta_local_do_email")
    fonte = (RAIZ / "app" / "main.py").read_text(encoding="utf-8")
    assert "Cron do Vercel." not in fonte


# ── Telas ─────────────────────────────────────────────────────────────────

def test_gate_de_administrador_num_ponto_so() -> None:
    ui = (RAIZ / "static" / "ui-common.js").read_text(encoding="utf-8")
    assert "function gateAdmin" in ui and 'dataset.soAdmin !== "1"' in ui
    # L2 (sem sessão a página nem monta) saiu do navegador para o servidor na
    # Leva D (09/10/2026): ver tests/test_sessao_cookie.py.
    assert "function exigirSessao" not in ui and "function apagarTokenAntigo" in ui, "L2"
    assert 'logout("sessao")' in ui and "Sessão encerrada. Entre novamente." in ui
    assert 'minlength="12"' in ui and 'minlength="6"' not in ui
    assert 'return "auto";' in ui, "L3: fonte fixa"
    for nome in ("configuracao", "usuarios", "instalador", "dashboard"):
        html = (RAIZ / "templates" / f"{nome}.html").read_text(encoding="utf-8")
        assert 'data-so-admin="1"' in html, nome
        assert "Acesso restrito a administradores" not in html, f"{nome}: o gate inline saiu"


def test_tela_de_configuracao_revisada() -> None:
    html = (RAIZ / "templates" / "configuracao.html").read_text(encoding="utf-8")
    assert "sel-fonte" not in html and "Fonte dos dados" not in html, "L3"
    assert "agent_config.json" in html and "o portal não a usa" in html
    assert "aguarda print" not in html
    assert 'list="portas-smtp"' in html and 'max="65535"' not in html
    assert "no dia do vencimento" not in html
    assert "colaborador" not in html.lower().replace("colaborador_", "")
    assert "Máquina alvo" not in html and "Servidor alvo" in html
    assert "e-mails pessoais de quem acompanha" in html and "admin_resumos_enviados" in html, "L4"
    assert "r.status === 403" in html and "401: a sessão expirou" not in html
    assert "Banco de dados: não verificado" in html


def test_tela_de_login_revisada() -> None:
    html = (RAIZ / "templates" / "login.html").read_text(encoding="utf-8")
    assert "fonts.googleapis.com" not in html and "aguia-fontes.css" in html
    assert 'minlength="12"' in html and 'minlength="6"' not in html
    assert "destinoAposLogin" in html and "textoDoErro" in html
    assert "cg_toast_pendente" in html, "o aviso de sessão encerrada chega à tela de login"
    assert "✅" not in html and "⚠️" not in html
    inicio = (RAIZ / "templates" / "index.html").read_text(encoding="utf-8")
    assert "/configuracao?aba=pastas" in inicio


def test_previa_do_email_usa_o_certificado_vigente() -> None:
    fonte = (RAIZ / "app" / "alert_state.py").read_text(encoding="utf-8")
    i = fonte.index("Prévia do e-mail")
    assert "vigentes_por_documento" in fonte[i - 600:i]


# ── Leva C (06/10/2026): as três abas que faltavam da Configuração ────────

def test_configuracao_sem_abas_legadas() -> None:
    html = (Path(__file__).resolve().parents[1] / "templates" / "configuracao.html").read_text(encoding="utf-8")
    assert "cg-cfg-legado" not in html
    # A fila é tabela, não o JSON da API num <pre>.
    assert "JSON.stringify(p, null, 2)" not in html and 'class="ag-table cg-tabela-fila"' in html
    # O agente é serviço instalado por instalador, não "python run_agent.py".
    assert "python agent\run_agent.py" not in html
    assert "AnaliseCertiDigitalAgent" in html and "Instalador_AnaliseCertiDigital_Agente.exe" in html
