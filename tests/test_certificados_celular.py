"""Aba Certificados no celular (17/11/2026).

A regra de duas etapas da aba Pessoas escondia o detalhe do certificado em
qualquer tela até 1024px, e a lista do modal não tinha teto de altura.
"""

from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CSS = (RAIZ / "static" / "aguia-carteiras.css").read_text(encoding="utf-8")
JS = (RAIZ / "static" / "carteiras-certificados.js").read_text(encoding="utf-8")
HTML = (RAIZ / "templates" / "carteiras.html").read_text(encoding="utf-8")


def test_regra_das_duas_etapas_de_pessoas_nao_alcanca_certificados():
    assert "body:not(.cg-tem-operador) .cg-cart-detalhe" not in CSS
    assert "body:not(.cg-tem-operador) #sec-pessoas .cg-cart-detalhe" in CSS


def test_certificado_aberto_troca_lista_pelo_detalhe():
    assert "#sec-certificados:not(.cg-tem-cert) .cg-cart-detalhe { display: none; }" in CSS
    assert "#sec-certificados.cg-tem-cert .cg-cart-lista { display: none; }" in CSS
    assert 'classList.add("cg-tem-cert")' in JS
    assert '{% if certificado_id %}class="cg-tem-cert"' in HTML
    assert 'voltar_texto="Voltar para certificados"' in HTML


def test_lista_do_modal_tem_teto():
    assert "#modalIncluir .cg-op-rolagem { max-height:" in CSS


def test_cabecalho_do_voltar_some_no_desktop_nas_duas_abas():
    desktop = CSS[CSS.index("@media (min-width: 1025px)"):CSS.index("@media (max-width: 1024px)")]
    assert ".cg-cart-detalhe > .cg-cart-cab { display: none; }" in desktop
    assert "#sec-certificados .cg-cart-detalhe > .cg-cart-cab" not in CSS


def test_rotulo_oculto_da_tabela_nao_alarga_a_pagina():
    assert "#certDetalhe .ag-table-scroll { position: relative; }" in CSS
