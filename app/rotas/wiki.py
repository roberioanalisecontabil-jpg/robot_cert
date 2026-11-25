"""Wiki do CertGuard: tutoriais de uso, módulo por módulo (14/10/2026).

Diferente das outras páginas, esta confere a sessão NO SERVIDOR antes de
renderizar. As telas de dados podem servir o HTML a qualquer um porque o HTML
delas é uma casca: os dados vêm das APIs, que exigem sessão. Aqui o conteúdo
é o próprio HTML -- prints e passo a passo de telas internas --, e o portal
está na internet. Sem sessão, vai para o login e volta depois.

Cada pessoa vê os tutoriais dos módulos que alcança, pela mesma matriz de
permissões que monta o menu lateral (`permissoes.matriz_para_papel`). Um
módulo com nível "nenhum" some do índice e a URL dele cai no índice: o
tutorial de Usuários não ensina nada a quem não pode abrir Usuários.

25/11/2026: cada módulo virou um TEMA com várias páginas, uma por tarefa
(`?pagina=<chave>`). A página herda a permissão do tema. O link antigo
`?modulo=<chave>` vai para a primeira página do tema; a âncora (`#instalar`)
não chega ao servidor, então o wiki.js leva até a página que tem a âncora.
A busca (`?q=`) roda aqui, sem serviço externo: um índice das seções (título
h2/h3 + texto) montado dos próprios tutoriais na importação.

As páginas são parâmetros de UMA rota, como as abas das outras telas: assim
o teste do menu lateral (um item aceso por rota) segue valendo.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app import permissoes
from app.sessao import require_auth, security

logger = logging.getLogger(__name__)

router = APIRouter()


@dataclass(frozen=True)
class ModuloWiki:
    chave: str
    titulo: str
    resumo: str
    # Chave na matriz de permissões; None = todo mundo que entra no portal.
    permissao: Optional[str]


@dataclass(frozen=True)
class PaginaWiki:
    chave: str      # templates/wiki/<chave>.html e ?pagina=<chave>
    tema: str       # chave do ModuloWiki: dá a permissão e o grupo no índice
    titulo: str
    resumo: str


# A ordem é a do menu lateral, com o que vale para todos nas pontas: primeiro
# entrar no portal, por último a bandeja das estações.
MODULOS: tuple[ModuloWiki, ...] = (
    ModuloWiki("primeiros-passos", "Primeiros passos",
               "Entrar no portal, o código por e-mail e o app autenticador.", None),
    ModuloWiki("inicio", "Início",
               "A lista de certificados, os detalhes de cada um e o pedido de instalação.", "inicio"),
    ModuloWiki("dashboard", "Dashboard",
               "Os números do parque de certificados e as renovações.", "dashboard"),
    ModuloWiki("historico", "Histórico",
               "Todos os certificados que já passaram pelo portal, com filtros e exportação.", "historico"),
    ModuloWiki("vencidos", "Vencidos",
               "Os clientes com o certificado já vencido.", "vencidos"),
    ModuloWiki("duplicidades", "Duplicidades",
               "Clientes com mais de um certificado guardado, e qual vale.", "duplicidades"),
    ModuloWiki("acompanhamento", "Acompanhamento",
               "Escolher os certificados que você acompanha e receber os avisos.", "acompanhamento"),
    ModuloWiki("carteiras", "Carteiras",
               "Montar a carteira de clientes de cada pessoa da equipe.", "carteiras"),
    ModuloWiki("instalador", "Instalador",
               "Custódia, movimentos, trilha e SIEG.", "instalador"),
    ModuloWiki("usuarios", "Usuários",
               "Contas, departamentos, níveis de acesso e computadores.", "usuarios"),
    ModuloWiki("configuracao", "Configuração",
               "Pastas, alertas, comandos e integrações do portal.", "configuracao"),
    ModuloWiki("api", "API de leitura",
               "Chave de API, como consultar e todas as consultas permitidas.", "configuracao"),
    ModuloWiki("bandeja", "Bandeja CertGuard Análise",
               "O programa das estações que instala os certificados pedidos no portal.", None),
)

_P = PaginaWiki
# Na ordem de leitura: tema a tema, e dentro do tema na ordem do tutorial antigo.
PAGINAS: tuple[PaginaWiki, ...] = (
    _P("entrar-no-portal", "primeiros-passos", "Como entrar e sair do portal",
       "E-mail e senha, o código enviado por e-mail e como sair."),
    _P("app-autenticador", "primeiros-passos", "Como usar o app autenticador",
       "Cadastrar o app do celular, entrar com o código dele e trocar de celular."),
    _P("recuperar-senha", "primeiros-passos", "Como recuperar a senha e trocar a senha provisória",
       "Recuperar a senha pelo e-mail e trocar a senha provisória no primeiro acesso."),
    _P("achar-certificado", "inicio", "Como encontrar um certificado",
       "Buscar, filtrar e abrir os detalhes de um certificado no Início."),
    _P("instalar-certificado", "inicio", "Como instalar um certificado no seu computador",
       "Pedir a instalação pela bandeja e o que fazer quando o botão não aparece."),
    _P("incluir-no-sieg", "inicio", "Como incluir um certificado no SIEG",
       "Incluir no SIEG, pelos detalhes, um certificado da sua carteira."),
    _P("exportar-e-avisos", "inicio", "Como exportar a lista e consultar os avisos",
       "Baixar a lista em planilha ou PDF e usar o sino de avisos."),
    _P("ler-dashboard", "dashboard", "Como ler o Dashboard",
       "Escolher o período e entender cada cartão."),
    _P("agir-dashboard", "dashboard", "Como agir a partir do Dashboard",
       "O que fazer quando um cartão indica um problema."),
    _P("historico", "historico", "Como consultar o histórico de certificados",
       "Todos os certificados que já passaram pelo portal, com filtros e exportação."),
    _P("vencidos", "vencidos", "Como consultar os certificados vencidos",
       "Os clientes com o certificado já vencido: filtrar, buscar e exportar."),
    _P("duplicidades", "duplicidades", "Como analisar certificados duplicados",
       "Clientes com mais de um certificado guardado, e qual vale."),
    _P("escolher-acompanhados", "acompanhamento", "Como escolher os certificados que você acompanha",
       "Marcar os clientes que você acompanha e ver a lista deles."),
    _P("avisos-por-email", "acompanhamento", "Como receber avisos de vencimento por e-mail",
       "Ligar e ajustar o aviso por e-mail e conferir os avisos já enviados."),
    _P("montar-carteira", "carteiras", "Como montar a carteira de um operador",
       "Os termos da tela e como atribuir clientes a uma pessoa."),
    _P("retirar-e-excecoes", "carteiras", "Como retirar clientes e registrar exceções do gestor",
       "Retirar clientes de uma carteira e registrar as exceções de um gestor."),
    _P("importar-carteiras", "carteiras", "Como importar carteiras por planilha",
       "Montar várias carteiras de uma vez com uma planilha."),
    _P("instalacoes-do-operador", "carteiras", "Como conferir as instalações de um operador",
       "As instalações de cada pessoa e os cuidados com as carteiras."),
    _P("cofre", "instalador", "Como conferir o diagnóstico do cofre",
       "Conferir se o cofre está saudável e recifrar."),
    _P("custodia", "instalador", "Como gerenciar a custódia dos certificados",
       "Procurar, desativar e reativar a custódia de um certificado."),
    _P("movimentos", "instalador", "Como acompanhar os movimentos dos arquivos",
       "O que o agente fez com os arquivos que chegaram e como resolver pendências."),
    _P("trilha", "instalador", "Como consultar a trilha das instalações",
       "Consultar cada tentativa de instalação."),
    _P("sieg-no-instalador", "instalador", "Como acompanhar as inclusões no SIEG",
       "Acompanhar, incluir e conferir certificados no SIEG."),
    _P("validade-e-retencao", "instalador", "Como ajustar a validade do pedido e a retenção da trilha",
       "A aba Configuração do Instalador: validade do pedido, retenção e expurgo."),
    _P("cadastrar-pessoas", "usuarios", "Como cadastrar pessoas",
       "Encontrar alguém e cadastrar uma pessoa ou várias de uma vez."),
    _P("editar-conta", "usuarios", "Como editar uma conta, a senha e o app autenticador",
       "Editar uma conta e ajudar quem esqueceu a senha ou perdeu o celular do app."),
    _P("desativar-reativar", "usuarios", "Como desativar e reativar uma conta",
       "Desativar a conta de quem saiu e reativar quem voltou."),
    _P("departamentos", "usuarios", "Como gerenciar departamentos",
       "Criar, renomear, trocar o gestor e apagar departamentos."),
    _P("niveis-de-acesso", "usuarios", "Como configurar os níveis de acesso",
       "Mudar o que cada papel pode ver e ver quem mudou o quê."),
    _P("computadores", "usuarios", "Como autorizar computadores",
       "Autorizar, negar e retirar o acesso dos computadores das pessoas."),
    _P("chave-das-estacoes", "configuracao", "Como trocar a chave das estações",
       "A chave que as estações usam e como trocá-la."),
    _P("pastas-e-agente", "configuracao", "Como configurar as pastas e o agente",
       "Mudar as pastas, forçar leitura e o agente no Windows."),
    _P("alertas-por-email", "configuracao", "Como configurar os alertas por e-mail",
       "Ligar os alertas, a forma de envio, o teste e o resumo."),
    _P("sieg-configuracao", "configuracao", "Como configurar as credenciais do SIEG",
       "Conectar o portal à conta do SIEG e sincronizar o que já está lá."),
    # API de leitura (revisão editorial de 25/11/2026): tutoriais primeiro,
    # depois a referência; as chaves api-consultar/api-consultas ficaram.
    _P("api-visao-geral", "api", "Visão geral da API de leitura",
       "Finalidade, requisitos, segurança e o que cada consulta resolve."),
    _P("api-chaves", "api", "Como criar e gerenciar chaves de API",
       "Criar, guardar, substituir e revogar uma chave de API."),
    _P("api-consultar", "api", "Como realizar a primeira consulta",
       "O endereço, o cabeçalho, a resposta e como percorrer as páginas."),
    _P("api-integracoes", "api", "Guias de integração",
       "Postman, Power BI, Excel, PowerShell, Python e cURL, com a chave guardada com segurança."),
    _P("api-certificados", "api", "Consultar certificados digitais",
       "As consultas de certificados, seus filtros e os campos da resposta."),
    _P("api-consultas", "api", "Referência das demais consultas",
       "Dashboard, carteiras, instalador, SIEG, usuários, configuração e conta vinculada."),
    _P("api-erros", "api", "Erros, soluções e perguntas frequentes",
       "O que cada código de erro significa e como resolver."),
    _P("bandeja-entrar", "bandeja", "Como entrar na bandeja",
       "Entrar pela primeira vez e esperar a autorização do computador."),
    _P("bandeja-instalar", "bandeja", "Como receber certificados na bandeja",
       "Receber a instalação pedida no portal, ver o que a bandeja fez e sair."),
)

_POR_CHAVE = {m.chave: m for m in MODULOS}
_PAGINA = {p.chave: p for p in PAGINAS}
assert len(_PAGINA) == len(PAGINAS) and all(p.tema in _POR_CHAVE for p in PAGINAS)
_PRIMEIRA = {}
for _p in PAGINAS:
    _PRIMEIRA.setdefault(_p.tema, _p)

# Escrito pelo script de captura (scripts/wiki_capturas.py) junto com as
# imagens: {id: {"w": largura, "h": altura, "v": versão}}.
MANIFESTO_PRINTS = Path(__file__).resolve().parent.parent.parent / "static" / "wiki" / "prints.json"


def _prints() -> dict:
    """Lido a cada página: o arquivo é pequeno, e recapturar os prints não
    deve exigir reiniciar o portal. Sem o arquivo, todo print vira aviso."""
    try:
        return json.loads(MANIFESTO_PRINTS.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        logger.error("Manifesto dos prints da wiki ilegível: %s", e)
        return {}


# ── Parâmetros da API de leitura ──────────────────────────────────────────
# As tabelas de parâmetros da wiki saem do OpenAPI do próprio portal: tipo,
# obrigatoriedade, padrão e limites não ficam desatualizados quando a rota
# muda. A descrição de cada parâmetro vem do tutorial (macro `parametros`).
_TIPOS = {"string": "Texto", "integer": "Inteiro", "number": "Número", "boolean": "true ou false"}
_LISTA = re.compile(r"^\^\(([\w|]+)\)\$$")


def _faixa(v: dict) -> str:
    lo, hi = v.get("minimum"), v.get("maximum")
    if lo is not None and hi is not None:
        return f"De {lo} a {hi}"
    if hi is not None:
        return f"Até {hi}"
    return f"A partir de {lo}" if lo is not None else ""


def parametros_api(caminho: str, ordem=()) -> list[dict]:
    """Os parâmetros do GET `caminho`, como a wiki os mostra. Rota que não
    existe devolve lista vazia (o teste da wiki é quem barra)."""
    from app.main import app  # import tardio: main importa este router

    op = app.openapi().get("paths", {}).get(caminho, {}).get("get")
    if op is None:
        logger.error("Wiki cita uma consulta que não existe: %s", caminho)
        return []
    saida = []
    for p in op.get("parameters", []):
        if p.get("in") not in ("path", "query"):
            continue
        s = p.get("schema", {})
        v = next((x for x in s.get("anyOf", [s]) if x.get("type") != "null"), s)
        tipo = "Data (AAAA-MM-DD)" if v.get("format") == "date" else _TIPOS.get(v.get("type"), "Texto")
        padrao = s.get("default")
        if isinstance(padrao, bool):
            padrao = "true" if padrao else "false"
        valores = []
        lista = _LISTA.match(v.get("pattern") or "")
        if lista:
            valores.append(", ".join(lista.group(1).split("|")))
        elif v.get("pattern") == "^[0-9a-fA-F]{64}$":
            valores.append("64 caracteres hexadecimais")
        if _faixa(v):
            valores.append(_faixa(v))
        if v.get("maxLength") and not v.get("pattern"):
            valores.append(f"Até {v['maxLength']} caracteres")
        saida.append({
            "nome": p["name"], "na_rota": p["in"] == "path", "tipo": tipo,
            "obrigatorio": bool(p.get("required")),
            "padrao": "" if padrao in (None, "") else str(padrao),
            "valores": "; ".join(valores),
        })
    # Na ordem do tutorial (os filtros mais usados primeiro); o resto depois.
    pos = {n: i for i, n in enumerate(ordem)}
    return sorted(saida, key=lambda x: pos.get(x["nome"], len(pos)))


def _visiveis(papel: str) -> tuple[list[ModuloWiki], bool]:
    """Os módulos que o papel alcança. Sem a matriz, só os que valem para todos:
    melhor um índice curto do que ensinar o que a pessoa talvez não possa usar.
    O segundo valor diz que a matriz falhou, para a tela avisar (P9-2)."""
    falhou = False
    try:
        niveis = permissoes.matriz_para_papel(papel)
    except permissoes.PermissoesIndisponiveis as e:
        logger.error("Wiki sem a matriz de permissões: %s", e)
        niveis, falhou = {}, True
    return [
        m for m in MODULOS
        if m.permissao is None or niveis.get(m.permissao, permissoes.NIVEL_NENHUM) != permissoes.NIVEL_NENHUM
    ], falhou


def _paginas_de(temas: list[ModuloWiki]) -> list[PaginaWiki]:
    chaves = {m.chave for m in temas}
    return [p for p in PAGINAS if p.tema in chaves]


_TUTORIAIS = Path(__file__).resolve().parent.parent.parent / "templates" / "wiki"
_FONTE = {p.chave: (_TUTORIAIS / f"{p.chave}.html").read_text(encoding="utf-8")
          for p in PAGINAS if (_TUTORIAIS / f"{p.chave}.html").is_file()}

# De que tutoriais é cada arquivo de static/wiki/ (`<id>.png`, `<id>.mp4`,
# `<id>.jpg`), lido dos próprios tutoriais: um print citado em dois módulos
# abre para quem alcança qualquer um deles. Arquivo que nenhum tutorial cita
# (o manifesto, por exemplo) fica com a regra geral: basta a sessão.
_CITACAO = re.compile(r'(?:print|video)\("([\w-]+)"')
_MODULOS_DO_ARQUIVO: dict[str, set[str]] = {}
for _chave, _texto in _FONTE.items():
    for _id in _CITACAO.findall(_texto):
        _MODULOS_DO_ARQUIVO.setdefault(_id.lower(), set()).add(_PAGINA[_chave].tema)


def arquivo_visivel(nome: str, papel: str) -> bool:
    """O papel alcança algum tutorial que usa este arquivo de static/wiki/?
    `nome` já vem normalizado e em minúsculas pela cerca do main."""
    modulos = _MODULOS_DO_ARQUIVO.get(nome.rsplit(".", 1)[0])
    if not modulos:
        return True
    return any(m.chave in modulos for m in _visiveis(papel)[0])


# ── Busca ─────────────────────────────────────────────────────────────────
# Sem LLM e sem serviço externo (os tutoriais citam dados de clientes e o
# portal guarda dados sob LGPD): palavras sem acento e em minúsculas, as
# palavras vazias fora, comparação pelo começo da palavra (instalo ~ instalar)
# e uma lista curta de sinônimos do domínio.

VAZIAS = frozenset("""
a o os as um uma uns umas de do da dos das d em no na nos nas num numa por pelo pela pelos pelas
para pra pro ao aos com sem e ou mas que como quando onde qual quais quem porque pq se nao sim
eu me mim meu minha meus minhas voce voces seu sua seus suas ele ela eles elas lhe isso isto esse
essa este esta aquele aquela ja ainda mais menos muito tem ter ha foi ser sao estou esta estao
posso pode podem consigo consegue preciso precisa quero queria devo deve faco fazer fica ficou
tudo todo toda todos todas algum alguma aqui ali la so tambem entao ate sobre
""".split())

_SINONIMOS = (
    ("certificado", "pfx", "a1", "cert"),
    ("senha", "codigo"),
    ("instalar", "instalacao", "baixar", "download"),
    ("email", "correio"),
    ("entrar", "login", "logar", "acessar", "acesso"),
    ("computador", "maquina", "estacao", "pc", "notebook"),
    ("cliente", "empresa"),
    ("vencido", "vencimento", "expirado", "expira", "vence"),
    ("apagar", "excluir", "remover", "desativar", "tirar", "retirar"),
    ("planilha", "excel", "csv"),
    ("usuario", "pessoa", "conta", "colaborador", "operador"),
    ("aviso", "alerta", "notificacao", "sino"),
    ("app", "autenticador", "celular"),
    ("esqueci", "recuperar", "redefinir"),
    ("chegou", "receber", "recebi"),
)


def _sem_acento(texto: str) -> str:
    """Minúsculas sem acento, com o mesmo comprimento do texto (o trecho do
    resultado é recortado do original pelas posições deste)."""
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if not unicodedata.combining(c))


def _palavras(texto: str) -> list[str]:
    # "e-mail" e "E-mail" viram "email"; "CNPJ/CPF" vira duas palavras.
    texto = re.sub(r"(?<=[a-z0-9])-(?=[a-z0-9])", "", _sem_acento(texto))
    return [w for w in re.findall(r"[a-z0-9]+", texto) if len(w) >= 2 and w not in VAZIAS]


def _raiz(palavra: str) -> str:
    """O começo da palavra que conta: instalo, instalar e instalação casam
    por "insta"/"instal". shortcut: não é um radicalizador de verdade; se a
    busca errar muito, trocar por um stemmer RSLP."""
    return palavra if len(palavra) <= 4 else palavra[:max(4, min(len(palavra) - 2, 6))]


_SINONIMOS_DA_RAIZ: dict[str, set[str]] = {}
for _grupo in _SINONIMOS:
    _raizes = {_raiz(w) for w in _grupo}
    for _r in _raizes:
        _SINONIMOS_DA_RAIZ.setdefault(_r, set()).update(_raizes - {_r})


def _texto_puro(fonte: str) -> str:
    """O texto que a pessoa lê, sem Jinja e sem HTML. O título de um aviso
    (`{% call dica("...") %}`) fica; prints e vídeos saem."""
    fonte = re.sub(r'\{%\s*call\s+\w+\("([^"]*)"\)\s*%\}', r" \1. ", fonte)
    fonte = re.sub(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", " ", fonte, flags=re.S)
    fonte = re.sub(r"<[^>]+>", " ", fonte)
    texto = " ".join(unescape(fonte).split())
    # O espaço que a tag deixou antes da pontuação: "<strong>X</strong>." -> "X."
    return re.sub(r"\(\s+", "(", re.sub(r"\s+([.,;:!?)])", r"\1", texto))


@dataclass(frozen=True)
class SecaoWiki:
    pagina: str
    ancora: str          # "" = a abertura da página, antes do primeiro título
    titulo: str          # o h2/h3; na abertura, o título da página
    texto: str
    pal_titulo: frozenset
    pal_pagina: frozenset
    pal_texto: tuple


_TITULO = re.compile(r'<h([23]) id="([^"]+)"[^>]*>(.*?)</h\1>', re.S)


def _secoes(pagina: PaginaWiki, fonte: str) -> list[SecaoWiki]:
    pal_pagina = frozenset(_palavras(pagina.titulo + " " + _POR_CHAVE[pagina.tema].titulo))
    pedacos, inicio, ancora, titulo = [], 0, "", pagina.titulo
    for m in _TITULO.finditer(fonte):
        pedacos.append((ancora, titulo, fonte[inicio:m.start()]))
        ancora, titulo, inicio = m.group(2), _texto_puro(m.group(3)), m.end()
    pedacos.append((ancora, titulo, fonte[inicio:]))
    secoes = []
    for ancora, titulo, trecho in pedacos:
        texto = _texto_puro(trecho)
        if not texto and not ancora:
            continue
        secoes.append(SecaoWiki(pagina.chave, ancora, titulo, texto,
                                frozenset(_palavras(titulo)), pal_pagina, tuple(_palavras(texto))))
    return secoes


SECOES: tuple[SecaoWiki, ...] = tuple(s for p in PAGINAS for s in _secoes(p, _FONTE.get(p.chave, "")))
# As raízes de cada página, para o "Veja também".
_RAIZES_DA_PAGINA = {
    p.chave: frozenset(_raiz(w) for s in SECOES if s.pagina == p.chave for w in (*s.pal_titulo, *s.pal_texto))
    for p in PAGINAS
}
# Âncora -> página, por tema: leva o link antigo `?modulo=X#ancora` à página certa.
_ANCORAS_DO_TEMA: dict[str, dict[str, str]] = {}
for _s in SECOES:
    if _s.ancora:
        _ANCORAS_DO_TEMA.setdefault(_PAGINA[_s.pagina].tema, {})[_s.ancora] = _s.pagina


def _casa(raiz: str, palavras) -> bool:
    return any(w.startswith(raiz) for w in palavras)


def _trecho(texto: str, raizes: list[str], tamanho: int = 200) -> str:
    base = _sem_acento(texto)
    posicoes = [m.start() for r in raizes for m in [re.search(r"\b" + re.escape(r), base)] if m]
    pos = min(posicoes) if posicoes else 0
    ini = max(0, pos - 60)
    if ini:
        ini = texto.find(" ", ini) + 1 or ini
    fim = min(len(texto), ini + tamanho)
    corte = texto.rfind(" ", ini, fim)
    if fim < len(texto) and corte > ini:
        fim = corte
    return ("…" if ini else "") + texto[ini:fim].strip() + ("…" if fim < len(texto) else "")


def buscar(pergunta: str, paginas: list[PaginaWiki], limite: int = 10) -> list[dict]:
    """As seções que respondem à pergunta, só das `paginas` dadas (as que a
    pessoa vê). Pontos por termo: 3 no título da seção, 2 no da página ou do
    tema, 1 no texto; sinônimo vale 0,6 disso. A soma é multiplicada pela
    fração dos termos achados (quem responde a pergunta toda vem antes), e a
    frequência no texto desempata."""
    termos = list(dict.fromkeys(_raiz(w) for w in _palavras(pergunta)))
    if not termos:
        return []
    permitidas = {p.chave for p in paginas}
    achados = []
    for s in SECOES:
        if s.pagina not in permitidas:
            continue
        total, cobertos, freq = 0.0, 0, 0
        for termo in termos:
            melhor = 0.0
            for raiz, peso in ((termo, 1.0), *((r, 0.6) for r in _SINONIMOS_DA_RAIZ.get(termo, ()))):
                if _casa(raiz, s.pal_titulo):
                    pontos = 3
                elif _casa(raiz, s.pal_pagina):
                    pontos = 2
                elif _casa(raiz, s.pal_texto):
                    pontos = 1
                else:
                    continue
                melhor = max(melhor, pontos * peso)
            if melhor:
                total += melhor
                cobertos += 1
                freq += sum(1 for w in s.pal_texto if w.startswith(termo))
        if cobertos:
            achados.append((total * cobertos / len(termos) + 0.05 * min(freq, 10), s))
    achados.sort(key=lambda par: -par[0])
    resultado = []
    for nota, s in achados[:limite]:
        p = _PAGINA[s.pagina]
        resultado.append({
            "pagina": p, "tema": _POR_CHAVE[p.tema], "secao": s.titulo if s.ancora else "",
            "url": f"/wiki-certguard?pagina={p.chave}" + (f"#{s.ancora}" if s.ancora else ""),
            "trecho": _trecho(s.texto, termos), "nota": round(nota, 2),
        })
    return resultado


def relacionadas(pagina: PaginaWiki, paginas: list[PaginaWiki], limite: int = 3) -> list[PaginaWiki]:
    """'Veja também': mesmo tema primeiro, depois as que têm mais palavras em
    comum (Jaccard das raízes). Só entre as `paginas` que a pessoa vê."""
    minhas = _RAIZES_DA_PAGINA[pagina.chave]

    def parecido(p: PaginaWiki) -> float:
        outras = _RAIZES_DA_PAGINA[p.chave]
        return len(minhas & outras) / (len(minhas | outras) or 1)

    candidatas = [p for p in paginas if p.chave != pagina.chave]
    candidatas.sort(key=lambda p: (p.tema != pagina.tema, -parecido(p)))
    return candidatas[:limite]


def _para_o_login(request: Request) -> RedirectResponse:
    destino = request.url.path + (("?" + request.url.query) if request.url.query else "")
    return RedirectResponse("/login?next=" + quote(destino, safe=""), status_code=303)


@router.get("/wiki-certguard", response_class=HTMLResponse)
async def pagina_wiki(request: Request) -> Response:
    try:
        # A mesma conferência das APIs, chamada à mão para poder virar
        # redirecionamento em vez de 401. O navegador manda o cookie; o
        # Bearer é lido como numa rota com `Depends(require_auth)`.
        sessao = await require_auth(request, await security(request), None)
    except HTTPException as e:
        if e.status_code == 403 and (e.headers or {}).get("X-Senha-Provisoria"):
            # Senha provisória: o Início abre o modal de troca.
            return RedirectResponse("/", status_code=303)
        return _para_o_login(request)
    # A identidade anônima (ambiente sem API_KEY) e o agente não são pessoas.
    if (sessao.role or "") == "agent":
        return _para_o_login(request)

    params = request.query_params
    chave = (params.get("pagina") or "").strip()
    modulo = (params.get("modulo") or "").strip()
    if modulo and not chave:
        # Link antigo (um tutorial por módulo): a primeira página do tema. A
        # página confere a permissão; a âncora segue no navegador.
        primeira = _PRIMEIRA.get(modulo)
        return RedirectResponse(f"/wiki-certguard?pagina={primeira.chave}" if primeira else "/wiki-certguard",
                                status_code=303)

    temas, sem_permissoes = _visiveis(sessao.role or "")
    paginas = _paginas_de(temas)
    atual = _PAGINA.get(chave)
    if sem_permissoes and atual is not None and atual not in paginas:
        # Sem a matriz não dá para saber se alcança: o índice com o aviso, e
        # não um 303 que parece perda de acesso ("503, nunca 403").
        atual = None
    elif chave and atual not in paginas:
        # Página que não existe ou que a pessoa não alcança: o índice.
        return RedirectResponse("/wiki-certguard", status_code=303)

    from app.main import templates  # import tardio: main importa este router

    pergunta = (params.get("q") or "").strip()[:200]
    contexto = {
        "pagina_ativa": "wiki", "modulos": temas, "atual": atual, "sem_permissoes": sem_permissoes,
        "temas": [(m, [p for p in paginas if p.tema == m.chave]) for m in temas],
        "q": pergunta, "resultados": buscar(pergunta, paginas) if pergunta and not atual else [],
        "prints": _prints() if atual else {},
        "parametros_api": parametros_api,
    }
    if atual:
        i = paginas.index(atual)
        contexto.update(
            tema=_POR_CHAVE[atual.tema],
            temas_por_chave=_POR_CHAVE,
            anterior=paginas[i - 1] if i > 0 else None,
            proximo=paginas[i + 1] if i + 1 < len(paginas) else None,
            relacionadas=relacionadas(atual, paginas),
            ancoras=_ANCORAS_DO_TEMA.get(atual.tema, {}),
        )
    return templates.TemplateResponse(request=request, name="wiki.html", context=contexto)
