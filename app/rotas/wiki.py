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

As páginas de cada módulo são `?modulo=<chave>`, como as abas das outras
telas, e não uma rota por módulo: assim a página continua sendo UMA rota de
página, e o teste do menu lateral (um item aceso por rota) segue valendo.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
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
    ModuloWiki("bandeja", "Bandeja CertGuard Análise",
               "O programa das estações que instala os certificados pedidos no portal.", None),
)

_POR_CHAVE = {m.chave: m for m in MODULOS}

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


def _visiveis(papel: str) -> list[ModuloWiki]:
    """Os módulos que o papel alcança. Sem a matriz, só os que valem para todos:
    melhor um índice curto do que ensinar o que a pessoa talvez não possa usar."""
    try:
        niveis = permissoes.matriz_para_papel(papel)
    except permissoes.PermissoesIndisponiveis as e:
        logger.error("Wiki sem a matriz de permissões: %s", e)
        niveis = {}
    return [
        m for m in MODULOS
        if m.permissao is None or niveis.get(m.permissao, permissoes.NIVEL_NENHUM) != permissoes.NIVEL_NENHUM
    ]


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

    visiveis = _visiveis(sessao.role or "")
    chave = (request.query_params.get("modulo") or "").strip()
    atual = _POR_CHAVE.get(chave)
    if chave and atual not in visiveis:
        # Módulo que não existe ou que a pessoa não alcança: o índice.
        return RedirectResponse("/wiki-certguard", status_code=303)

    from app.main import templates  # import tardio: main importa este router

    contexto = {"pagina_ativa": "wiki", "modulos": visiveis, "atual": atual, "prints": _prints() if atual else {}}
    if atual:
        i = visiveis.index(atual)
        contexto["anterior"] = visiveis[i - 1] if i > 0 else None
        contexto["proximo"] = visiveis[i + 1] if i + 1 < len(visiveis) else None
    return templates.TemplateResponse(request=request, name="wiki.html", context=contexto)
