"""
Matriz de permissões por papel: qual módulo cada papel alcança, e até onde.

Etapa 3 de `docs/PLANO_niveis_de_acesso.md`. Três decisões moldam este arquivo,
e vale registrá-las porque cada uma poda uma classe inteira de engano:

1. **Por papel, não por usuário.** Permissão individual exigiria uma linha por
   pessoa e transformaria "por que fulano não vê isto?" numa investigação. Se
   um dia for preciso, a tabela ganha `user_id` e esta camada muda de chave —
   mas o modelo não nasce carregando um eixo que ninguém pediu.

2. **`admin` é sempre total, e não tem linha na tabela.** Isso elimina de uma
   vez o engano mais caro possível numa tela de permissões: o administrador
   tirando o próprio acesso a Usuários e ficando sem como voltar. Não é uma
   validação que pode falhar — é uma linha que não existe.

3. **Alcance NÃO mora aqui.** `require_admin_ou_lider` e `_exigir_alcance` já
   resolvem *de quem* um gestor pode tratar, derivado da liderança de
   departamento. Esta matriz responde outra pergunta — *qual módulo, e em que
   profundidade* — e achatar as duas perderia a barreira que impede um líder do
   Fiscal de mexer na carteira do Contábil.
"""
from __future__ import annotations

import threading
import time
from typing import Dict, Optional, Tuple

# ── Vocabulário ────────────────────────────────────────────────────────────

NIVEL_NENHUM = "nenhum"
NIVEL_LER = "ler"
NIVEL_EDITAR = "editar"
NIVEIS = (NIVEL_NENHUM, NIVEL_LER, NIVEL_EDITAR)

# Ordem de profundidade: `editar` satisfaz quem pede `ler`, o contrário não.
_PESO = {NIVEL_NENHUM: 0, NIVEL_LER: 1, NIVEL_EDITAR: 2}

# Os módulos são as PÁGINAS do portal, não os prefixos de rota. É o vocabulário
# do pedido ("quais páginas vão aparecer") e o mesmo da sidebar, então a tela de
# permissões e o menu falam a mesma língua sem tradução no meio.
MODULOS = (
    "inicio",
    "dashboard",
    "historico",
    "vencidos",
    "duplicidades",
    "acompanhamento",
    "carteiras",
    "instalador",
    "usuarios",
    "configuracao",
)

# Rotas de máquina (`ingest`, `agent/*`) e de conta (`login`, `senha`) ficam de
# fora de propósito: quem as guarda é `require_agent_or_admin` e a ausência de
# sessão, não o papel de um humano. Colocá-las na matriz criaria a ilusão de que
# desmarcar uma célula desliga o agente.

PAPEIS_TOTAIS = ("admin",)


# ── O padrão: exatamente o comportamento de hoje ───────────────────────────
#
# Semente da migration e queda quando não há banco. Reproduz o que o portal já
# faz em 20/08/2026 — assim ligar esta camada não muda nada no dia do deploy, e
# qualquer diferença observada depois é mudança que alguém fez de propósito.
PADRAO: Dict[str, Dict[str, str]] = {
    "gestor": {
        "inicio": NIVEL_LER,
        "dashboard": NIVEL_NENHUM,
        "historico": NIVEL_LER,
        "vencidos": NIVEL_LER,
        "duplicidades": NIVEL_LER,
        "acompanhamento": NIVEL_LER,
        # Editar porque montar carteira é a função do papel. O alcance — de quem
        # ele monta — continua sendo decidido pela liderança de departamento.
        "carteiras": NIVEL_EDITAR,
        "instalador": NIVEL_NENHUM,
        "usuarios": NIVEL_NENHUM,
        "configuracao": NIVEL_NENHUM,
    },
    "user": {
        "inicio": NIVEL_LER,
        "dashboard": NIVEL_NENHUM,
        "historico": NIVEL_LER,
        "vencidos": NIVEL_LER,
        "duplicidades": NIVEL_LER,
        "acompanhamento": NIVEL_LER,
        "carteiras": NIVEL_NENHUM,
        "instalador": NIVEL_NENHUM,
        "usuarios": NIVEL_NENHUM,
        "configuracao": NIVEL_NENHUM,
    },
}


class PermissoesIndisponiveis(RuntimeError):
    """
    Não deu para saber a permissão — o que é diferente de não ter permissão.

    Existe pelo mesmo motivo que `cert_installer.AlcanceIndisponivel`: quem
    chama traduz isto em **503**, nunca em 403. Um 403 aqui faria a pessoa
    acreditar que perdeu um acesso que continua sendo dela, e o suporte
    procuraria a permissão errada.
    """


# ── Cache ──────────────────────────────────────────────────────────────────
#
# A matriz muda em cliques de admin e é lida em toda requisição. Sem cache,
# cada chamada de API viraria uma consulta a mais no Supabase.
_TTL_SEGUNDOS = 30.0
_cache: Optional[Tuple[float, Dict[str, Dict[str, str]]]] = None
_trava = threading.Lock()


def invalidar_cache() -> None:
    """Chamado por quem grava a matriz, para a mudança valer na hora."""
    global _cache
    with _trava:
        _cache = None


def _tabela_ausente(erro: Exception) -> bool:
    """
    O erro diz "essa tabela nao existe", e nao "nao consegui ler"?

    PostgREST devolve `PGRST205` com a mensagem "Could not find the table". Olho
    os dois: o codigo e o contrato estavel, o texto e a queda para quando o
    cliente embrulhar o erro e o codigo se perder no caminho.
    """
    texto = str(erro)
    return "PGRST205" in texto or "Could not find the table" in texto


def _buscar_no_banco() -> Optional[Dict[str, Dict[str, str]]]:
    """
    Lê a matriz do Supabase. `None` quando não há Supabase configurado.

    Levanta `PermissoesIndisponiveis` quando HÁ banco e a leitura falhou — os
    dois casos são diferentes e confundi-los seria abrir ou fechar demais.
    """
    # Os dois vivem em `settings_state`, que é quem já fala com o Supabase.
    from app.settings_state import _supabase, supabase_configured

    if not supabase_configured():
        return None

    sb = _supabase()
    if sb is None:
        return None

    try:
        resp = sb.table("permissoes").select("papel,modulo,nivel").execute()
    except Exception as e:
        # Tabela que AINDA NAO EXISTE nao e falha: e o codigo tendo chegado
        # antes da migration. Nesse caso vale o padrao, e o portal se comporta
        # exatamente como hoje.
        #
        # A distincao e a licao registrada na migration de 18/08: "codigo antes
        # da coluna faria toda requisicao autenticada virar 503 — o portal
        # inteiro parando". Tratar as duas situacoes como a mesma repetiria isso
        # no primeiro deploy desta camada.
        if _tabela_ausente(e):
            return None
        raise PermissoesIndisponiveis(str(e)) from e

    matriz: Dict[str, Dict[str, str]] = {}
    for linha in (getattr(resp, "data", None) or []):
        papel = str(linha.get("papel") or "").strip().lower()
        modulo = str(linha.get("modulo") or "").strip().lower()
        nivel = str(linha.get("nivel") or "").strip().lower()
        if papel and modulo in MODULOS and nivel in NIVEIS:
            matriz.setdefault(papel, {})[modulo] = nivel

    # Tabela vazia é tratada como "ainda não semeada", e não como "ninguém pode
    # nada": o padrão entra e o portal continua funcionando. Fechar tudo aqui
    # derrubaria o acesso de todo mundo no primeiro deploy antes da migration.
    return matriz or None


def _matriz() -> Dict[str, Dict[str, str]]:
    global _cache
    agora = time.monotonic()
    with _trava:
        if _cache and agora - _cache[0] < _TTL_SEGUNDOS:
            return _cache[1]
    banco = _buscar_no_banco()
    resultado = banco if banco is not None else PADRAO
    with _trava:
        _cache = (agora, resultado)
    return resultado


# ── Consulta ───────────────────────────────────────────────────────────────

def nivel_de(papel: str, modulo: str) -> str:
    """
    Nível de um papel num módulo. `admin` é sempre `editar`, sem consultar nada.

    Papel desconhecido devolve `nenhum` — falha fechada: um papel novo criado no
    banco sem linha na matriz não herda acesso por omissão.
    """
    p = (papel or "").strip().lower()
    if p in PAPEIS_TOTAIS:
        return NIVEL_EDITAR
    if modulo not in MODULOS:
        raise ValueError(f"módulo desconhecido: {modulo!r}")
    return _matriz().get(p, {}).get(modulo, NIVEL_NENHUM)


def pode(papel: str, modulo: str, minimo: str) -> bool:
    """`editar` satisfaz quem pede `ler`; o contrário não."""
    if minimo not in NIVEIS:
        raise ValueError(f"nível desconhecido: {minimo!r}")
    return _PESO[nivel_de(papel, modulo)] >= _PESO[minimo]


def matriz_para_papel(papel: str) -> Dict[str, str]:
    """A linha inteira de um papel — o que o menu precisa para se montar."""
    p = (papel or "").strip().lower()
    if p in PAPEIS_TOTAIS:
        return {m: NIVEL_EDITAR for m in MODULOS}
    linha = _matriz().get(p, {})
    return {m: linha.get(m, NIVEL_NENHUM) for m in MODULOS}
