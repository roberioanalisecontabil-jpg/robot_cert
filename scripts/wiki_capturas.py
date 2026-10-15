"""Refaz os prints da wiki (/wiki-certguard) a partir de um portal de demonstração.

Lê scripts/wiki_capturas.json, entra no portal com uma conta por papel, faz os
passos de cada captura e grava static/wiki/<id>.png. No fim reescreve
static/wiki/prints.json com largura, altura e versão de TODAS as imagens da
pasta (inclusive as capturadas à mão), que é o que a wiki lê.

O portal de demonstração mora em scripts/wiki_demo/ (dados 100% inventados):
    .venv\\Scripts\\python.exe scripts\\wiki_demo\\seed_wiki.py     # recria o banco certguard_wiki
    scripts\\wiki_demo\\subir_portal_wiki.ps1                       # portal em 127.0.0.1:8091
    # tela do código de login: .venv\\Scripts\\python.exe scripts\\wiki_demo\\servir_wiki.py 8091 --codigo

Uso (a senha vem do ambiente, nunca do código nem da linha de comando; o seed
a grava em scripts/wiki_demo/credenciais-demo.txt, fora do git):
    $env:WIKI_SENHA = "<senha comum das contas de demonstração>"
    .venv\\Scripts\\python.exe scripts/wiki_capturas.py --base http://127.0.0.1:8091
    .venv\\Scripts\\python.exe scripts/wiki_capturas.py --base ... --so inicio-lista,dup-resumo
    # tela do código de login: portal subido com LOGIN_EXIGE_CODIGO=1
    .venv\\Scripts\\python.exe scripts/wiki_capturas.py --base ... --login-codigo
    # só reescrever o prints.json (depois de pôr um print manual na pasta)
    .venv\\Scripts\\python.exe scripts/wiki_capturas.py --so-manifesto

Use SEMPRE um portal de demonstração com banco recém-semeado: alguns prints
gravam estado (a seleção do Acompanhamento) e a ordem da lista importa.
Botões de ações irreversíveis ficam em "proibidos" no JSON e o script se
recusa a clicar neles.

Código de saída: 0 se todas as capturas pedidas saíram, 1 se alguma falhou.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import struct
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LISTA_PADRAO = REPO / "scripts" / "wiki_capturas.json"
SAIDA_PADRAO = REPO / "static" / "wiki"

# Contas da base de demonstração (seed da wiki); trocáveis por variável.
EMAILS_PADRAO = {
    "admin": "admin.demo@exemplo.com",
    "gestor": "gestor.demo@exemplo.com",
    "colaborador": "colaborador.demo@exemplo.com",
}

ESPERA_MS = 15000

# Nada se mexendo na hora do clique nem da foto. O cursor piscando também
# sai, senão dois prints da mesma tela dariam versões diferentes. A tarja
# cobre o que está em "ocultar".
CSS_DA_CAPTURA = """
*, *::before, *::after { transition: none !important; animation: none !important; caret-color: transparent !important; }
.wiki-tarja { background: repeating-linear-gradient(135deg, #c9ced6 0 8px, #bcc2cc 8px 16px) !important;
  color: transparent !important; -webkit-text-fill-color: transparent !important; text-shadow: none !important; }
.wiki-tarja * { visibility: hidden !important; }
.wiki-tarja::placeholder { color: transparent !important; }
.wiki-tarja-img { filter: contrast(0) !important; }
"""

# Antes de qualquer script da página: tema claro fixo (o portal lê a escolha
# do localStorage) e o CSS acima assim que o documento existir. No instante
# do init script ainda não há <html> para receber o <style>.
INICIO_DA_PAGINA = (
    "(() => {"
    " try { localStorage.setItem('cert_robot_theme', 'light'); } catch (e) {}"
    " const css = " + json.dumps(CSS_DA_CAPTURA) + ";"
    " document.addEventListener('DOMContentLoaded', () => {"
    "   const s = document.createElement('style'); s.textContent = css; document.head.appendChild(s); });"
    "})();"
)


# Tudo o que o portal mostra enquanto busca dados: overlay de carregamento,
# linhas-esqueleto e regiões marcadas como ocupadas. Só conta o que está visível.
SEM_CARREGANDO = r"""
() => {
  const visivel = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
    && getComputedStyle(el).visibility !== "hidden";
  const sinais = ".global-loading-overlay.is-visible, .table-loading-overlay.is-visible, "
    + ".cg-skeleton-row, .notif-loading, [aria-busy='true']";
  return ![...document.querySelectorAll(sinais)].some(visivel);
}
"""


class FalhaDeCaptura(Exception):
    pass


# ---------------------------------------------------------------- lista


def carregar_lista(caminho: Path) -> dict:
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    ids = [c["id"] for c in dados["capturas"]]
    repetidos = {i for i in ids if ids.count(i) > 1}
    if repetidos:
        raise SystemExit(f"ids repetidos em {caminho.name}: {sorted(repetidos)}")
    return dados


# ---------------------------------------------------------------- manifesto


def _dimensoes_png(dados: bytes) -> tuple[int, int]:
    # Cabeçalho IHDR: não precisa de Pillow para ler largura e altura.
    if dados[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("não é PNG")
    return struct.unpack(">II", dados[16:24])


def escrever_manifesto(saida: Path) -> dict:
    """Todas as imagens da pasta, não só as desta rodada: um print manual posto
    na pasta também precisa entrar, senão a wiki mostra o aviso no lugar."""
    manifesto = {}
    for png in sorted(saida.glob("*.png")):
        dados = png.read_bytes()
        w, h = _dimensoes_png(dados)
        manifesto[png.stem] = {"w": w, "h": h, "v": hashlib.sha256(dados).hexdigest()[:8]}
    (saida / "prints.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return manifesto


# ---------------------------------------------------------------- imagem


def otimizar_png(caminho: Path) -> None:
    """Paleta de 256 cores sem pontilhado: tela de sistema tem poucas cores e o
    texto continua nítido; costuma cortar o arquivo a menos da metade. Só troca
    se ficar menor. Sem Pillow, fica o PNG do navegador."""
    try:
        from PIL import Image
    except ImportError:
        return
    original = caminho.read_bytes()
    with Image.open(io.BytesIO(original)) as im:
        rgb = im.convert("RGB")
        pal = rgb.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        buf = io.BytesIO()
        pal.save(buf, format="PNG", optimize=True)
    if buf.tell() < len(original):
        caminho.write_bytes(buf.getvalue())


# ---------------------------------------------------------------- navegador


def esperar_portal(base: str, segundos: int = 60) -> None:
    fim = time.time() + segundos
    while True:
        try:
            urllib.request.urlopen(base + "/login", timeout=3)
            return
        except Exception:  # noqa: BLE001
            if time.time() > fim:
                raise SystemExit(f"portal não respondeu em {base}/login")
            time.sleep(1)


def assentar(page, rede: bool = True, carregando_ok: bool = False) -> list[str]:
    """Espera a rede parar, os indicadores de carregamento sumirem e as fontes
    chegarem. Devolve avisos em vez de falhar: quem decide é a conferência."""
    avisos = []
    if rede:
        try:
            page.wait_for_load_state("networkidle", timeout=ESPERA_MS)
        except Exception:  # noqa: BLE001
            avisos.append("a rede não assentou")
    if not carregando_ok:
        try:
            page.wait_for_function(SEM_CARREGANDO, timeout=ESPERA_MS)
        except Exception:  # noqa: BLE001
            avisos.append("indicador de carregamento ainda visível")
    page.evaluate("document.fonts ? document.fonts.ready.then(() => true) : true")
    page.wait_for_timeout(250)  # um quadro a mais para o layout final
    return avisos


def novo_contexto(navegador):
    ctx = navegador.new_context(
        viewport={"width": 1440, "height": 900},
        device_scale_factor=1,
        color_scheme="light",
        reduced_motion="reduce",
        locale="pt-BR",
        timezone_id="America/Sao_Paulo",
        # A CSP do portal barra <style> e eval injetados; sem isto o CSS que
        # congela animações e a tarja de "ocultar" não pegariam.
        bypass_csp=True,
    )
    ctx.add_init_script(INICIO_DA_PAGINA)
    return ctx


def nova_pagina(ctx):
    page = ctx.new_page()
    # confirm/alert nativos: dispensados, nunca aceitos (um "OK" poderia
    # confirmar uma ação de verdade).
    page.on("dialog", lambda d: d.dismiss())
    page.set_default_timeout(ESPERA_MS)
    return page


def entrar(navegador, base: str, email: str, senha: str):
    """Login pelo formulário, como uma pessoa: a sessão fica no cookie do contexto."""
    ctx = novo_contexto(navegador)
    page = nova_pagina(ctx)
    page.goto(base + "/login")
    page.fill("#email", email)
    page.fill("#password", senha)
    page.click("#btn-entrar")
    try:
        page.wait_for_url(lambda u: "/login" not in u, timeout=ESPERA_MS)
    except Exception as e:  # noqa: BLE001
        erro = page.locator("#login-error").inner_text() if page.locator("#login-error").is_visible() else ""
        codigo = page.locator("#view-codigo-login").is_visible()
        motivo = "o portal pediu o código (LOGIN_EXIGE_CODIGO ligado)" if codigo else (erro or str(e))
        raise SystemExit(f"não entrou como {email}: {motivo}") from e
    page.close()
    return ctx


# ---------------------------------------------------------------- passos


def _resolver(page, valor: str, senha: str) -> str:
    """{senha}, {texto:<sel>}, {palavra:<sel>} e {attr:<sel>@<atributo>}: o
    texto sai dos dados da própria tela, para o print não depender de um nome
    fixo do seed."""
    valor = valor.replace("{senha}", senha)
    m = re.fullmatch(r"\{(texto|palavra|attr):(.+)\}", valor)
    if not m:
        return valor
    if m.group(1) == "attr":
        # Atributo, quando o texto visível traz junto rótulo de leitor de tela.
        sel, atributo = m.group(2).rsplit("@", 1)
        texto = (page.locator(sel).first.get_attribute(atributo) or "").strip()
    else:
        texto = page.locator(m.group(2)).first.inner_text().strip()
    if m.group(1) == "palavra":
        texto = re.split(r"\s+", texto)[0].strip(".,;:-")
    if not texto:
        raise FalhaDeCaptura(f"sem texto em {m.group(2)}")
    return texto


def _conferir_proibido(loc, proibidos: list[str]) -> None:
    proibido = loc.evaluate(
        "(el, sels) => sels.find((s) => { try { return !!el.closest(s); } catch (e) { return false; } }) || null",
        proibidos,
    )
    if proibido:
        raise FalhaDeCaptura(f"recusado: clique em {proibido} (ação irreversível)")


def executar(page, passos: list, ctx_execucao: dict) -> None:
    for n, passo in enumerate(passos, 1):
        if isinstance(passo, str):
            raise FalhaDeCaptura(f"passo em texto livre (captura manual?): {passo}")
        try:
            _executar_passo(page, passo, ctx_execucao)
        except FalhaDeCaptura:
            raise
        except Exception as e:  # noqa: BLE001
            # Diz qual passo travou: a mensagem do Playwright sozinha não diz.
            primeira = str(e).splitlines()[0][:160]
            raise FalhaDeCaptura(f"passo {n} ({passo['acao']} {passo.get('sel') or ''}): {primeira}") from e


def _executar_passo(page, passo: dict, ctx_execucao: dict) -> None:
    senha = ctx_execucao["senha"]
    acao = passo["acao"]
    sel = passo.get("sel")
    loc = page.locator(sel).first if sel else None
    if acao == "esperar":
        loc.wait_for(state=passo.get("estado", "visible"))
    elif acao == "esperar_texto":
        loc.wait_for(state="visible")
        page.wait_for_function(
            "([sel, t]) => { const el = document.querySelector(sel); const s = (el && el.textContent || '').trim();"
            " return !!s && (!t || s.includes(t)); }",
            arg=[sel, passo.get("texto") or ""],
        )
    elif acao == "esperar_js":
        # Como função, não como texto solto: a CSP do portal barra eval.
        page.wait_for_function("() => (" + passo["js"] + ")")
    elif acao == "clicar":
        loc.wait_for(state="visible")
        _conferir_proibido(loc, ctx_execucao["proibidos"])
        loc.click()
    elif acao == "preencher":
        valor = _resolver(page, passo["valor"], senha)
        if passo.get("palavras"):
            # Nome inteiro não cabe no campo de busca e o print mostraria o fim.
            valor = " ".join(valor.split()[: passo["palavras"]])
        loc.fill(valor)
    elif acao == "selecionar":
        valor = passo["valor"]
        if valor == "{outro}":
            # Qualquer opção diferente da atual: basta a tela mudar.
            valor = loc.evaluate("(s) => [...s.options].map((o) => o.value).find((v) => v !== s.value)")
        loc.select_option(valor)
    elif acao == "marcar":
        # As primeiras N caixas ainda desmarcadas e habilitadas.
        faltam = passo.get("n", 1)
        todas = page.locator(sel)
        for i in range(todas.count()):
            caixa = todas.nth(i)
            if faltam and caixa.is_enabled() and not caixa.is_checked():
                caixa.check()
                faltam -= 1
        if faltam:
            raise FalhaDeCaptura(f"faltaram {faltam} caixas para marcar em {sel}")
    elif acao == "rolar":
        loc.wait_for(state="attached")
        loc.evaluate("(el, b) => el.scrollIntoView({block: b})", passo.get("bloco", "center"))
    elif acao == "mouse":
        loc.hover()
        ctx_execucao["mouse_usado"] = True
    elif acao == "segurar":
        # Prende a resposta até a captura: estados de "carregando" que na
        # vida real duram um instante.
        page.route(passo["url"], lambda rota: ctx_execucao["presas"].append(rota))
        ctx_execucao["segurando"] = True
    elif acao == "js":
        page.evaluate("() => {" + passo["js"] + "}")
    elif acao == "pausa":
        page.wait_for_timeout(passo["ms"])
    elif acao == "passos_de":
        outra = ctx_execucao["por_id"][passo["id"]]
        executar(page, outra["passos"], ctx_execucao)
    else:
        raise FalhaDeCaptura(f"ação desconhecida: {acao}")




def _ocultar(page, seletores: list[str]) -> None:
    for sel in seletores:
        page.locator(sel).evaluate_all(
            """(els) => els.forEach((el) => {
                 if (["INPUT", "TEXTAREA"].includes(el.tagName)) el.value = "";
                 el.classList.add(["IMG", "CANVAS", "svg", "VIDEO"].includes(el.tagName) ? "wiki-tarja-img" : "wiki-tarja");
               })"""
        )


def _problemas_visiveis(page, alvo) -> list[str]:
    """O que denuncia um print ruim: toast de erro, 'Carregando' no recorte."""
    problemas = []
    if page.locator(".toast-item.toast-error").filter(has_text=re.compile(".")).count():
        if page.locator(".toast-item.toast-error").first.is_visible():
            problemas.append("toast de erro: " + page.locator(".toast-item.toast-error").first.inner_text().strip()[:120])
    texto = alvo.inner_text() if alvo is not None else page.locator("body").inner_text()
    if "Carregando" in texto:
        problemas.append("'Carregando' no recorte")
    return problemas


def _responder(corpo: str):
    # Fábrica, e não lambda com valor padrão: o Playwright passa (rota, pedido)
    # e o pedido ocuparia o lugar do corpo.
    def responder(rota) -> None:
        rota.fulfill(status=200, content_type="application/json", body=corpo)
    return responder


def _foto_com_folga(page, alvo, destino: Path, margem: int, altura_max: int | None) -> None:
    """Recorte com folga em volta (seção sem borda própria fica com o texto
    encostado na beirada) e/ou com altura limitada (tabela longa vira um
    print do tamanho de uma tela). Rola até o topo do elemento e recorta da
    janela visível."""
    alvo.evaluate("(el, m) => window.scrollBy(0, el.getBoundingClientRect().top - m)", margem)
    page.wait_for_timeout(100)
    c = alvo.bounding_box()
    vw, vh = page.viewport_size["width"], page.viewport_size["height"]
    x0, y0 = max(0, c["x"] - margem), max(0, c["y"] - margem)
    x1, y1 = min(vw, c["x"] + c["width"] + margem), min(vh, c["y"] + c["height"] + margem)
    if altura_max:
        y1 = min(y1, y0 + altura_max)
    page.screenshot(path=str(destino), clip={"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0},
                    animations="disabled", caret="hide")


def capturar(page, base: str, cap: dict, saida: Path, ctx_execucao: dict) -> list[str]:
    ctx_execucao["presas"] = []
    ctx_execucao["segurando"] = False
    ctx_execucao["mouse_usado"] = False
    for sim in cap.get("simular") or []:
        # Responde no lugar do servidor só nesta página, para mostrar um estado
        # que a base de demonstração não tem (ex.: estação sem bandeja). Antes
        # do goto: a tela pede esses dados ao abrir.
        page.route(sim["url"], _responder(json.dumps(sim["json"], ensure_ascii=False)))
    page.goto(base + cap["url"])
    page.add_style_tag(content=CSS_DA_CAPTURA)  # garantia, caso o init script chegue tarde
    if cap["papel"] != "anonimo" and "/login" in page.url:
        raise FalhaDeCaptura("caiu na tela de login (sessão perdida)")
    avisos = assentar(page)
    executar(page, cap["passos"], ctx_execucao)
    carregando_ok = bool(cap.get("carregando_ok"))
    avisos += assentar(page, rede=not ctx_execucao["segurando"], carregando_ok=carregando_ok)
    _ocultar(page, cap.get("ocultar") or [])
    if not ctx_execucao.get("mouse_usado"):
        # O cursor fica onde foi o último clique e deixa linha ou item de
        # menu destacado; no canto não pega nada.
        page.mouse.move(0, 0)

    destino = saida / f"{cap['id']}.png"
    alvo = None
    if cap.get("recorte"):
        alvo = page.locator(cap["recorte"]).first
        alvo.wait_for(state="visible")
        caixa = alvo.bounding_box()
        if not caixa or caixa["width"] < 10 or caixa["height"] < 10:
            raise FalhaDeCaptura(f"recorte vazio: {cap['recorte']}")
    if not carregando_ok:
        avisos += _problemas_visiveis(page, alvo)
    if not cap.get("manter_toast"):
        # Toast de sucesso de um passo (ex.: Revalidar) cobre a tela que o
        # print quer mostrar; só fica quando ele é o assunto.
        page.evaluate("() => document.querySelectorAll('.toast-item').forEach((t) => t.remove())")
    if alvo is not None and (cap.get("margem") or cap.get("altura_max")):
        _foto_com_folga(page, alvo, destino, cap.get("margem") or 0, cap.get("altura_max"))
    elif alvo is not None:
        alvo.screenshot(path=str(destino), animations="disabled", caret="hide")
    else:
        page.screenshot(path=str(destino), animations="disabled", caret="hide")
    otimizar_png(destino)
    for rota in ctx_execucao["presas"]:
        try:
            rota.abort()
        except Exception:  # noqa: BLE001
            pass
    return avisos


# ---------------------------------------------------------------- principal


def main() -> int:
    ap = argparse.ArgumentParser(description="Refaz os prints da wiki a partir de um portal de demonstração.")
    ap.add_argument("--base", default=os.environ.get("WIKI_BASE", "http://127.0.0.1:8091"),
                    help="URL do portal de demonstração (ou WIKI_BASE)")
    ap.add_argument("--so", default="", help="ids separados por vírgula; sem isto, todas as automáticas")
    ap.add_argument("--login-codigo", action="store_true",
                    help="só os prints da tela do código (portal com LOGIN_EXIGE_CODIGO=1)")
    ap.add_argument("--lista", type=Path, default=LISTA_PADRAO)
    ap.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    ap.add_argument("--so-manifesto", action="store_true", help="só reescreve prints.json com o que está na pasta")
    ap.add_argument("--mostrar", action="store_true", help="abre o navegador visível (para ajustar passos)")
    ap.add_argument("--depurar", type=Path, help="pasta onde salvar a tela de cada captura que falhar")
    args = ap.parse_args()

    args.saida.mkdir(parents=True, exist_ok=True)
    if args.so_manifesto:
        print(f"prints.json: {len(escrever_manifesto(args.saida))} imagens")
        return 0

    senha = os.environ.get("WIKI_SENHA", "")
    if not senha:
        raise SystemExit("defina WIKI_SENHA com a senha das contas de demonstração")
    emails = {p: os.environ.get(f"WIKI_EMAIL_{p.upper()}", e) for p, e in EMAILS_PADRAO.items()}

    dados = carregar_lista(args.lista)
    por_id = {c["id"]: c for c in dados["capturas"]}
    pedidos = [i.strip() for i in args.so.split(",") if i.strip()]
    desconhecidos = [i for i in pedidos if i not in por_id]
    if desconhecidos:
        raise SystemExit(f"ids que não estão na lista: {desconhecidos}")

    fila = []
    for cap in dados["capturas"]:  # a ordem da lista, mesmo com --so
        if pedidos and cap["id"] not in pedidos:
            continue
        if cap.get("manual"):
            if pedidos:
                print(f"  -- {cap['id']}: manual, pulado ({cap.get('obs', '')[:80]})")
            continue
        if bool(cap.get("login_codigo")) != args.login_codigo:
            if pedidos:
                print(f"  -- {cap['id']}: " + ("só com --login-codigo" if cap.get("login_codigo") else "não roda com --login-codigo"))
            continue
        fila.append(cap)

    esperar_portal(args.base)
    from playwright.sync_api import sync_playwright

    ctx_execucao = {"senha": senha, "proibidos": dados.get("proibidos", []), "por_id": por_id}
    falhas, com_aviso = [], []
    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=not args.mostrar)
        contextos = {}
        for cap in fila:
            papel = cap["papel"]
            try:
                if papel == "anonimo":
                    ctx = novo_contexto(navegador)  # sem cookie nenhum, a cada print
                else:
                    # "conta": outra pessoa do mesmo papel, para um estado que
                    # as contas .demo não têm (senha provisória, sem computador).
                    email = cap.get("conta") or emails[papel]
                    if email not in contextos:
                        contextos[email] = entrar(navegador, args.base, email, senha)
                    ctx = contextos[email]
                page = nova_pagina(ctx)
                try:
                    avisos = capturar(page, args.base, cap, args.saida, ctx_execucao)
                except Exception:
                    if args.depurar:
                        args.depurar.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(args.depurar / f"{cap['id']}.png"), full_page=True)
                    raise
                finally:
                    # Fecha sem confirmar nada: modais abertos morrem com a página.
                    page.close(run_before_unload=False)
                    if papel == "anonimo":
                        ctx.close()
                if avisos:
                    com_aviso.append(cap["id"])
                print(f"  ok {cap['id']}" + (f"  [aviso: {'; '.join(avisos)}]" if avisos else ""))
            except Exception as e:  # noqa: BLE001
                falhas.append(cap["id"])
                print(f"  XX {cap['id']}: {str(e).splitlines()[0][:200]}")
        for ctx in contextos.values():
            ctx.close()
        navegador.close()

    manifesto = escrever_manifesto(args.saida)
    print(f"\n{len(fila) - len(falhas)}/{len(fila)} capturas; prints.json com {len(manifesto)} imagens.")
    if com_aviso:
        print("Com aviso (conferir a imagem):", ", ".join(com_aviso))
    if falhas:
        print("Falharam:", ", ".join(falhas))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
