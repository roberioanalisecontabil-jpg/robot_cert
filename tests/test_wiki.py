"""Wiki do Certguard (app/rotas/wiki.py).

O que a página promete, e por isso o que se testa:
- sem sessão, nada do conteúdo sai: vai para o login e volta depois;
- cada papel vê os tutoriais dos módulos que alcança, pela matriz de
  permissões, e a URL de um módulo fora do alcance cai no índice;
- todo módulo listado tem o seu arquivo de conteúdo.
"""
import re
from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app import auth, permissoes, sessao_cookie
from app.rotas import wiki

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def _cabecalho(papel: str) -> dict:
    """Sessão no cookie, como o navegador manda: a cerca das páginas
    (`paginas_exigem_sessao_middleware`) só olha o cookie."""
    tok = auth.create_access_token({"sub": f"{papel}@x.com", "role": papel})
    return {"Cookie": f"{sessao_cookie.COOKIE_SESSAO}={tok}"}


@pytest.fixture
def client_wiki(api_key: str) -> TestClient:  # noqa: ARG001
    """Com API_KEY configurada: sem ela, o portal trata quem não mandou nada
    como identidade anônima, e é justamente esse caso que precisa ir ao login."""
    from app.main import app

    return TestClient(app)


def _matriz_user(monkeypatch: pytest.MonkeyPatch, **niveis: str) -> None:
    base = {m: permissoes.NIVEL_NENHUM for m in permissoes.MODULOS}
    base.update(niveis)
    monkeypatch.setattr(permissoes, "matriz_para_papel", lambda papel: dict(base) if papel == "user" else {m: permissoes.NIVEL_EDITAR for m in permissoes.MODULOS})


def test_sem_sessao_vai_para_o_login_e_volta(client_wiki: TestClient) -> None:
    r = client_wiki.get("/wiki-certguard?modulo=inicio", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/login?next=")
    assert unquote(r.headers["location"].split("next=", 1)[1]) == "/wiki-certguard?modulo=inicio"


def test_sem_sessao_nao_entrega_conteudo(client_wiki: TestClient) -> None:
    r = client_wiki.get("/wiki-certguard", follow_redirects=False)
    assert "wiki-indice" not in r.text


def test_admin_ve_todos_os_modulos(client_wiki: TestClient) -> None:
    r = client_wiki.get("/wiki-certguard", headers=_cabecalho("admin"))
    assert r.status_code == 200
    for m in wiki.MODULOS:
        assert f"?modulo={m.chave}" in r.text, m.chave


def test_colaborador_ve_so_o_que_alcanca(client_wiki: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _matriz_user(monkeypatch, inicio=permissoes.NIVEL_LER, acompanhamento=permissoes.NIVEL_EDITAR)
    r = client_wiki.get("/wiki-certguard", headers=_cabecalho("user"))
    assert r.status_code == 200
    visiveis = {m.chave for m in wiki.MODULOS if f"?modulo={m.chave}\"" in r.text}
    assert visiveis == {"primeiros-passos", "inicio", "acompanhamento", "bandeja"}


def test_modulo_fora_do_alcance_cai_no_indice(client_wiki: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _matriz_user(monkeypatch, inicio=permissoes.NIVEL_LER)
    r = client_wiki.get("/wiki-certguard?modulo=usuarios", headers=_cabecalho("user"), follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/wiki-certguard"


def test_modulo_inexistente_cai_no_indice(client_wiki: TestClient) -> None:
    r = client_wiki.get("/wiki-certguard?modulo=nao-existe", headers=_cabecalho("admin"), follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/wiki-certguard"


def test_sem_matriz_mostra_so_o_que_vale_para_todos(client_wiki: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def indisponivel(papel: str) -> dict:
        raise permissoes.PermissoesIndisponiveis("sem banco")

    monkeypatch.setattr(permissoes, "matriz_para_papel", indisponivel)
    r = client_wiki.get("/wiki-certguard", headers=_cabecalho("user"))
    visiveis = {m.chave for m in wiki.MODULOS if f"?modulo={m.chave}\"" in r.text}
    assert visiveis == {m.chave for m in wiki.MODULOS if m.permissao is None}


@pytest.mark.parametrize("modulo", [m.chave for m in wiki.MODULOS])
def test_cada_modulo_abre(client_wiki: TestClient, modulo: str) -> None:
    assert (TEMPLATES / "wiki" / f"{modulo}.html").is_file()
    r = client_wiki.get(f"/wiki-certguard?modulo={modulo}", headers=_cabecalho("admin"))
    assert r.status_code == 200
    assert 'aria-current="page"' in r.text


VIDEO = re.compile(r'video\("([\w-]+)"')


def test_cada_video_embutido_tem_arquivo_e_capa() -> None:
    """Um vídeo citado num tutorial sem o MP4 em static/wiki/ vira um player
    quebrado na página, sem erro em lugar nenhum."""
    estaticos = TEMPLATES.parent / "static" / "wiki"
    ids = {i for f in (TEMPLATES / "wiki").glob("*.html") for i in VIDEO.findall(f.read_text(encoding="utf-8"))}
    assert ids, "nenhum vídeo embutido nos tutoriais"
    for i in ids:
        assert (estaticos / f"{i}.mp4").is_file(), i
        assert (estaticos / f"{i}.jpg").is_file(), i


def test_pagina_com_video_mostra_o_player(client_wiki: TestClient) -> None:
    r = client_wiki.get("/wiki-certguard?modulo=bandeja", headers=_cabecalho("admin"))
    assert r.status_code == 200
    assert '<video controls preload="none"' in r.text
    assert 'src="/static/wiki/video-bandeja.mp4"' in r.text


def test_permissoes_dos_modulos_existem_na_matriz() -> None:
    """Uma chave de permissão digitada errado esconderia o tutorial de todos
    os que não são admin, sem erro nenhum."""
    for m in wiki.MODULOS:
        assert m.permissao is None or m.permissao in permissoes.MODULOS, m.chave
