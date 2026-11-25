"""Meu perfil (25/11/2026): nome, telefone e foto da própria conta."""
from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tests.test_seguranca_lote4 import ADMIN, FISCAL_OP, _h, banco  # noqa: F401

RAIZ = Path(__file__).resolve().parents[1]


def _png(w: int = 600, h: int = 400) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(b, "PNG")
    return b.getvalue()


def test_le_o_proprio_perfil(client: TestClient, banco) -> None:
    r = client.get("/api/perfil", headers=_h(*FISCAL_OP))
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["email"] == "fis@x.com" and p["foto_versao"] is None and p["microsoft"] is False


def test_salva_nome_em_maiusculas_e_telefone_so_digitos(client: TestClient, banco) -> None:
    r = client.put("/api/perfil", json={"nome": "  maria   da silva ", "telefone": "(82) 99876-5432"}, headers=_h(*FISCAL_OP))
    assert r.status_code == 200, r.text
    linha = next(u for u in banco.tabelas["users"] if u["email"] == "fis@x.com")
    assert linha["full_name"] == "MARIA DA SILVA" and linha["telefone"] == "82998765432"
    # Telefone vazio apaga; +55 é aceito e cortado.
    client.put("/api/perfil", json={"nome": "Maria", "telefone": "+55 82 3333-4444"}, headers=_h(*FISCAL_OP))
    assert linha["telefone"] == "8233334444"
    client.put("/api/perfil", json={"nome": "Maria", "telefone": ""}, headers=_h(*FISCAL_OP))
    assert linha["telefone"] is None


@pytest.mark.parametrize("corpo", [
    {"nome": "x", "telefone": ""},
    {"nome": "Maria", "telefone": "123"},
    {"nome": "Maria", "telefone": "(02) 99999-9999"},
    {"nome": "Ma\x07ria", "telefone": ""},
])
def test_recusa_nome_ou_telefone_invalido(client: TestClient, banco, corpo) -> None:
    assert client.put("/api/perfil", json=corpo, headers=_h(*FISCAL_OP)).status_code == 422


def test_so_mexe_na_propria_conta(client: TestClient, banco) -> None:
    antes = next(u for u in banco.tabelas["users"] if u["email"] == "admin@x.com")["full_name"]
    client.put("/api/perfil", json={"nome": "Outro Nome", "telefone": ""}, headers=_h(*FISCAL_OP))
    assert next(u for u in banco.tabelas["users"] if u["email"] == "admin@x.com")["full_name"] == antes


def test_foto_vira_jpeg_quadrado_sem_metadados(client: TestClient, banco) -> None:
    r = client.put("/api/perfil/foto", files={"arquivo": ("f.png", _png(), "image/png")}, headers=_h(*FISCAL_OP))
    assert r.status_code == 200, r.text
    linha = banco.tabelas["usuario_foto"][0]
    jpeg = base64.b64decode(linha["jpeg_b64"])
    with Image.open(io.BytesIO(jpeg)) as img:
        assert img.format == "JPEG" and img.size == (256, 256) and not img.getexif()
    lida = client.get("/api/perfil/foto", headers=_h(*FISCAL_OP))
    assert lida.status_code == 200 and lida.headers["content-type"] == "image/jpeg" and lida.content == jpeg
    assert client.get("/api/perfil", headers=_h(*FISCAL_OP)).json()["foto_versao"]
    # Cada um lê só a própria foto.
    assert client.get("/api/perfil/foto", headers=_h(*ADMIN)).status_code == 404
    assert client.delete("/api/perfil/foto", headers=_h(*FISCAL_OP)).status_code == 200
    assert client.get("/api/perfil/foto", headers=_h(*FISCAL_OP)).status_code == 404


def test_foto_recusa_o_que_nao_e_imagem(client: TestClient, banco) -> None:
    r = client.put("/api/perfil/foto", files={"arquivo": ("f.jpg", b"<html>nada</html>", "image/jpeg")}, headers=_h(*FISCAL_OP))
    assert r.status_code == 422


def test_sem_login_nao_entra(client: TestClient, banco) -> None:
    assert client.get("/api/perfil").status_code == 401
    assert client.put("/api/perfil", json={"nome": "Maria"}).status_code in (401, 403)


def test_pagina_e_menu_da_conta() -> None:
    html = (RAIZ / "templates" / "perfil.html").read_text(encoding="utf-8")
    for i in ("perfil-arquivo", "perfil-nome", "perfil-telefone", "form-senha", "perfil-senha-microsoft"):
        assert f'id="{i}"' in html, i
    barra = (RAIZ / "templates" / "_sidebar.html").read_text(encoding="utf-8")
    # Sair, tema e app autenticador moram no menu da conta, fora da navegação.
    menu = barra[barra.index('id="sidebar-conta"'):]
    for trecho in ('href="/perfil"', 'id="btn-theme-toggle"', 'data-action="app-autenticador"', 'data-action="logout"'):
        assert trecho in menu, trecho
    nav = barra[barra.index('<nav class="sidebar-nav">'):barra.index("</nav>")]
    assert 'data-action="logout"' not in nav


def test_migration_do_perfil() -> None:
    sql = (RAIZ / "supabase" / "migrations" / "20261125100000_perfil_usuario.sql").read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS telefone" in sql and "CREATE TABLE IF NOT EXISTS public.usuario_foto" in sql


def test_pagina_do_perfil_nao_acende_item_do_menu(client: TestClient, banco) -> None:
    r = client.get("/perfil", headers=_h(*FISCAL_OP))
    assert r.status_code == 200
    nav = r.text[r.text.index('<nav class="sidebar-nav">'):r.text.index("</nav>")]
    assert 'class="active"' not in nav
