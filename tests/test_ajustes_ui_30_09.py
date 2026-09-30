"""
Três pedidos de 30/09/2026, depois do portal em uso:

  1. Notificações: marcar UM aviso como lido, além do "Li todos".
  2. O sanduíche do menu mora na barra lateral (no celular fica um no topo,
     porque a barra sai da tela e levaria o botão junto).
  3. Carteiras: a lista de operadores tem fio entre os itens, como as colunas
     "Disponíveis" e "Na carteira".

Escritos antes da correção; falhavam em 57ca331.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app import auth

RAIZ = Path(__file__).resolve().parents[1]


def _admin() -> dict:
    return {"Authorization": "Bearer " + auth.create_access_token({"sub": "admin@x.com", "role": "admin"})}


# ── 1. Marcar um aviso como lido ───────────────────────────────────────────

@pytest.fixture
def avisos(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Dois avisos acionáveis desta pessoa e um que não é; a gravação é capturada."""
    gravado: dict = {"chaves": []}
    monkeypatch.setattr(m, "get_active_alerts", lambda email, role, uid: [
        {"chave": "fp-a|30", "acionavel": True, "nome": "ALFA"},
        {"chave": "fp-b|7", "acionavel": True, "nome": "BETA"},
        {"chave": "fp-c|0", "acionavel": False, "nome": "GAMA"},
    ])
    monkeypatch.setattr(m, "marcar_notificacoes_lidas", lambda uid, chaves: gravado["chaves"].extend(chaves) or len(chaves))
    return gravado


def test_marca_so_o_aviso_pedido(client: TestClient, avisos: dict) -> None:
    r = client.post("/api/colaborador/notificacoes/lida", json={"chave": "fp-a|30"}, headers=_admin())
    assert r.status_code == 200, r.text
    assert r.json() == {"marcadas": 1}
    assert avisos["chaves"] == ["fp-a|30"], "o outro aviso continua no sino"


def test_chave_que_nao_e_um_aviso_pendente_e_404(client: TestClient, avisos: dict) -> None:
    for chave in ("inventada|1", "fp-c|0"):  # inexistente, e existente mas não acionável
        r = client.post("/api/colaborador/notificacoes/lida", json={"chave": chave}, headers=_admin())
        assert r.status_code == 404, r.text
    assert avisos["chaves"] == [], "nada pode ter sido gravado"


def test_chave_vazia_e_422(client: TestClient, avisos: dict) -> None:
    assert client.post("/api/colaborador/notificacoes/lida", json={"chave": ""}, headers=_admin()).status_code == 422


def test_sem_login_e_401(client_com_chave: TestClient) -> None:
    """Com API_KEY (produção), quem chega sem sessão leva 401 antes da rota.
    (No modo aberto de desenvolvimento o anônimo chega à rota e leva 404,
    porque não tem aviso nenhum — também não marca nada.)"""
    assert client_com_chave.post("/api/colaborador/notificacoes/lida", json={"chave": "x"}).status_code == 401


def test_o_sino_tem_o_botao_por_item() -> None:
    js = (RAIZ / "static" / "ui-common.js").read_text(encoding="utf-8")
    assert "/api/colaborador/notificacoes/lida\"" in js
    assert "notif-item-lida-btn" in js
    assert "Marcar como lida" in js
    css = (RAIZ / "static" / "style.css").read_text(encoding="utf-8")
    assert ".notif-item-lida-btn" in css


# ── 2. Sanduíche na barra lateral ──────────────────────────────────────────

def test_sanduiche_vai_para_a_barra_lateral_e_o_topo_fica_so_no_celular() -> None:
    js = (RAIZ / "static" / "ui-common.js").read_text(encoding="utf-8")
    trecho = js.split("function initSidebarToggle")[1].split("\nfunction ")[0]
    assert '.sidebar-header' in trecho, "o botão tem de ser criado dentro do cabeçalho da barra"
    assert "sidebar-toggle-btn--lateral" in trecho and "sidebar-toggle-btn--mobile" in trecho
    css = (RAIZ / "static" / "style.css").read_text(encoding="utf-8")
    assert ".sidebar-header .sidebar-toggle-btn--lateral" in css
    # No desktop o do topo some; no celular o da barra some (ela sai da tela).
    assert re.search(r"\.topbar-actions \.sidebar-toggle-btn--mobile\s*\{\s*display:\s*none", css)
    bloco_mobile = css.split("@media (max-width: 768px)")[-1]
    assert ".sidebar-header .sidebar-toggle-btn--lateral { display: none; }" in bloco_mobile


# ── 3. Fio entre operadores ────────────────────────────────────────────────

def test_lista_de_operadores_tem_o_mesmo_fio_das_colunas_da_carteira() -> None:
    css = (RAIZ / "static" / "aguia-carteiras.css").read_text(encoding="utf-8")
    item = css.split(".cg-op-item {")[1].split("}")[0]
    assert "border-bottom: var(--bw-1) solid var(--border-default)" in item
    lado = css.split(".cg-transfer__lado {")[1].split("}")[0]
    assert "var(--border-default)" in lado, "é este o fio que a pessoa vê nas colunas"


def test_cache_busters_dos_arquivos_alterados_subiram() -> None:
    """Sem isto o navegador segue com o CSS/JS antigo e nada do acima aparece."""
    html = (RAIZ / "templates" / "carteiras.html").read_text(encoding="utf-8")
    assert "aguia-carteiras.css?v=aguia-2026-09a" in html
    assert "ui-common.js?v=aguia-2026-09h" in html
    assert "style.css?v=menu-lateral-2026-09" in html
    for nome in ("index.html", "usuarios.html", "vencidos.html"):
        t = (RAIZ / "templates" / nome).read_text(encoding="utf-8")
        assert "ui-common.js?v=aguia-2026-09h" in t and "style.css?v=menu-lateral-2026-09" in t
