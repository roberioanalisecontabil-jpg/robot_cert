"""Certificados — Frente 3, leva 10 (12/10/2026).

Saiu de `app/main.py` sem mudar comportamento: a lista do Início
(`/api/certificados`) e os detalhes, duplicidades, histórico, vencidos, o
inventário que o agente manda (`/api/ingest`) e mover vencidos, com os
helpers e tetos de recurso deles.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path as PathParam, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import auth, db_pg, nome_publico, nomes, permissoes, sieg, taxa
from app.alcance import (
    _documentos_ao_alcance,
    _marcar_instalaveis,
    _no_alcance,
    _no_cofre,
    _recortar_pela_carteira,
)
from app.alert_state import trigger_all_alerts
from app.cert_scanner import cert_to_public_dict, CertInfo, CertStatus, move_to_expired, scan_folder
from app.comum import LISTAGEM_EXPORT_MAX
from app.historico_agg_cache import get_or_build as _historico_cache_get_or_build
from app.novos_certificados import agendar_ou_notificar, filtrar_ineditos, fingerprints_do_snapshot
from app.sessao import (
    _ip_do_cliente,
    _machine_da_credencial,
    _parse_iso_utc,
    require_admin,
    require_agent_or_admin,
    require_auth,
    require_modulo,
)
from app.settings_state import (
    banco_configurado,
    get_latest_snapshot,
    load_settings,
    PortalSettings,
    save_snapshot,
    upsert_cert_history,
)

logger = logging.getLogger("app.main")
router = APIRouter()


# ── Tetos de recurso (lote 5 da auditoria) ────────────────────────────────
#
# Um worker só (`Procfile`): o que não tem teto derruba o portal inteiro, e
# quem derruba é qualquer sessão comum. Cada limite abaixo tem o teste que o
# derrubaria em `tests/test_seguranca_lote5.py`.

# Um CSV de 5 MB cabe ~100.000 linhas; cada linha de usuário custa um bcrypt
# (~0,25 s) — horas de CPU num worker só, com o gunicorn matando no meio.
# Inventário real de uma estação não passa de alguns milhares; sem teto um
# snapshot vira carga permanente em /duplicidades e em todo alerta seguinte.
MAX_ITENS_INGEST = 20000
MAX_ITENS_DUPLICIDADE = 1500
_JANELA_NOMES = 15
_DUP_CACHE_TTL_SEG = 300.0
_INGEST_ALERTA_DEBOUNCE_SEG = 600.0


def _painel_busca_normalizada(value: Any) -> str:
    """Mesma ideia que `normalizarTexto` no dashboard (minúsculas, sem acentos)."""
    t = str(value or "").lower()
    t = unicodedata.normalize("NFD", t)
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")


def _enrich_cert_item_dashboard_flags(it: dict, now: datetime, thirty_days: datetime) -> dict:
    """Alinha com o painel: vencido pela data `not_after` mesmo que `status` ainda seja ok."""
    row = dict(it)
    expired_by_date = False
    expiring_soon = False
    na = row.get("not_after")
    if na:
        exp = _parse_iso_utc(str(na))
        min_dt = datetime.min.replace(tzinfo=timezone.utc)
        if exp > min_dt:
            if exp < now:
                expired_by_date = True
            elif exp <= thirty_days and exp >= now:
                expiring_soon = True
    row["_isExpiredByDate"] = expired_by_date
    row["_isExpiringSoon"] = expiring_soon
    return row


def _sieg_filtro_match(row: dict, filtro: str) -> bool:
    """Filtro SIEG do Início: "No SIEG" inclui o erro? Não — cada um o seu."""
    f = (filtro or "todos").strip().lower()
    e = row.get("sieg_estado")
    if f == "todos":
        return True
    if f == "fora":
        return e in (None, "removido", "substituido")
    if f == "incluindo":
        return e in ("incluindo", "erro")
    return e == f


def _dashboard_filtro_status_match(row: dict, filtro: str) -> bool:
    s = str(row.get("status") or "").lower()
    ed = bool(row.get("_isExpiredByDate"))
    es = bool(row.get("_isExpiringSoon"))
    f = (filtro or "todos").strip().lower()
    if f in ("todos", ""):
        return True
    if f == "validos":
        return s == "ok" and not ed and not es
    if f in ("prestes_vencer", "prestes a vencer"):
        return s == "ok" and es and not ed
    if f == "vencidos":
        return s == "expirado" or ed
    if f in ("erros", "erro"):
        return s == "erro"
    if f in ("sem_padrao", "fora_do_padrao"):
        return s == "fora_do_padrao"
    return True


# Status que significam "o robo NAO conseguiu ler este arquivo": ou a leitura
# falhou (`erro`), ou o nome nao segue a convencao que carrega a senha do PFX
# (`fora_do_padrao`). Nos dois casos o certificado nunca vai ao cofre e nunca e
# instalavel pelo portal — e por isso nao ajuda quem veio buscar um certificado
# para usar.
STATUS_ILEGIVEIS = ("erro", "fora_do_padrao")


def _e_ilegivel(row: dict) -> bool:
    return str(row.get("status") or "").lower() in STATUS_ILEGIVEIS


def _e_vencido(row: dict) -> bool:
    """Mesmo critério do filtro `vencidos` e do resumo: status ou data."""
    return str(row.get("status") or "").lower() == "expirado" or bool(row.get("_isExpiredByDate"))


def _dashboard_busca_match(row: dict, q_raw: str) -> bool:
    if not str(q_raw or "").strip():
        return True
    raw = str(q_raw).strip()
    bt = _painel_busca_normalizada(raw)
    bd = re.sub(r"\D", "", raw)
    nome = _painel_busca_normalizada(row.get("nome") or row.get("display_name") or "")
    doc_f = _painel_busca_normalizada(row.get("documento_formatado") or "")
    doc_n = _painel_busca_normalizada(row.get("documento_numero") or "")
    fn = _painel_busca_normalizada(row.get("nome_publico") or "")
    na_txt = _painel_busca_normalizada(row.get("not_after") or "")
    dd = _digits_only_doc(row.get("documento_numero") or row.get("documento_formatado"))
    nd = _digits_only_doc(str(row.get("not_after") or ""))
    if bt and bt in nome:
        return True
    if bt and bt in doc_f:
        return True
    if bt and bt in doc_n:
        return True
    if bt and bt in fn:
        return True
    if bt and bt in na_txt:
        return True
    if bd and bd in dd:
        return True
    if bd and bd in nd:
        return True
    return False


def _dashboard_resumo_counts(rows: List[dict]) -> dict[str, int]:
    total = len(rows)
    validos = expirando = erros = vencidos = sem_padrao = 0
    for it in rows:
        s = str(it.get("status") or "").lower()
        ed = bool(it.get("_isExpiredByDate"))
        es = bool(it.get("_isExpiringSoon"))
        if s == "erro":
            erros += 1
        elif s == "fora_do_padrao":
            sem_padrao += 1
        elif s == "expirado" or ed:
            vencidos += 1
        elif s == "ok":
            if es:
                expirando += 1
            else:
                validos += 1
    return {
        "total": total,
        "validos": validos,
        "expirando": expirando,
        "erros": erros,
        "vencidos": vencidos,
        "sem_padrao": sem_padrao,
    }


def chave_alfabetica(item: dict) -> tuple:
    """
    Chave de ordenação por titular, insensível a caixa e acento.

    `(1, "")` para quem não tem nome legível: vai para o fim. Ordenar por
    string vazia os jogaria para o topo, e a primeira página da lista seria
    justamente o que o robô não conseguiu ler — o oposto do útil.
    """
    bruto = str(item.get("nome") or item.get("display_name") or item.get("nome_publico") or "").strip()
    if not bruto:
        return (1, "")
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", bruto) if unicodedata.category(c) != "Mn"
    )
    return (0, sem_acento.casefold())


# Colunas que a tabela do Inicio deixa ordenar. O valor e a funcao que extrai a
# chave; `None` como primeiro elemento da tupla mantem a regra que ja valia para
# o nome: **o que falta vai para o FIM**, nas duas direcoes.
#
# Isso nao e detalhe. Ordenar por vencimento com os sem-data no topo daria uma
# primeira pagina inteira de arquivos que o robo nao conseguiu ler — o oposto do
# util, que e exatamente o que `chave_alfabetica` ja evitava para o nome.
def _chave_texto(campo: str):
    def chave(it: dict):
        v = str(it.get(campo) or "").strip()
        if not v:
            return (1, "")
        sem_acento = "".join(
            c for c in unicodedata.normalize("NFD", v) if unicodedata.category(c) != "Mn"
        )
        return (0, sem_acento.casefold())
    return chave


def _chave_data(campo: str):
    def chave(it: dict):
        v = str(it.get(campo) or "").strip()
        return (1, "") if not v else (0, v)   # ISO 8601 ordena como texto
    return chave


ORDENACOES = {
    "nome": chave_alfabetica,
    "status": _chave_texto("status"),
    "emissao": _chave_data("not_before"),
    "vencimento": _chave_data("not_after"),
    "documento": _chave_texto("documento_numero"),
}


def _ordenar_listagem(itens: List[dict], coluna: str, direcao: str) -> List[dict]:
    """Ordena por coluna. Coluna desconhecida mantem a ordem que veio.

    Recusar seria pior: a tabela ganharia um estado em que ela simplesmente nao
    carrega, e o sintoma (uma tela vazia) nao diria que o problema e o parametro.
    """
    chave = ORDENACOES.get((coluna or "").strip().lower())
    if chave is None:
        return itens

    # Os SEM valor saem da ordenacao em vez de participar dela.
    #
    # A primeira versao devolvia `(1, "")` para eles e deixava o `reverse` fazer
    # o resto — e o `reverse` inverte tambem o marcador, entao em ordem
    # decrescente os sem-data iam para o TOPO. A primeira pagina virava uma
    # lista de arquivos que o robo nao conseguiu ler, que e o oposto do util e
    # justamente o que `chave_alfabetica` ja evitava para o nome.
    #
    # Descoberto pelo teste que afirmava a invariante nas DUAS direcoes; com uma
    # so teria passado.
    presentes = [it for it in itens if chave(it)[0] == 0]
    ausentes = [it for it in itens if chave(it)[0] != 0]
    ordenados = sorted(presentes, key=chave, reverse=(str(direcao).lower() == "desc"))
    return ordenados + ausentes


def ordenar_por_titular(itens: List[dict]) -> List[dict]:
    """
    Ordena a listagem de certificados pelo nome do titular.

    **Precisa acontecer aqui, no servidor, e antes da paginação.** A tabela
    pagina no servidor: ordenar no navegador ordenaria só os 10 ou 25 itens da
    página visível, e a lista *pareceria* certa enquanto continuasse errada
    entre páginas — que é pior que estar visivelmente errada.

    Não havia ordenação nenhuma antes. A lista saía na ordem em que o agente
    varre o disco, e ele percorre pasta por pasta: o resultado eram vários
    blocos alfabéticos emendados (um por subpasta, mais os vencidos no fim),
    que de longe parece ordem alfabética e de perto não é.
    """
    return sorted(itens, key=chave_alfabetica)


def _list_certificados_payload(
    sets: PortalSettings,
    snap: Optional[dict],
    fonte: str,
) -> dict[str, Any]:
    """Monta o payload base (sem paginação) para GET /api/certificados."""
    if fonte == "local":
        src = sets.effective_source()
        exp = sets.effective_expired()
        itens: List[CertInfo] = scan_folder(src)
        return {
            "source_dir": str(src),
            "expired_dir": str(exp),
            "atualizado_em": datetime.now(timezone.utc).isoformat(),
            "itens": [cert_to_public_dict(c) for c in itens],
            "data_source": "local",
            "machine_id": sets.machine_id,
        }
    # Sanitizado também na SAÍDA, e não só no ingest: um snapshot gravado antes
    # da migração do lote 3 ainda tem o nome do arquivo (com a senha) em cada
    # item, e a resposta da API não pode depender de a migração já ter rodado.
    if fonte == "remoto":
        if not snap:
            raise HTTPException(
                status_code=404,
                detail="Nenhum dado remoto. Configure o agente no Windows para enviar leituras.",
            )
        return {
            "source_dir": str(snap.get("source_folder", "") or ""),
            "expired_dir": str(snap.get("expired_folder", "") or ""),
            "atualizado_em": snap.get("scanned_at", datetime.now(timezone.utc).isoformat()),
            "itens": [nome_publico.sanitizar_item(it) for it in (snap.get("items", []) or [])],
            "data_source": "remoto",
            "machine_id": snap.get("machine_id"),
        }
    # auto
    if snap:
        return {
            "source_dir": str(snap.get("source_folder", "") or ""),
            "expired_dir": str(snap.get("expired_folder", "") or ""),
            "atualizado_em": snap.get("scanned_at", datetime.now(timezone.utc).isoformat()),
            "itens": [nome_publico.sanitizar_item(it) for it in (snap.get("items", []) or [])],
            "data_source": "remoto",
            "machine_id": snap.get("machine_id"),
        }
    src = sets.effective_source()
    exp = sets.effective_expired()
    itens_scan: List[CertInfo] = scan_folder(src)
    return {
        "source_dir": str(src),
        "expired_dir": str(exp),
        "atualizado_em": datetime.now(timezone.utc).isoformat(),
        "itens": [cert_to_public_dict(c) for c in itens_scan],
        "data_source": "local",
        "machine_id": sets.machine_id,
    }


class IngestBody(BaseModel):
    # Limites (achado #29): `items` era ilimitado e alimenta /duplicidades
    # (n²) e todo alerta seguinte — um POST virava carga permanente.
    machine_id: str = Field(default="default", max_length=128)
    source_folder: str = Field(max_length=1024)
    expired_folder: str = Field(max_length=1024)
    items: List[dict] = Field(default_factory=list, max_length=20000)
    scanned_at: Optional[str] = Field(default=None, max_length=64)


# `/api/certificados` fica FORA da matriz, de proposito. Duas razoes:
#
# 1. `scripts/diagnostico.py` a consome com X-API-Key. Liga-la faria a
#    ferramenta de diagnostico reportar "-1 itens" em silencio — quebrar o
#    termometro e pior do que a febre.
# 2. `inicio` e onde todo mundo aterrissa depois do login. Desligar esse modulo
#    para um papel deixaria a pessoa entrar e nao ver nada, sem lugar para ir.
#
# As telas de consulta especificas (historico, vencidos, duplicidades) SAO
# governadas pela matriz; so a listagem geral fica aberta a quem esta
# autenticado, como sempre esteve.
@router.get("/api/certificados", dependencies=[Depends(require_auth)])
def listar_certificados(
    fonte: str = Query(
        "auto",
        description="auto | remoto | local",
    ),
    pagina: Optional[int] = Query(None, ge=1, description="Com por_pagina, ativa paginação no servidor"),
    por_pagina: Optional[int] = Query(None, ge=1, le=2000),
    filtro_status: str = Query("todos", description="todos | validos | prestes_vencer | vencidos | erros"),
    busca: Optional[str] = Query(None, max_length=400),
    todas_filtradas: bool = Query(False, description="Exportação: todos os itens do filtro (até LISTAGEM_EXPORT_MAX)"),
    ocultar_ilegiveis: bool = Query(
        False,
        description="Exclui erro e fora_do_padrao da lista, da contagem e da exportação",
    ),
    filtro_sieg: str = Query("todos", description="todos | incluindo | no_sieg | fora (SIEG, 07/10/2026)"),
    ocultar_vencidos: bool = Query(
        False,
        description="Exclui vencidos da lista e da contagem; devolve `vencidos_ocultos`",
    ),
    ordenar: Optional[str] = Query(
        None,
        description="nome | status | emissao | vencimento | documento. Vazio = ordem alfabética por titular",
    ),
    direcao: str = Query("asc", description="asc | desc"),
    token: auth.TokenData = Depends(require_auth),
) -> JSONResponse:
    """
    * auto: usa o último snapshot ingerido se existir; senão leitura local.
    * remoto: só snapshot (404 se vazio).
    * local: sempre leitura no disco do servidor (pastas efetivas da config).

    Com ``pagina`` e ``por_pagina`` na query, devolve ``paginacao`` e ``resumo`` (painel).
    Sem esses parâmetros, mantém o comportamento antigo: lista completa em ``itens``.
    """
    e_admin = (token.role or "").strip().lower() == "admin"
    # Vencidos entraram no Início em 23/10/2026 (a página Vencidos foi unida a
    # ele). Quem a matriz deixa sem o módulo Vencidos continua sem vê-los.
    if not e_admin and not permissoes.pode(token.role or "", "vencidos", permissoes.NIVEL_LER):
        ocultar_vencidos = True
    # Ler o disco do servidor é do administrador (auditoria de 10/10/2026): a
    # varredura abre e decifra cada PFX da pasta, sem cache nem teto, e era
    # disparável por qualquer logado com `fonte=local`.
    if fonte == "local" and not e_admin:
        raise HTTPException(status_code=403, detail="A leitura direta da pasta do servidor é só do administrador.")
    try:
        sets = load_settings()
        snap = get_latest_snapshot()
        if not e_admin and not snap:
            # Sem inventário do agente, o `auto` caía na varredura do disco.
            # Para quem não é admin, a lista simplesmente ainda não existe.
            base = {"source_dir": "", "expired_dir": "", "itens": [], "data_source": "remoto",
                    "atualizado_em": datetime.now(timezone.utc).isoformat(), "machine_id": None}
        else:
            if (fonte == "local" or not snap) and not taxa.permitir(
                f"varredura-local:{(token.email or '').strip().lower()}", 10, 300
            ):
                # A varredura decifra cada PFX da pasta, sem cache: mesmo para
                # o administrador, repetida em laço ela ocupa o único processo
                # do portal (auditoria de 10/10/2026).
                raise HTTPException(status_code=429, detail="Muitas leituras da pasta em sequência. Aguarde alguns minutos.")
            base = _list_certificados_payload(sets, snap, fonte)
        # Dado pessoal do titular (responsável, CPF, nascimento, e-mail) nunca
        # sai pela lista, para ninguém: só pela rota de detalhes, no alcance
        # (Q7, 06/10/2026). A leitura do disco os trazia de `cert_to_public_dict`.
        base["itens"] = ordenar_por_titular([nome_publico.sem_dados_pessoais(it) for it in base.get("itens") or []])
        # A pasta do servidor só para admin (SECURITY_AUDIT #2): o operador
        # precisa do titular e do documento, não da árvore de diretórios.
        if not e_admin:
            base["itens"] = [nome_publico.sem_pasta(it) for it in base["itens"]]
            base["source_dir"] = base["expired_dir"] = ""
        # Ver é de todos; a carteira decide o que cada um INSTALA (08/10/2026,
        # adendo ao ADR 0001). Antes a lista era recortada pela carteira
        # (#5); agora cada item diz se a pessoa pode instalá-lo, e a barreira
        # da instalação (`assegurar_carteira`) continua a mesma.
        alcance = _documentos_ao_alcance(token)
        _marcar_instalaveis(base["itens"], alcance)
        # Operador sem Atribuição nenhuma vê a lista vazia. A tela precisa
        # distinguir isso de "o agente ainda não enviou dados" (01/10/2026):
        # o remédio é outro — pedir ao Gestor, não esperar o agente.
        base["alcance_vazio"] = isinstance(alcance, set) and not alcance
        # Caixa alta vira título no servidor (app/nomes.py), num lugar só,
        # para toda tela que lista o inventário (Início, Custódia).
        for it in base["itens"]:
            it["nome_exibicao"] = nomes.nome_exibicao(it.get("nome") or it.get("display_name"))

        # Paginação por padrão (achado #29): sem `pagina`/`por_pagina` a rota
        # devolvia a lista inteira. A exportação continua pelo `todas_filtradas`,
        # que já tem o próprio teto.
        if pagina is None and por_pagina is None and not todas_filtradas:
            pagina, por_pagina = 1, 100
        paged = pagina is not None and por_pagina is not None
        if not paged and not todas_filtradas:
            return JSONResponse({**base, "banco": banco_configurado()})

        now = datetime.now(timezone.utc)
        thirty = now + timedelta(days=30)
        enriched = [_enrich_cert_item_dashboard_flags(it, now, thirty) for it in (base.get("itens") or [])]
        # Estado no SIEG por linha (selo e filtro do Início): uma consulta só,
        # por fingerprint. Sem a tabela (migration pendente) vem vazio.
        _sieg = sieg.estados(it.get("fingerprint_sha256") for it in enriched)
        for it in enriched:
            e = _sieg.get((it.get("fingerprint_sha256") or "").lower())
            it["sieg_estado"] = e["estado"] if e else None
        # A exclusao entra AQUI, junto dos outros filtros, e nao depois: daqui
        # saem a listagem, o `resumo` dos cards, a contagem de paginas e a
        # exportacao. Filtrar mais tarde daria uma pagina de 100 com 91 linhas e
        # cards que nao batem com a tabela.
        #
        # `ocultar_ilegiveis` e OPT-IN. O mesmo endpoint atende o
        # `scripts/diagnostico.py`, que existe justamente para achar arquivo
        # ilegivel — mudar o padrao cegaria a ferramenta de diagnostico.
        filtered = [
            it
            for it in enriched
            if _dashboard_filtro_status_match(it, filtro_status)
            and _dashboard_busca_match(it, busca or "")
            and not (ocultar_ilegiveis and _e_ilegivel(it))
            and _sieg_filtro_match(it, filtro_sieg)
        ]
        # Vencidos fora da lista para quem não tem o módulo Vencidos (ver o
        # início da função); a contagem vai junto em `vencidos_ocultos`.
        vencidos_ocultos = 0
        if ocultar_vencidos:
            vencidos = [it for it in filtered if _e_vencido(it)]
            vencidos_ocultos = len(vencidos)
            filtered = [it for it in filtered if not _e_vencido(it)]
        base["vencidos_ocultos"] = vencidos_ocultos
        # Antes do `resumo` e da paginacao, e pelo mesmo motivo que a ordem
        # alfabetica ja era feita aqui: ordenar no navegador ordenaria so os 25
        # itens da pagina visivel, e a lista PARECERIA certa enquanto
        # continuasse errada entre paginas.
        #
        # Sem `ordenar`, nada muda: a lista ja chega ordenada por titular de
        # `_list_certificados_payload`, e essa continua sendo a ordem de fabrica.
        if ordenar:
            filtered = _ordenar_listagem(filtered, ordenar, direcao)

        resumo = _dashboard_resumo_counts(filtered)

        if todas_filtradas:
            lista_truncada = len(filtered) > LISTAGEM_EXPORT_MAX
            return JSONResponse(
                {
                    **base,
                    "itens": filtered[:LISTAGEM_EXPORT_MAX],
                    "resumo": resumo,
                    "lista_truncada": lista_truncada,
                    "banco": banco_configurado(),
                }
            )

        pp = int(por_pagina or 20)
        total = len(filtered)
        total_pags = max(1, (total + pp - 1) // pp) if total else 1
        pagina_in = min(max(1, int(pagina or 1)), total_pags)
        off = (pagina_in - 1) * pp
        page_items = filtered[off : off + pp]
        return JSONResponse(
            {
                **base,
                "itens": page_items,
                "resumo": resumo,
                "paginacao": {
                    "pagina": pagina_in,
                    "total_paginas": total_pags,
                    "total_itens": total,
                    "por_pagina": pp,
                    # Permite ao portal avisar sobre truncamento ANTES de exportar,
                    # em vez de só depois que o arquivo já foi gerado.
                    "export_max": LISTAGEM_EXPORT_MAX,
                },
                "banco": banco_configurado(),
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Erro em GET /api/certificados (fonte=%s)", fonte)
        raise HTTPException(
            status_code=500,
            detail="Falha ao listar certificados. Veja o log do servidor.",
        ) from e


def _escape_ilike_pattern(val: str) -> str:
    """Evita que % e _ do usuário interfiram com ILIKE."""
    return val.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _valor_or(val: str) -> str:
    """Valor da DSL `or_` entre aspas: vírgula e ponto do usuário deixam de
    ser sintaxe (SECURITY_AUDIT #34). `db_pg._desaspear` desfaz."""
    return '"' + val.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _filtro_or_da_busca(busca: str) -> str:
    """As três cláusulas da busca do histórico, com o texto do usuário como
    UM valor cada, sem chance de virar cláusula nova."""
    q = _valor_or("%" + _escape_ilike_pattern(busca) + "%")
    # `documento_numero` entra para a busca só com dígitos casar (01/10/2026).
    return f"nome.ilike.{q},nome_publico.ilike.{q},documento.ilike.{q},documento_numero.ilike.{q}"


def _normalize_ingest_items_status(items: List[dict], now: datetime) -> List[dict]:
    """
    Alinha gravacao com o criterio do painel: se not_after ja passou (UTC),
    marca status como expirado mesmo quando o agente enviou ok (ex.: relogio local desfasado).
    Nao altera erro, fora_do_padrao nem itens sem not_after valido.
    """
    min_dt = datetime.min.replace(tzinfo=timezone.utc)
    out: List[dict] = []
    for raw in items:
        it = dict(raw)
        s = str(it.get("status") or "").strip().lower()
        if s == CertStatus.OK.value:
            na = it.get("not_after")
            if na:
                exp = _parse_iso_utc(str(na))
                if exp > min_dt and exp < now:
                    it["status"] = CertStatus.EXPIRED.value
        out.append(it)
    return out


def _digits_only_doc(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _normalize_name_dup(value: Any) -> str:
    t = str(value or "").strip().lower()
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(t.split())


def _fingerprint_hex_from_row(row: dict) -> str:
    """SHA-256 (hex) do fingerprint do certificado; aceita chave antiga `cert_sha256` nos snapshots."""
    v = row.get("fingerprint_sha256") or row.get("cert_sha256")
    if v is None or not str(v).strip():
        return ""
    return str(v).strip().lower()


def _item_resumo_duplicidade(it: dict, incluir_pasta: bool = False) -> dict[str, Any]:
    fp = it.get("fingerprint_sha256") or it.get("cert_sha256")
    nome = it.get("nome") or it.get("display_name")
    out = {
        # O nome PÚBLICO do arquivo (SECURITY_AUDIT #2): o nome bruto carrega
        # a senha, e esta tela o mostrava copiável. A pasta só vai para admin
        # — é estrutura do servidor, e é ele quem vai lá apagar a cópia.
        "nome_publico": it.get("nome_publico"),
        "nome": nome,
        # Caixa alta vira título no servidor (app/nomes.py), como no Início e
        # no Vencidos; números e códigos do nome passam intactos.
        "nome_exibicao": nomes.nome_exibicao(nome),
        "documento": it.get("documento_formatado") or it.get("documento_numero"),
        "documento_numero": it.get("documento_numero"),
        "not_after": it.get("not_after"),
        "not_before": it.get("not_before"),
        "status": it.get("status"),
        "subject": it.get("subject"),
        "issuer": it.get("issuer"),
        "serial_number": it.get("serial_number"),
        "fingerprint_sha256": fp,
    }
    if incluir_pasta:
        out["pasta"] = it.get("pasta")
    return out


def _fingerprint_hex_resumo(m: dict) -> str:
    v = m.get("fingerprint_sha256")
    if v is None or not str(v).strip():
        return ""
    return str(v).strip().lower()


def _filtrar_grupo_documento_apos_fingerprint(members: List[dict]) -> List[dict]:
    """
    Remove da lista «mesmo documento» os arquivos que já entram no agrupamento
    por fingerprint (2+ com o mesmo SHA-256). A duplicidade criptográfica é a
    validação definitiva; o grupo por documento fica para CPF/CNPJ igual sem
    fingerprint ou com certificados distintos (ex.: renovação).
    """
    by_fp: dict[str, List[dict]] = defaultdict(list)
    sem_fp: List[dict] = []
    for m in members:
        fp = _fingerprint_hex_resumo(m)
        if not fp:
            sem_fp.append(m)
        else:
            by_fp[fp].append(m)
    kept: List[dict] = []
    kept.extend(sem_fp)
    for _fp, grupo in by_fp.items():
        if len(grupo) < 2:
            kept.extend(grupo)
    return kept


def _agrupar_duplicidades(
    rows: List[dict],
    incluir_pasta: bool = False,
) -> Tuple[List[dict], List[dict], List[dict]]:
    """
    Deteta duplicidades no mesmo inventário (último snapshot ou scan local):
    - mesmo CNPJ/CPF (11+ dígitos) em mais de um arquivo (exceto quando a duplicidade
      já é explicada só por fingerprint — aí fica só em certificados idênticos);
    - certificados idênticos: mesmo fingerprint (SHA-256 do DER) em mais de um arquivo;
    - nomes muito semelhantes (SequenceMatcher) só quando não existe fingerprint
      no inventário (export antigo do agente ou leitura falhou).
    """
    by_doc: dict[str, List[dict]] = defaultdict(list)
    for it in rows:
        d = _digits_only_doc(it.get("documento_numero") or it.get("documento_formatado"))
        if len(d) >= 11:
            by_doc[d].append(_item_resumo_duplicidade(it, incluir_pasta))

    grupos_documento: List[dict] = []
    for doc_digits, members in by_doc.items():
        if len(members) < 2:
            continue
        filtrados = _filtrar_grupo_documento_apos_fingerprint(members)
        if len(filtrados) < 2:
            continue
        exib = next((m.get("documento") for m in filtrados if m.get("documento")), doc_digits)
        grupos_documento.append(
            {
                "tipo": "documento",
                "documento_digitos": doc_digits,
                "documento_exibicao": exib,
                "itens": filtrados,
            }
        )

    by_fp: dict[str, List[dict]] = defaultdict(list)
    for it in rows:
        fp = _fingerprint_hex_from_row(it)
        if not fp:
            continue
        by_fp[fp].append(_item_resumo_duplicidade(it, incluir_pasta))

    grupos_cert_igual: List[dict] = []
    for fp_hex, members in by_fp.items():
        if len(members) < 2:
            continue
        grupos_cert_igual.append(
            {
                "tipo": "certificado_igual",
                "fingerprint_sha256": fp_hex,
                "itens": members,
            }
        )

    n = len(rows)
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # Vizinhança ordenada (achado #12): os nomes normalizados vão em ordem e
    # cada um se compara só com os `_JANELA_NOMES` seguintes. O laço era n²
    # sobre o inventário inteiro — para 1.000 itens, 500 mil `SequenceMatcher`
    # por requisição, num worker só, aberto a todo papel. Dois nomes com razão
    # ≥ 0,86 diferem em poucos caracteres e ficam vizinhos na ordenação; o que
    # a poda perde é o par que difere logo no início ("A PADARIA" / "PADARIA"),
    # que a razão 0,86 também dificilmente aceitaria. Não é um bloco por
    # prefixo de propósito: inventário em que todos os nomes começam pela
    # mesma palavra cairia num bloco só, e voltaria a n².
    candidatos: List[Tuple[int, str, str, str]] = []
    for i in range(n):
        if _fingerprint_hex_from_row(rows[i]):
            continue
        fi = str(rows[i].get("nome_publico") or "").strip().lower()
        if not fi:
            continue
        ni = _normalize_name_dup(
            rows[i].get("nome") or rows[i].get("display_name") or rows[i].get("nome_publico")
        )
        if len(ni) < 5:
            continue
        di = _digits_only_doc(rows[i].get("documento_numero") or rows[i].get("documento_formatado"))
        candidatos.append((i, fi, ni, di))

    candidatos.sort(key=lambda c: c[2])
    for a in range(len(candidatos)):
        i, fi, ni, di = candidatos[a]
        for b in range(a + 1, min(a + 1 + _JANELA_NOMES, len(candidatos))):
            j, fj, nj, dj = candidatos[b]
            if fi == fj:
                continue
            if len(di) >= 11 and len(dj) >= 11 and di == dj:
                continue
            if SequenceMatcher(None, ni, nj).ratio() >= 0.86:
                union(i, j)

    roots: dict[int, List[int]] = defaultdict(list)
    for i in range(n):
        roots[find(i)].append(i)

    grupos_nome: List[dict] = []
    for _root, idxs in roots.items():
        if len(idxs) < 2:
            continue
        members = [_item_resumo_duplicidade(rows[k], incluir_pasta) for k in idxs]
        nomes_cur = [
            _normalize_name_dup(
                rows[k].get("nome") or rows[k].get("display_name") or rows[k].get("nome_publico")
            )
            for k in idxs
        ]
        rotulo = max(nomes_cur, key=len) if nomes_cur else "—"
        grupos_nome.append({"tipo": "nome_similar", "rotulo": rotulo[:120], "itens": members})

    return grupos_documento, grupos_nome, grupos_cert_igual


def _doc_norm(v: Any) -> str:
    return re.sub(r"\D+", "", str(v or ""))


def _parse_dt_or_min(v: Any) -> datetime:
    return _parse_iso_utc(str(v or ""))


def _status_prioridade(status: str) -> int:
    s = str(status or "").lower()
    if s in ("ok", "valido", "válido"):
        return 3
    if s in ("expirado", "vencido"):
        return 2
    if s in ("erro",):
        return 1
    return 0










def _lista_base_docs_historico() -> List[dict]:
    """Um item por DOCUMENTO, escolhendo o certificado que responde a pergunta
    "este cliente esta coberto?".

    Le o INVENTARIO, e nao `cert_history`. A troca corrigiu um defeito que so
    aparecia em cliente que renovou o certificado:

    `cert_history` faz upsert por `arquivo_chave` (nome publico + fingerprint), e o fluxo normal do escritorio
    produz DOIS arquivos com o mesmo nome — o novo na pasta de trabalho e o
    antigo movido para `99.CERTIFICADOS VENCIDOS`. Os dois colidiam numa linha
    so, e sobrava o ultimo processado. Em 22/08 eram 7 nomes repetidos, 5 deles
    com um valido e um vencido: para esses cinco clientes o Acompanhamento
    mostrava VENCIDO existindo certificado valido — e o dano e concreto, porque
    sugere renovar o que acabou de ser renovado.

    A regra de prioridade abaixo ja existia e ja estava certa. Ela nunca chegava
    a ser aplicada porque o valido nao estava na base.
    """
    sets = load_settings()
    snap = get_latest_snapshot()
    payload = _list_certificados_payload(sets, snap, "auto")
    now = datetime.now(timezone.utc)

    grupos: Dict[str, dict] = {}
    for it in (payload.get("itens") or []):
        doc = _doc_norm(it.get("documento_formatado") or it.get("documento_numero"))
        if not doc:
            continue
        venc = it.get("not_after")
        cand = {
            "documento": it.get("documento_formatado") or it.get("documento_numero") or doc,
            "documento_digitos": doc,
            "nome": it.get("nome") or it.get("display_name") or "—",
            "status_ultimo": str(it.get("status") or "").lower(),
            "vencimento_certificado": venc,
            "ultima_data_registrada": venc,
            # Abre o modal de detalhes a partir de Vencidos (20/10/2026).
            "fingerprint_sha256": it.get("fingerprint_sha256"),
        }
        atual = grupos.get(doc)
        if not atual:
            grupos[doc] = cand
            continue

        pa = _status_prioridade(atual.get("status_ultimo", ""))
        pc = _status_prioridade(cand.get("status_ultimo", ""))
        if pc > pa:
            grupos[doc] = cand
            continue
        if pc == pa:
            # Empate: vence o de validade MAIS DISTANTE.
            #
            # Entre dois validos, e o que diz ate quando o cliente esta coberto.
            # Entre dois vencidos, e o que venceu por ultimo — o mais proximo de
            # ainda valer, e o que a pessoa reconhece.
            da = _parse_dt_or_min(atual.get("vencimento_certificado"))
            dc = _parse_dt_or_min(cand.get("vencimento_certificado"))
            if dc > da:
                grupos[doc] = cand
    return sorted(grupos.values(), key=lambda x: (x.get("nome") or "").lower())


@router.get("/api/certificados/{fingerprint}/detalhes", dependencies=[Depends(require_auth)])
def detalhes_do_certificado(
    fingerprint: str = PathParam(..., min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$"),
    token: auth.TokenData = Depends(require_auth),
) -> dict:
    """Modal do Início: o item do inventário com os dados do responsável.

    Desde 08/10/2026 todos veem todos os certificados; a carteira decide só
    quem instala. Fora da carteira o modal abre com os dados do certificado,
    mas SEM os dados pessoais do responsável (eles continuam guardados pelo
    alcance, decisão Q7 de 06/10/2026) e com `instalavel: false`. A pasta e o
    nome do arquivo seguem só para o administrador, como na lista.
    """
    fp = fingerprint.lower()
    snap = get_latest_snapshot(com_dados_pessoais=True) or {}
    item = next((it for it in (snap.get("items") or []) if (it.get("fingerprint_sha256") or "").lower() == fp), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Certificado não encontrado.")
    # Identidade de máquina não é pessoa: o alcance total do agente serve à
    # varredura, não a este modal, que nenhum agente chama (auditoria de
    # 10/10/2026). Sem isto, a credencial de uma estação lia CPF, nascimento e
    # e-mail de todos os titulares.
    agente = (token.role or "").strip().lower() == "agent"
    instalavel = not agente and _no_alcance(item, _documentos_ao_alcance(token))
    if not instalavel:
        from app.nome_publico import sem_dados_pessoais

        item = sem_dados_pessoais(item)
    saida = dict(item)
    saida["instalavel"] = instalavel
    if (token.role or "").strip().lower() != "admin":
        saida = nome_publico.sem_pasta(saida)
        saida.pop("nome_publico", None)
    saida["nome_exibicao"] = nomes.nome_exibicao(item.get("nome") or item.get("display_name"))
    saida["no_cofre"] = _no_cofre(fp)
    # Inventário de agente anterior à 1.7.0: emissor e cadeia saem do texto
    # do emissor e do sujeito, que sempre vieram. O responsável não tem de
    # onde sair e fica ausente (a tela explica).
    if not saida.get("emissor"):
        saida["emissor"] = _atributo_rfc4514(item.get("issuer"), "CN")
    if not saida.get("organizacao"):
        saida["organizacao"] = _atributo_rfc4514(item.get("subject"), "O")
    return saida


def _atributo_rfc4514(dn: Optional[str], nome: str) -> Optional[str]:
    """Primeiro valor de `nome` num DN RFC 4514 ("CN=AC X,O=ICP-Brasil,C=BR")."""
    if not dn:
        return None
    m = re.search(r"(?:^|,)\s*" + re.escape(nome) + r"=((?:\\.|[^,\\])+)", dn, re.IGNORECASE)
    if not m:
        return None
    return re.sub(r"\\(.)", r"\1", m.group(1)).strip() or None


_dup_cache: Dict[Tuple[str, str, bool], Tuple[float, Tuple[list, list, list]]] = {}
_dup_cache_lock = threading.Lock()


def _dup_cache_limpar() -> None:
    with _dup_cache_lock:
        _dup_cache.clear()


@router.get("/api/certificados/duplicidades", dependencies=[Depends(require_modulo("duplicidades"))])
def certificados_duplicidades(request: Request, token: auth.TokenData = Depends(require_auth)) -> dict[str, Any]:
    """
    Analisa o último snapshot recebido (dados atuais do agente) ou, na ausência,
    o scan local no servidor, e devolve grupos de possíveis duplicados.

    Os itens saem com o nome PÚBLICO do arquivo; a pasta só para admin
    (SECURITY_AUDIT #2). Sanitizado na saída porque um snapshot anterior à
    migração do lote 3 ainda carrega o nome com a senha.

    A análise é memoizada por varredura (achado #12): o snapshot não muda
    entre duas leituras, e recalcular era o laço n² mais caro do portal num
    worker só. Quem força varredura nova a cada chamada esbarra no teto por
    identidade; quem manda um inventário maior que o teto recebe 413 em vez
    de derrubar o processo.
    """
    snap = get_latest_snapshot()
    origem = "ultimo_snapshot"
    scanned_at: Optional[str] = None
    if snap and (snap.get("items") or []):
        raw_items: List[dict] = list(snap.get("items") or [])
        scanned_at = str(snap.get("scanned_at") or "") or None
    else:
        sets = load_settings()
        raw_items = [cert_to_public_dict(c) for c in scan_folder(sets.effective_source())]
        origem = "scan_local_servidor"
        scanned_at = datetime.now(timezone.utc).isoformat()

    if len(raw_items) > MAX_ITENS_DUPLICIDADE:
        raise HTTPException(
            status_code=413,
            detail=f"Inventário com mais de {MAX_ITENS_DUPLICIDADE} itens: grande demais para a análise ao vivo.",
        )

    admin = (token.role or "").strip().lower() == "admin"
    # Recorte pelo Alcance (revisão de 01/10/2026): era a única leitura do
    # inventário sem recorte, num módulo aberto a Operador por padrão — um
    # operador com carteira vazia via nome, CNPJ, serial e fingerprint de todo
    # o acervo. Com recorte, o resultado é por pessoa e não vai ao cache.
    alcance = _documentos_ao_alcance(token)
    chave = (origem, str(scanned_at or ""), admin)
    agora = time.monotonic()
    guardado = None
    if alcance is None:
        with _dup_cache_lock:
            guardado = _dup_cache.get(chave)
    if guardado and agora - guardado[0] < _DUP_CACHE_TTL_SEG and origem == "ultimo_snapshot":
        gd, gn, gci = guardado[1]
        rows_total = sum(1 for it in raw_items if str((it.get("nome_publico") or it.get("file_name") or "")).strip())
    else:
        quem = (token.email or "").strip().lower() or _ip_do_cliente(request)
        if not taxa.permitir(f"dup:{quem}", 5, 300):
            raise HTTPException(status_code=429, detail="Limite de análises por pessoa atingido. Aguarde alguns minutos.")
        itens = [nome_publico.sanitizar_item(it) for it in raw_items]
        rows = [it for it in itens if str(it.get("nome_publico") or "").strip()]
        rows = _recortar_pela_carteira(rows, alcance)
        rows_total = len(rows)
        gd, gn, gci = _agrupar_duplicidades(rows, incluir_pasta=admin)
        if alcance is None:
            with _dup_cache_lock:
                if len(_dup_cache) > 32:
                    _dup_cache.clear()
                _dup_cache[chave] = (agora, (gd, gn, gci))
    return {
        "origem_dados": origem,
        "scanned_at": scanned_at,
        "total_itens_analisados": rows_total,
        "grupos_documento": gd,
        "grupos_nome_similar": gn,
        "grupos_certificado_igual": gci,
        "total_grupos_documento": len(gd),
        "total_grupos_nome_similar": len(gn),
        "total_grupos_certificado_igual": len(gci),
        "alcance_vazio": isinstance(alcance, set) and not alcance,
    }


def _historico_merge_snapshot_into_agregados(snap: dict[str, Any], agregados: Dict[str, dict]) -> None:
    """Acumula itens de um snapshot no mapa por `arquivo_chave` (mantém linha do scan mais recente).

    O item é sanitizado antes: snapshots anteriores à migração do lote 3 ainda
    trazem o nome do arquivo com a senha, e este agregado vai para a API."""
    scanned_at = snap.get("scanned_at") or datetime.now(timezone.utc).isoformat()
    scanned_dt = _parse_iso_utc(scanned_at)
    for bruto in (snap.get("items") or []):
        it = nome_publico.sanitizar_item(bruto)
        nome_pub = str(it.get("nome_publico") or "").strip()
        if not nome_pub:
            continue
        key = it["arquivo_chave"]
        atual = agregados.get(key)
        if (not atual) or (scanned_dt > atual["_dt"]):
            doc_raw = (
                it.get("documento_formatado") or it.get("documento_numero") or it.get("documento")
            )
            agregados[key] = {
                "_dt": scanned_dt,
                "nome_publico": nome_pub,
                "nome": it.get("nome") or it.get("display_name") or nome_pub,
                "status_ultimo": it.get("status"),
                "documento": doc_raw,
                "vencimento_certificado": it.get("not_after"),
                "ultima_data_registrada": scanned_dt.isoformat(),
            }


def _historico_carregar_agregados(limite_snapshots: int) -> Tuple[Dict[str, dict], int]:
    """
    Percorre snapshots (banco em lotes ou arquivo local) e devolve agregação por arquivo_chave.
    Resultado pode vir de cache em RAM (TTL configurável) por (banco ativo, limite).
    """
    from app.settings_state import _banco

    sb = _banco()
    uses_sb = sb is not None

    def _build() -> Tuple[Dict[str, dict], int]:
        agregados: Dict[str, dict] = {}
        snapshots_lidos = 0
        if sb:
            try:
                page_size = 50
                offset = 0
                while snapshots_lidos < limite_snapshots:
                    chunk = min(page_size, limite_snapshots - snapshots_lidos)
                    end = offset + chunk - 1
                    r = (
                        sb.table("cert_snapshots")
                        .select("scanned_at, items")
                        .order("scanned_at", desc=True)
                        .range(offset, end)
                        .execute()
                    )
                    rows = r.data or []
                    if not rows:
                        break
                    for snap in rows:
                        _historico_merge_snapshot_into_agregados(snap, agregados)
                    snapshots_lidos += len(rows)
                    offset += len(rows)
                    if len(rows) < chunk:
                        break
            except Exception as e:  # noqa: BLE001
                logger.exception("Falha ao ler histórico no banco")
                raise HTTPException(status_code=500, detail="Falha ao ler o histórico. Veja o log do servidor.") from e
        else:
            snap = get_latest_snapshot()
            if snap:
                _historico_merge_snapshot_into_agregados(snap, agregados)
                snapshots_lidos = 1
        return agregados, snapshots_lidos

    return _historico_cache_get_or_build(uses_sb, limite_snapshots, _build)


def _historico_itens_visualizacao(agregados: Dict[str, dict]) -> List[dict]:
    linhas = sorted(agregados.values(), key=lambda x: x["_dt"], reverse=True)
    return [{k: v for k, v in row.items() if k != "_dt"} for row in linhas]


# Filtro por status do Histórico (03/10/2026): o cartão Acervo ilegível do
# Dashboard aponta para cá. "ilegivel" é o par (erro, fora_do_padrao) que o
# Dashboard soma; os demais são o `status_ultimo` tal qual.
STATUS_HISTORICO = {
    "ilegivel": ("erro", "fora_do_padrao"),
    "erro": ("erro",),
    "fora_do_padrao": ("fora_do_padrao",),
    "ok": ("ok",),
    "expirado": ("expirado",),
}


def _historico_status_aceitos(status_raw: Optional[str]) -> Optional[tuple]:
    chave = str(status_raw or "").strip().lower()
    if not chave:
        return None
    if chave not in STATUS_HISTORICO:
        raise HTTPException(status_code=422, detail="Status desconhecido. Use: " + ", ".join(STATUS_HISTORICO))
    return STATUS_HISTORICO[chave]


def _historico_filtrar_status(itens: List[dict], aceitos: Optional[tuple]) -> List[dict]:
    if not aceitos:
        return itens
    return [it for it in itens if str(it.get("status_ultimo") or "").lower() in aceitos]


def _historico_filtrar_busca(itens: List[dict], busca_raw: str) -> List[dict]:
    q = str(busca_raw or "").strip().lower()
    if not q:
        return itens
    out: List[dict] = []
    for it in itens:
        haystack = (
            f"{it.get('nome_publico') or ''} {it.get('nome') or ''} {it.get('documento') or ''} "
            f"{_doc_norm(it.get('documento'))} "
            f"{it.get('ultima_data_registrada') or ''} {it.get('vencimento_certificado') or ''}"
        ).lower()
        if q in haystack:
            out.append(it)
    return out


_RE_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _data_da_query(valor: Optional[str], nome: str, sufixo: str) -> Optional[datetime]:
    """YYYY-MM-DD de verdade, ou 422. Vazio é "sem filtro"."""
    if not valor:
        return None
    v = valor.strip()
    if not _RE_DATA.match(v):
        raise HTTPException(status_code=422, detail=f"{nome} precisa estar no formato AAAA-MM-DD.")
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{nome} não é uma data válida.")
    return _parse_iso_utc(v + sufixo)


def _vencidos_filtrar_busca(rows: List[dict], busca_raw: str) -> List[dict]:
    if not str(busca_raw or "").strip():
        return rows
    raw = str(busca_raw).strip()
    bt = _painel_busca_normalizada(raw)
    bd = re.sub(r"\D", "", raw)
    out: List[dict] = []
    for it in rows:
        nome = _painel_busca_normalizada(it.get("nome") or "")
        doc_txt = _painel_busca_normalizada(it.get("documento") or "")
        doc_d = _digits_only_doc(it.get("documento") or "")
        venc_txt = _painel_busca_normalizada(it.get("vencimento_certificado") or "")
        vn = _digits_only_doc(str(it.get("vencimento_certificado") or ""))
        if bt and bt in nome:
            out.append(it)
            continue
        if bt and bt in doc_txt:
            out.append(it)
            continue
        if bt and bt in venc_txt:
            out.append(it)
            continue
        if bd and bd in doc_d:
            out.append(it)
            continue
        if bd and bd in vn:
            out.append(it)
            continue
    return out


def _cert_history_fetch_all(sb: Any) -> List[dict[str, Any]]:
    """Lê todas as linhas de cert_history (PostgREST limita ~1000 por pedido sem range)."""
    cols = (
        "nome_publico, nome, documento, status_ultimo, "
        "vencimento_certificado, ultima_data_registrada"
    )
    batch = 1000
    out: List[dict[str, Any]] = []
    offset = 0
    while True:
        r = (
            sb.table("cert_history")
            .select(cols)
            .order("ultima_data_registrada", desc=True)
            .range(offset, offset + batch - 1)
            .execute()
        )
        chunk = r.data or []
        out.extend(chunk)
        if len(chunk) < batch:
            break
        offset += batch
    return out


def historico_certificados(
    limite_snapshots: int = 500,
    *,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    busca: Optional[str] = None,
    status: Optional[str] = None,
) -> dict:
    """
    Lista certificados já mapeados em algum momento, com a última data registrada.
    Com ``limit`` definido, lê só uma página de ``cert_history`` (menos carga).

    Chamadas internas devem omitir ``limit`` para obter a lista completa.
    """
    from app.settings_state import _banco

    pagination = limit is not None
    offset = max(0, int(offset or 0))
    page_limit = int(limit) if pagination else None
    busca_txt = str(busca).strip() if busca else ""
    status_aceitos = _historico_status_aceitos(status)

    def _normalize_rows(rows_raw: List[dict[str, Any]]) -> List[dict[str, Any]]:
        return [
            {
                "nome_publico":           row.get("nome_publico"),
                "nome":                   row.get("nome"),
                "documento":              row.get("documento"),
                "status_ultimo":          row.get("status_ultimo"),
                "vencimento_certificado": row.get("vencimento_certificado"),
                "ultima_data_registrada": row.get("ultima_data_registrada"),
            }
            for row in rows_raw
        ]

    def _apply_cert_history_or_busca(qb: Any) -> Any:
        if status_aceitos:
            qb = qb.in_("status_ultimo", list(status_aceitos))
        if not busca_txt:
            return qb
        return qb.or_(_filtro_or_da_busca(busca_txt))

    sb = _banco()
    if sb:
        _use_history_table = True
        rows_non_paginated: List[dict[str, Any]] = []
        try:
            if pagination and page_limit is not None:
                qc = _apply_cert_history_or_busca(
                    sb.table("cert_history").select("arquivo_chave", count="exact", head=True)
                )
                c_r = qc.execute()
                total_count = c_r.count if c_r.count is not None else 0

                if total_count > 0 or busca_txt or status_aceitos:
                    qp = _apply_cert_history_or_busca(
                        sb.table("cert_history")
                        .select(
                            "nome_publico, nome, documento, status_ultimo, "
                            "vencimento_certificado, ultima_data_registrada",
                        )
                        .order("ultima_data_registrada", desc=True)
                    )
                    hi = offset + page_limit - 1
                    p_r = qp.range(offset, hi).execute()
                    return {
                        "itens": _normalize_rows(p_r.data or []),
                        "total": total_count,
                        "offset": offset,
                        "limit": page_limit,
                        "snapshots_lidos": 0,
                        "fonte": "cert_history",
                    }

                # total_count == 0 e sem texto de busca → tentar snapshots (dados legados)
            else:
                rows_non_paginated = _cert_history_fetch_all(sb)
        except Exception as e:  # noqa: BLE001
            err_str = str(e)
            if db_pg.tabela_ausente(e) or "PGRST205" in err_str or "cert_history" in err_str:
                logger.warning(
                    "Tabela cert_history não encontrada; usando fallback de snapshots. "
                    "Aplique supabase/migrations/20260504_cert_history.sql no banco."
                )
                _use_history_table = False
                rows_non_paginated = []
            else:
                logger.exception("Falha inesperada ao ler cert_history no banco")
                raise HTTPException(status_code=500, detail="Falha ao ler o histórico. Veja o log do servidor.") from e

        if _use_history_table and rows_non_paginated and not pagination:
            # A busca vale também aqui (achado #54): este é o caminho da
            # exportação, e ele lia a tabela inteira ignorando o filtro.
            itens = _historico_filtrar_status(_historico_filtrar_busca(_normalize_rows(rows_non_paginated), busca_txt), status_aceitos)
            return {
                "itens": itens,
                "total": len(itens),
                "offset": 0,
                "limit": len(itens),
                "snapshots_lidos": 0,
                "fonte": "cert_history",
            }

    agregados, snapshots_lidos = _historico_carregar_agregados(limite_snapshots)
    itens = _historico_itens_visualizacao(agregados)
    itens = _historico_filtrar_status(_historico_filtrar_busca(itens, busca_txt), status_aceitos)

    if pagination and page_limit is not None:
        total_f = len(itens)
        fatia = itens[offset : offset + page_limit]
        return {
            "itens": fatia,
            "total": total_f,
            "offset": offset,
            "limit": page_limit,
            "snapshots_lidos": snapshots_lidos,
            "fonte": "snapshots",
        }

    return {
        "itens": itens,
        "total": len(itens),
        "offset": 0,
        "limit": len(itens),
        "snapshots_lidos": snapshots_lidos,
        "fonte": "snapshots",
    }


@router.get("/api/certificados/historico", dependencies=[Depends(require_modulo("historico"))])
def historico_certificados_http(
    limite_snapshots: int = Query(
        500,
        ge=1,
        le=2000,
        description="Máximo de snapshots no fallback (quando cert_history está vazio)",
    ),
    pagina: int = Query(1, ge=1, description="Página (1-based)"),
    por_pagina: int = Query(20, ge=1, le=2000, description="Registros por página"),
    todas_filtradas: bool = Query(
        False,
        description="Quando true, devolve toda a lista filtrada (exportação; pode truncar)",
    ),
    busca: Optional[str] = Query(
        None,
        max_length=200,
        description="Filtro parcial em nome, arquivo ou documento",
    ),
    status: Optional[str] = Query(
        None,
        max_length=20,
        description="Status da última verificação: ilegivel, erro, fora_do_padrao, ok ou expirado",
    ),
    token: auth.TokenData = Depends(require_auth),
) -> dict:
    b = busca.strip() if busca else None
    st = status.strip().lower() if status else None
    _historico_status_aceitos(st)  # 422 antes de tocar o banco
    alcance = _documentos_ao_alcance(token)
    # A tela mostra "Atualizado em" e distingue carteira vazia de histórico
    # vazio; os dois campos faltavam na resposta (revisão de 01/10/2026).
    extras = {
        "alcance_vazio": isinstance(alcance, set) and not alcance,
        "atualizado_em": (get_latest_snapshot() or {}).get("scanned_at") or datetime.now(timezone.utc).isoformat(),
    }
    if todas_filtradas:
        raw = historico_certificados(limite_snapshots, offset=None, limit=None, busca=b, status=st)
        itens = _recortar_pela_carteira(list(raw.get("itens") or []), alcance)
        lista_truncada = len(itens) > LISTAGEM_EXPORT_MAX
        return {
            **extras,
            "itens": itens[:LISTAGEM_EXPORT_MAX],
            "total": len(itens),
            "snapshots_lidos": raw.get("snapshots_lidos", 0),
            "fonte": raw.get("fonte"),
            "lista_truncada": lista_truncada,
        }

    off = (pagina - 1) * por_pagina
    if alcance is not None:
        # Com recorte, a página é cortada DEPOIS do recorte, aqui: paginar no
        # banco e recortar depois daria páginas com buracos e um total que
        # conta o que a pessoa não pode ver (#5).
        raw = historico_certificados(limite_snapshots, offset=None, limit=None, busca=b, status=st)
        recortados = _recortar_pela_carteira(list(raw.get("itens") or []), alcance)
        raw = {**raw, "itens": recortados[off: off + por_pagina], "total": len(recortados),
               "offset": off, "limit": por_pagina}
    else:
        raw = historico_certificados(
            limite_snapshots,
            offset=off,
            limit=por_pagina,
            busca=b,
            status=st,
        )
    total = int(raw.get("total") or 0)
    total_pags = max(1, (total + por_pagina - 1) // por_pagina) if total else 1
    pagina_out = min(max(1, pagina), total_pags)
    out = dict(raw)
    out.update(extras)
    out["paginacao"] = {
        "pagina": pagina_out,
        "total_paginas": total_pags,
        "total_itens": total,
        "por_pagina": por_pagina,
        "export_max": LISTAGEM_EXPORT_MAX,
    }
    return out


@router.get("/api/certificados/vencidos", dependencies=[Depends(require_modulo("vencidos"))])
def vencidos_certificados(
    data_inicio: Optional[str] = Query(None, description="Data inicial (YYYY-MM-DD) pelo vencimento"),
    data_fim: Optional[str] = Query(None, description="Data final (YYYY-MM-DD) pelo vencimento"),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=2000),
    todas_filtradas: bool = Query(False, description="Lista completa filtrada (exportação; pode truncar)"),
    busca: Optional[str] = Query(None, max_length=200),
    limite_snapshots: int = Query(500, ge=1, le=2000, description="Quantidade máxima de snapshots lidos"),
    ordem: str = Query("desc", pattern="^(asc|desc)$", description="Ordem pelo vencimento: desc = mais recente primeiro"),
    token: auth.TokenData = Depends(require_auth),
) -> dict:
    # Data inválida é 422, não filtro ignorado (achado #54): `_parse_iso_utc`
    # devolvia `datetime.min` para "abc" e a tela mostrava a lista inteira como
    # se o filtro tivesse valido.
    inicio_dt = _data_da_query(data_inicio, "data_inicio", "T00:00:00+00:00")
    fim_dt = _data_da_query(data_fim, "data_fim", "T23:59:59+00:00")

    # Vencido é o CLIENTE cujo certificado vigente venceu, no inventário atual
    # (decisão D1, 01/10/2026). Até 30/09 a lista vinha de `cert_history` por
    # arquivo: um cliente renovado aparecia com o certificado antigo, e um
    # arquivo que saiu da pasta continuava "vencido" para sempre. A base agora
    # é a mesma do Acompanhamento e do sino — um item por Documento.
    alcance = _documentos_ao_alcance(token)
    itens_hist = _recortar_pela_carteira(_lista_base_docs_historico(), alcance)
    snap_atual = get_latest_snapshot() or {}
    hist = {"snapshots_lidos": 1 if snap_atual else 0}
    extras = {
        "alcance_vazio": isinstance(alcance, set) and not alcance,
        "atualizado_em": snap_atual.get("scanned_at") or datetime.now(timezone.utc).isoformat(),
    }
    busca_txt = str(busca or "").strip() or None

    now_utc = datetime.now(timezone.utc)
    min_dt = datetime.min.replace(tzinfo=timezone.utc)

    def _conta_como_certificado_vencido(it: dict) -> bool:
        """Inclui `expirado`/`vencido` no status ou data de validade já passada (alinha ao painel)."""
        s = str(it.get("status_ultimo") or "").lower()
        if s in ("expirado", "vencido"):
            return True
        venc_dt = _parse_iso_utc(it.get("vencimento_certificado"))
        if venc_dt <= min_dt:
            return False
        return venc_dt < now_utc

    venc_filtrados: List[dict] = []
    for it in itens_hist:
        if not _conta_como_certificado_vencido(it):
            continue
        venc_dt = _parse_iso_utc(it.get("vencimento_certificado"))
        s_low = str(it.get("status_ultimo") or "").lower()
        if inicio_dt or fim_dt:
            if venc_dt <= min_dt:
                if s_low not in ("expirado", "vencido"):
                    continue
            else:
                if inicio_dt and venc_dt < inicio_dt:
                    continue
                if fim_dt and venc_dt > fim_dt:
                    continue
        venc_filtrados.append(it)

    venc_filtrados = _vencidos_filtrar_busca(venc_filtrados, busca_txt or "")

    # Ordem pelo vencimento, mais recente primeiro por padrão: quem abre a
    # tela quer o que acabou de vencer, não o de 2019. Antes a lista vinha na
    # ordem da agregação do histórico, que a pessoa lia como aleatória. Quem
    # não tem data vai para o fim nas duas direções. A ordenação é sobre a
    # lista inteira, antes do corte da página.
    venc_filtrados.sort(
        key=lambda it: _parse_iso_utc(it.get("vencimento_certificado")),
        reverse=(ordem == "desc"),
    )
    if ordem == "asc":
        sem_data = [it for it in venc_filtrados if _parse_iso_utc(it.get("vencimento_certificado")) <= min_dt]
        venc_filtrados = [it for it in venc_filtrados if _parse_iso_utc(it.get("vencimento_certificado")) > min_dt] + sem_data

    # Nome legível decidido aqui, num lugar só (ver app/nomes.py); o original
    # continua em `nome` para busca e exportação.
    venc_filtrados = [{**it, "nome_exibicao": nomes.nome_exibicao(it.get("nome"))} for it in venc_filtrados]

    anos_cnt: defaultdict[int, int] = defaultdict(int)
    for it in venc_filtrados:
        venc_dt = _parse_iso_utc(it.get("vencimento_certificado"))
        y = int(venc_dt.year)
        if y < 1900:
            continue
        anos_cnt[y] += 1
    resumo_anos = [{"ano": ano, "total": anos_cnt[ano]} for ano in sorted(anos_cnt.keys(), reverse=True)]

    total = len(venc_filtrados)
    if todas_filtradas:
        lista_truncada = total > LISTAGEM_EXPORT_MAX
        return {
            **extras,
            "itens": venc_filtrados[:LISTAGEM_EXPORT_MAX],
            "total": total,
            "data_inicio": data_inicio,
            "data_fim": data_fim,
            "snapshots_lidos": hist.get("snapshots_lidos", 0),
            "lista_truncada": lista_truncada,
            "resumo_anos": resumo_anos,
        }

    total_pags = max(1, (total + por_pagina - 1) // por_pagina) if total else 1
    pagina_out = min(max(1, pagina), total_pags)
    off_pg = (pagina_out - 1) * por_pagina
    pagina_slice = venc_filtrados[off_pg : off_pg + por_pagina]

    return {
        **extras,
        "itens": pagina_slice,
        "total": total,
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "ordem": ordem,
        "snapshots_lidos": hist.get("snapshots_lidos", 0),
        "resumo_anos": resumo_anos,
        "paginacao": {
            "pagina": pagina_out,
            "total_paginas": total_pags,
            "total_itens": total,
            "por_pagina": por_pagina,
            "export_max": LISTAGEM_EXPORT_MAX,
        },
    }


# Ingestao de inventario: quem alimenta e o agente (`agent/run_agent.py`), e
# `require_auth` aceitava qualquer autenticado — um operador comum podia
# sobrescrever o inventario inteiro. `require_agent_or_admin` e a mesma guarda
# que `upload-pfx`, `redeem` e `report` ja usam, e o agente ja passa por ela em
# producao (o cofre tem 491 certificados que so chegaram por `upload-pfx`).
_ultimo_disparo_por_ingest = 0.0
_ingest_disparo_lock = threading.Lock()


def _pode_disparar_alerta_por_ingest() -> bool:
    global _ultimo_disparo_por_ingest
    with _ingest_disparo_lock:
        agora = time.monotonic()
        if agora - _ultimo_disparo_por_ingest < _INGEST_ALERTA_DEBOUNCE_SEG:
            return False
        _ultimo_disparo_por_ingest = agora
        return True


@router.post("/api/ingest")
def ingest(
    body: IngestBody,
    background_tasks: BackgroundTasks,
    token: auth.TokenData = Depends(require_agent_or_admin),
) -> dict:
    """
    Recebe o resultado de um scan feito no Windows (agente em segundo plano).
    Persiste no banco (ou em data/last_ingest.json se o banco não estiver configurado).
    Também faz upsert na tabela materializada cert_history para acelerar o histórico.

    O inventário é o da máquina que a credencial prova ser (achado #4): ele
    alimenta a barreira de custódia do cofre, e um agente que escrevesse o
    inventário de OUTRA estação escolhia o que ela pode enviar.
    """
    machine_id = _machine_da_credencial(token, body.machine_id) or "default"
    scanned = datetime.now(timezone.utc)
    # O nome do arquivo carrega a senha do PFX; ele não entra no banco por
    # nenhum caminho (SECURITY_AUDIT #2). Um agente antigo ainda o manda —
    # aqui ele vira nome público, pasta e chave, e o bruto é descartado.
    items = [nome_publico.sanitizar_item(it) for it in _normalize_ingest_items_status(body.items, scanned)]
    # O que o portal já conhecia, ANTES de gravar este inventário: é contra
    # isto que "certificado novo" é decidido (cópia/renomeação não é novo).
    try:
        conhecidos = fingerprints_do_snapshot(get_latest_snapshot())
    except Exception:  # noqa: BLE001
        logger.exception("Sem o inventário anterior; todo arquivo inédito será tratado como certificado novo")
        conhecidos = set()
    save_snapshot(
        machine_id=machine_id,
        source_folder=body.source_folder.strip(),
        expired_folder=body.expired_folder.strip(),
        items=items,
    )
    # Atualiza a tabela materializada — operação rápida, não bloqueia o retorno.
    # Devolve o que nunca esteve nela: os certificados novos na pasta.
    novos = filtrar_ineditos(upsert_cert_history(
        machine_id=machine_id,
        scanned_iso=scanned.isoformat(),
        items=items,
    ) or [], conhecidos)
    # Aviso de certificado novo (30/09/2026): quem tem o cliente na carteira
    # e os administradores recebem por e-mail; o antispam por (certificado,
    # destinatário) mora em `novos_certificados`, então não há debounce aqui.
    # Desde 02/10/2026 o aviso pode esperar a hora cheia (um e-mail com todos
    # os novos da hora) — `agendar_ou_notificar` decide pela configuração.
    if novos:
        background_tasks.add_task(agendar_ou_notificar, novos)
    # Dispara e-mails de alerta em segundo plano para não bloquear a resposta
    # do agente — no máximo uma vez a cada `_INGEST_ALERTA_DEBOUNCE_SEG`
    # (achado #28): cada ingestão varria o acervo e enviava e-mails; várias
    # estações ingerindo em sequência eram várias varreduras completas.
    if _pode_disparar_alerta_por_ingest():
        background_tasks.add_task(trigger_all_alerts)
    return {
        "ok": True,
        "itens_recebidos": len(body.items),
        "novos": len(novos),
        "grava_em": "banco" if banco_configurado() else "arquivo local (data/last_ingest.json)",
    }


# Move arquivo de certificado no sistema de arquivos do servidor. Estava sob
# `require_auth` — qualquer autenticado. Nenhum template ou script do portal
# chama esta rota; ela e acionada fora da UI, e quem a aciona e operacao.
def _pasta_relativa(pasta: Path, raiz: Path) -> str:
    """`F:/certs/clientes` sob a raiz `F:/certs` → `clientes`; a própria raiz →
    ""; fora da raiz → só o último nome. Nunca o caminho absoluto (#53)."""
    try:
        rel = Path(pasta).resolve().relative_to(Path(raiz).resolve())
    except ValueError:
        return Path(pasta).name
    return "" if str(rel) == "." else rel.as_posix()


@router.post("/api/mover-vencidos", dependencies=[Depends(require_admin)])
def mover_vencidos() -> JSONResponse:
    """
    Só move arquivos no **mesmo** sistema de arquivos que corre o API (servidor acessa as pastas).
    Se a interface mostrar dados "remotos" vindos do agente, use o agendador no Windows
    (agente com --mover) para mover aí o disco local.
    """
    sets = load_settings()
    src = sets.effective_source()
    exp = sets.effective_expired()
    itens: List[CertInfo] = scan_folder(src)
    movidos: List[dict] = []
    erros: List[dict] = []

    for c in itens:
        if c.status != CertStatus.EXPIRED:
            continue
        # Nome público e pasta RELATIVA à raiz configurada, nunca o caminho
        # completo: o nome do arquivo carrega a senha do PFX (#2) e o caminho
        # absoluto desenha o disco do servidor (#53).
        rotulo = nome_publico.nome_publico_de_arquivo(c.file_name) or "(sem nome)"
        try:
            novo = move_to_expired(c, exp)
            movidos.append({"arquivo": rotulo, "de": _pasta_relativa(c.path.parent, src),
                            "para": _pasta_relativa(Path(novo).parent, exp)})
        except OSError as e:
            logger.error("Falha ao mover %s: %s", rotulo, e)
            erros.append({"arquivo": rotulo, "erro": "Não foi possível mover o arquivo. Veja o log do servidor."})

    return JSONResponse(
        {
            "movidos": movidos,
            "erros": erros,
            "total_movidos": len(movidos),
        }
    )
