"""A aba do navegador mostra o C dourado do CertGuard, não o A da Análise (14/11/2026)."""
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

RAIZ = Path(__file__).resolve().parent.parent


def test_favicon_e_o_c_do_certguard():
    r = TestClient(app).get("/favicon.ico")
    assert r.status_code == 200
    assert r.content == (RAIZ / "ico" / "certguard.ico").read_bytes()


def test_paginas_pedem_a_versao_nova_do_favicon():
    for html in (RAIZ / "templates").glob("*.html"):
        texto = html.read_text(encoding="utf-8")
        if 'rel="icon"' in texto:
            assert "favicon.ico?v=certguard-c-v1" in texto, html.name
