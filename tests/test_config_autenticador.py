"""App autenticador numa aba da Configuração (24/11/2026)."""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def test_aba_app_autenticador_na_configuracao():
    html = (RAIZ / "templates" / "configuracao.html").read_text(encoding="utf-8")
    assert 'id="tab-autenticador"' in html and 'id="sec-autenticador"' in html
    assert 'autenticador: "sec-autenticador"' in html
    assert 'ligarAppAutenticador(document.getElementById("sec-autenticador"))' in html
    # Os ids que a lógica compartilhada procura.
    for i in ("form-app-aut", "aa-sub", "aa-erro", "aa-senha", "aa-cadastro", "aa-instrucao",
              "aa-qr", "aa-segredo", "aa-link", "aa-codigo", "aa-acao"):
        assert f'id="{i}"' in html, i


def test_modal_e_aba_usam_a_mesma_logica():
    js = (RAIZ / "static" / "ui-common.js").read_text(encoding="utf-8")
    assert "function ligarAppAutenticador(raiz)" in js
    assert "ligarAppAutenticador(dlg)" in js
    assert 'location.href = "/configuracao?aba=autenticador"' in js


def test_rota_aceita_a_aba():
    main = (RAIZ / "app" / "main.py").read_text(encoding="utf-8")
    assert '"remocao", "autenticador", "api"):' in main
