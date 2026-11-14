"""Aba "Remoção nas estações" da Configuração (Frente B, 14/11/2026)."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parents[1]
TEMPLATE = (RAIZ / "templates" / "configuracao.html").read_text(encoding="utf-8")
JS = RAIZ / "static" / "configuracao-remocao.js"


def test_aba_remocao_existe_e_abre_pelo_link(client: TestClient) -> None:
    assert 'href="?aba=remocao"' in TEMPLATE and 'id="sec-remocao"' in TEMPLATE
    assert "Remoção nas estações" in TEMPLATE
    html = client.get("/configuracao?aba=remocao").text
    assert re.search(r'id="tab-remocao"[^>]*aria-selected="true"', html)
    assert "hidden" not in re.search(r'<section[^>]*id="sec-remocao"[^>]*>', html).group(0).replace("role=", "")


def test_selects_com_os_tres_modos() -> None:
    for sel in ("sel-remocao-carteira", "sel-remocao-sem-login"):
        bloco = re.search(rf'<select id="{sel}".*?</select>', TEMPLATE, re.S).group(0)
        for v in ("desligado", "relatorio", "ligado"):
            assert f'value="{v}"' in bloco
    assert "Desligado: não confere. Só relatório: lista o que sairia, sem remover." in TEMPLATE


def test_js_e_servido_e_incluido(client: TestClient) -> None:
    assert "/static/configuracao-remocao.js" in TEMPLATE
    r = client.get("/static/configuracao-remocao.js")
    assert r.status_code == 200 and "/api/remocao" in r.text


def test_js_nunca_monta_html_com_dado_da_estacao() -> None:
    # usuario_windows, detalhe e motivo vêm da estação: só textContent.
    assert "innerHTML" not in JS.read_text(encoding="utf-8")


def test_rotulos_de_estado_e_regra() -> None:
    js = JS.read_text(encoding="utf-8")
    for rotulo in ("Removeria (relatório)", "Em aviso", "Remoção pendente", "Removido", "Falhou",
                   "Carteira", "Conta desativada", "Computador recusado/desvinculado",
                   "Empréstimo vencido", "Perfil sem login"):
        assert rotulo in js


def test_salvar_manda_so_os_dois_modos_alem_do_corpo_base() -> None:
    # O PUT remonta os campos "próprios" a partir do corpo; por isso vai o corpo
    # base das outras abas. Dos campos que o PUT preserva quando omitidos
    # (None), nenhum vai: só os dois modos.
    fn = re.search(r"async function salvarRemocao\(\).*?\n      \}\n", TEMPLATE, re.S).group(0)
    assert "remocao_carteira_modo" in fn and "remocao_sem_login_modo" in fn
    for outro in ("corpoEntrada", "corpoModeloEmail", "install_token_ttl_min", "trilha_retencao_dias"):
        assert outro not in fn
