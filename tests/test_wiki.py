"""Wiki do CertGuard (app/rotas/wiki.py).

O que a página promete, e por isso o que se testa:
- sem sessão, nada do conteúdo sai: vai para o login e volta depois;
- cada papel vê os tutoriais dos módulos que alcança, pela matriz de
  permissões, e a URL de um módulo fora do alcance cai no índice;
- todo módulo listado tem o seu arquivo de conteúdo;
- (25/11/2026) os módulos viraram temas com páginas por tarefa: os links
  antigos `?modulo=` redirecionam, a busca respeita a permissão e o "Veja
  também" só mostra o que a pessoa vê.
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


def _temas_no_indice(html: str) -> set[str]:
    return {m.chave for m in wiki.MODULOS if f'id="tema-{m.chave}"' in html}


def test_admin_ve_todos_os_modulos(client_wiki: TestClient) -> None:
    r = client_wiki.get("/wiki-certguard", headers=_cabecalho("admin"))
    assert r.status_code == 200
    assert _temas_no_indice(r.text) == {m.chave for m in wiki.MODULOS}
    for p in wiki.PAGINAS:
        assert f'?pagina={p.chave}"' in r.text, p.chave


def test_colaborador_ve_so_o_que_alcanca(client_wiki: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _matriz_user(monkeypatch, inicio=permissoes.NIVEL_LER, acompanhamento=permissoes.NIVEL_EDITAR)
    r = client_wiki.get("/wiki-certguard", headers=_cabecalho("user"))
    assert r.status_code == 200
    assert _temas_no_indice(r.text) == {"primeiros-passos", "inicio", "acompanhamento", "bandeja"}
    assert "?pagina=cadastrar-pessoas" not in r.text


def test_modulo_fora_do_alcance_cai_no_indice(client_wiki: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _matriz_user(monkeypatch, inicio=permissoes.NIVEL_LER)
    r = client_wiki.get("/wiki-certguard?pagina=cadastrar-pessoas", headers=_cabecalho("user"), follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/wiki-certguard"
    # Pelo link antigo também: a primeira página do tema, e dela o índice.
    r = client_wiki.get("/wiki-certguard?modulo=usuarios", headers=_cabecalho("user"), follow_redirects=False)
    assert r.headers["location"] == "/wiki-certguard?pagina=cadastrar-pessoas"
    r = client_wiki.get(r.headers["location"], headers=_cabecalho("user"), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/wiki-certguard"


def test_modulo_inexistente_cai_no_indice(client_wiki: TestClient) -> None:
    for url in ("/wiki-certguard?modulo=nao-existe", "/wiki-certguard?pagina=nao-existe"):
        r = client_wiki.get(url, headers=_cabecalho("admin"), follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/wiki-certguard"


def test_sem_matriz_mostra_so_o_que_vale_para_todos(client_wiki: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def indisponivel(papel: str) -> dict:
        raise permissoes.PermissoesIndisponiveis("sem banco")

    monkeypatch.setattr(permissoes, "matriz_para_papel", indisponivel)
    r = client_wiki.get("/wiki-certguard", headers=_cabecalho("user"))
    assert _temas_no_indice(r.text) == {m.chave for m in wiki.MODULOS if m.permissao is None}


@pytest.mark.parametrize("pagina", [p.chave for p in wiki.PAGINAS])
def test_cada_pagina_abre(client_wiki: TestClient, pagina: str) -> None:
    assert (TEMPLATES / "wiki" / f"{pagina}.html").is_file()
    r = client_wiki.get(f"/wiki-certguard?pagina={pagina}", headers=_cabecalho("admin"))
    assert r.status_code == 200
    assert 'aria-current="page"' in r.text
    assert 'class="wiki-busca"' in r.text  # a pesquisa também no tutorial


def test_todo_tema_tem_pagina_e_todo_tutorial_tem_dono() -> None:
    assert {p.tema for p in wiki.PAGINAS} == {m.chave for m in wiki.MODULOS}
    arquivos = {f.stem for f in (TEMPLATES / "wiki").glob("*.html")} - {"_macros"}
    assert arquivos == {p.chave for p in wiki.PAGINAS}


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
    r = client_wiki.get("/wiki-certguard?pagina=bandeja-instalar", headers=_cabecalho("admin"))
    assert r.status_code == 200
    assert '<video controls preload="none"' in r.text
    assert 'src="/static/wiki/video-bandeja.mp4"' in r.text


def test_permissoes_dos_modulos_existem_na_matriz() -> None:
    """Uma chave de permissão digitada errado esconderia o tutorial de todos
    os que não são admin, sem erro nenhum."""
    for m in wiki.MODULOS:
        assert m.permissao is None or m.permissao in permissoes.MODULOS, m.chave


# P9-1 e P9-2 (revisão de 21/11/2026)

def test_p9_1_prints_da_wiki_exigem_sessao(client_wiki: TestClient) -> None:
    for caminho in ("/static/wiki/prints.json", "/static//wiki/prints.json", "/static/WIKI/prints.json"):
        r = client_wiki.get(caminho, follow_redirects=False)
        assert r.status_code in (401, 303, 404), caminho
        assert '"w"' not in r.text, caminho
    assert client_wiki.get("/static/wiki/prints.json", headers=_cabecalho("user")).status_code == 200


def test_p9_1_resto_do_static_continua_publico(client_wiki: TestClient) -> None:
    # A tela de login usa o /static sem sessão.
    assert client_wiki.get("/static/wiki.css").status_code == 200


def test_p9_2_sem_matriz_o_modulo_pedido_mostra_aviso_e_nao_redireciona(
    client_wiki: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def indisponivel(papel: str) -> dict:
        raise permissoes.PermissoesIndisponiveis("sem banco")

    monkeypatch.setattr(permissoes, "matriz_para_papel", indisponivel)
    r = client_wiki.get("/wiki-certguard?pagina=achar-certificado", headers=_cabecalho("user"), follow_redirects=False)
    assert r.status_code == 200
    assert "Não deu para conferir suas permissões agora" in r.text


# Prints de tutorial fora do alcance (lacunas menores, 22/11/2026)

def test_print_de_modulo_fora_do_alcance_da_404(client_wiki: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Quem não alcança Usuários não abre, pela URL, os prints do tutorial de
    Usuários; nem pelas variações de caminho que o StaticFiles aceita."""
    _matriz_user(monkeypatch, inicio=permissoes.NIVEL_LER)
    for caminho in ("/static/wiki/usuarios-importar.png", "/static//wiki/usuarios-importar.png",
                    "/static/WIKI/Usuarios-Importar.png", "/static/x/../wiki/usuarios-importar.png"):
        r = client_wiki.get(caminho, headers=_cabecalho("user"), follow_redirects=False)
        assert r.status_code == 404, caminho
    # O admin alcança Usuários e abre o print.
    assert client_wiki.get("/static/wiki/usuarios-importar.png", headers=_cabecalho("admin")).status_code == 200


def test_print_de_modulo_alcancado_ou_de_todos_abre(client_wiki: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _matriz_user(monkeypatch, inicio=permissoes.NIVEL_LER)
    cab = _cabecalho("user")
    assert client_wiki.get("/static/wiki/inicio-busca.png", headers=cab).status_code == 200
    # Print citado em dois tutoriais (Início e Instalador): basta alcançar um.
    assert client_wiki.get("/static/wiki/inicio-sieg-confirmar.png", headers=cab).status_code == 200
    # Bandeja vale para todos; o manifesto não é de módulo nenhum.
    assert client_wiki.get("/static/wiki/video-bandeja.jpg", headers=cab).status_code == 200
    assert client_wiki.get("/static/wiki/prints.json", headers=cab).status_code == 200


# Páginas por tarefa, links antigos, busca e "Veja também" (25/11/2026)

@pytest.mark.parametrize("modulo", [m.chave for m in wiki.MODULOS])
def test_link_antigo_do_modulo_vai_para_a_primeira_pagina_do_tema(client_wiki: TestClient, modulo: str) -> None:
    r = client_wiki.get(f"/wiki-certguard?modulo={modulo}", headers=_cabecalho("admin"), follow_redirects=False)
    assert r.status_code == 303
    primeira = next(p for p in wiki.PAGINAS if p.tema == modulo)
    assert r.headers["location"] == f"/wiki-certguard?pagina={primeira.chave}"


# Âncoras que os links antigos usavam (?modulo=X#ancora) e as que os
# tutoriais citavam entre si: o wiki.js leva da primeira página do tema à
# página que tem a âncora, pelo mapa que a rota põe no artigo.
@pytest.mark.parametrize("tema,ancora,pagina", [
    ("inicio", "instalar", "instalar-certificado"),
    ("inicio", "sieg", "incluir-no-sieg"),
    ("primeiros-passos", "cadastrar-app", "app-autenticador"),
    ("primeiros-passos", "codigo-nao-chegou", "entrar-no-portal"),
    ("api", "bloqueadas", "api-consultas"),
    ("configuracao", "forcar-leitura", "pastas-e-agente"),
    ("usuarios", "departamentos", "departamentos"),
])
def test_ancora_antiga_aponta_a_pagina_nova(client_wiki: TestClient, tema: str, ancora: str, pagina: str) -> None:
    assert f'id="{ancora}"' in (TEMPLATES / "wiki" / f"{pagina}.html").read_text(encoding="utf-8")
    cab = _cabecalho("admin")
    r = client_wiki.get(f"/wiki-certguard?modulo={tema}", headers=cab, follow_redirects=False)
    r = client_wiki.get(r.headers["location"], headers=cab)
    assert r.status_code == 200
    assert f'"{ancora}": "{pagina}"' in r.text


def test_toda_ancora_de_um_tema_tem_uma_pagina_so() -> None:
    """Dentro de um tema as âncoras não se repetem (vieram de um arquivo só);
    se duas páginas do mesmo tema tivessem a mesma, o link antigo ficaria ambíguo."""
    for tema in {p.tema for p in wiki.PAGINAS}:
        ids = [i for p in wiki.PAGINAS if p.tema == tema
               for i in re.findall(r'<h[23] id="([^"]+)"', (TEMPLATES / "wiki" / f"{p.chave}.html").read_text(encoding="utf-8"))]
        assert len(ids) == len(set(ids)), tema


def test_links_internos_da_wiki_resolvem() -> None:
    """Todo link entre tutoriais aponta uma página que existe e, com âncora,
    uma âncora que está nela. Nenhum tutorial usa mais o ?modulo= antigo."""
    for f in (TEMPLATES / "wiki").glob("*.html"):
        texto = f.read_text(encoding="utf-8")
        assert "?modulo=" not in texto, f.name
        for pagina, ancora in re.findall(r'/wiki-certguard\?pagina=([\w-]+)(?:#([\w-]+))?', texto):
            alvo = TEMPLATES / "wiki" / f"{pagina}.html"
            assert alvo.is_file(), (f.name, pagina)
            if ancora:
                assert f'id="{ancora}"' in alvo.read_text(encoding="utf-8"), (f.name, pagina, ancora)
        for ancora in re.findall(r'href="#([\w-]+)"', texto):
            assert f'id="{ancora}"' in texto, (f.name, ancora)


def _paginas_da_busca(pergunta: str, paginas=None) -> list[str]:
    return [r["pagina"].chave for r in wiki.buscar(pergunta, list(paginas or wiki.PAGINAS))]


def test_busca_responde_as_perguntas_de_exemplo() -> None:
    assert _paginas_da_busca("como instalo um certificado?")[0] == "instalar-certificado"
    r = wiki.buscar("não chega o código no e-mail", list(wiki.PAGINAS))[0]
    assert r["pagina"].chave == "entrar-no-portal"
    assert r["url"] == "/wiki-certguard?pagina=entrar-no-portal#codigo-nao-chegou"
    assert r["secao"] == "O código não chegou ou expirou" and r["trecho"]


def test_busca_ignora_acento_e_maiusculas() -> None:
    assert _paginas_da_busca("CÓDIGO NÃO CHEGOU") == _paginas_da_busca("codigo nao chegou")
    assert _paginas_da_busca("instalação")[:3] == _paginas_da_busca("INSTALACAO")[:3]
    assert "custodia" in _paginas_da_busca("custodia")


def test_busca_ignora_palavras_vazias() -> None:
    assert wiki.buscar("como o de para que", list(wiki.PAGINAS)) == []


def test_busca_usa_sinonimos() -> None:
    """Os tutoriais não dizem "A1"; pelo sinônimo, a busca acha certificado
    (e "baixar" acha instalar)."""
    assert not any("a1" in s.pal_texto for s in wiki.SECOES)
    assert _paginas_da_busca("baixar o a1 no computador")[0] == "instalar-certificado"
    assert _paginas_da_busca("instalar pfx")[0] == "instalar-certificado"


def test_busca_pontua_titulo_acima_do_texto() -> None:
    r = wiki.buscar("departamento", list(wiki.PAGINAS))
    assert r[0]["pagina"].chave == "departamentos"


def test_busca_so_acha_o_que_a_pessoa_ve(client_wiki: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _matriz_user(monkeypatch, inicio=permissoes.NIVEL_LER)
    r = client_wiki.get("/wiki-certguard?q=departamento+gestor", headers=_cabecalho("user"))
    assert r.status_code == 200
    assert "?pagina=departamentos" not in r.text and "?pagina=cadastrar-pessoas" not in r.text
    # O admin acha a mesma coisa.
    r = client_wiki.get("/wiki-certguard?q=departamento+gestor", headers=_cabecalho("admin"))
    assert "/wiki-certguard?pagina=departamentos#" in r.text


def test_busca_pela_pagina_mostra_titulo_secao_e_trecho(client_wiki: TestClient) -> None:
    r = client_wiki.get("/wiki-certguard?q=n%C3%A3o+chega+o+c%C3%B3digo+no+e-mail", headers=_cabecalho("admin"))
    assert r.status_code == 200
    assert 'href="/wiki-certguard?pagina=entrar-no-portal#codigo-nao-chegou"' in r.text
    assert "Entrar e sair do portal" in r.text and "O código não chegou ou expirou" in r.text
    assert 'class="wiki-resultado__trecho"' in r.text
    r = client_wiki.get("/wiki-certguard?q=zzzqqq", headers=_cabecalho("admin"))
    assert "Nada encontrado" in r.text


def test_busca_escapa_a_pergunta(client_wiki: TestClient) -> None:
    r = client_wiki.get("/wiki-certguard?q=%3Cscript%3Ealert(1)%3C/script%3E", headers=_cabecalho("admin"))
    assert "<script>alert(1)" not in r.text


def test_veja_tambem_mesmo_tema_primeiro_e_so_o_visivel() -> None:
    atual = next(p for p in wiki.PAGINAS if p.chave == "instalar-certificado")
    rel = wiki.relacionadas(atual, list(wiki.PAGINAS))
    assert len(rel) == 3 and all(p.tema == "inicio" for p in rel) and atual not in rel
    # Página de tema com uma página só: completa por termos em comum, só do que vê.
    historico = next(p for p in wiki.PAGINAS if p.chave == "historico")
    visiveis = [p for p in wiki.PAGINAS if p.tema in {"historico", "vencidos", "primeiros-passos"}]
    rel = wiki.relacionadas(historico, visiveis)
    assert rel and all(p in visiveis for p in rel) and historico not in rel


def test_pagina_mostra_veja_tambem_e_o_proximo_tema(client_wiki: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _matriz_user(monkeypatch, inicio=permissoes.NIVEL_LER)
    r = client_wiki.get("/wiki-certguard?pagina=exportar-e-avisos", headers=_cabecalho("user"))
    assert r.status_code == 200
    assert "Veja também" in r.text
    # Última página do Início para quem não vê Dashboard..Carteiras: o próximo é a Bandeja.
    assert "Próximo tema · Bandeja CertGuard Análise" in r.text
    assert "?pagina=bandeja-entrar" in r.text
    assert "?pagina=ler-dashboard" not in r.text and "?pagina=departamentos" not in r.text
