"""Agregações do Dashboard.

**A decisão de agregação foi tomada por medição, não por instinto** — era o
maior risco técnico registrado no plano (§5.4). O que se mediu contra produção:

    snapshots só com scanned_at (317)     24,5 KB   0,59s
    UM snapshot com `items`              518,8 KB   0,42s
    cert_history (2 colunas, 1.029)       78,6 KB   0,28s
    install_log inteiro                   11,5 KB   0,21s
    cert_pfx_store (2 colunas, 489)       54,7 KB   0,22s

Varrer os 317 snapshots com `items` daria ~160 MB numa função serverless.
Impossível. Mas só **um** painel precisa dos itens — renovações —, e ele não
precisa de todos: renovação é a comparação entre o inventário de hoje e o de N
dias atrás, ou seja **dois** snapshots, ~1 MB.

Daí a divisão em dois endpoints. Os sete painéis baratos somam ~170 KB e não
podem ficar esperando o caro: quem abre o dashboard vê o que importa de
imediato, e as renovações preenchem depois.

Nenhuma tabela de métricas, nenhuma view materializada, nenhum job de
pré-cálculo. Seriam a resposta certa se o custo estivesse espalhado; ele está
concentrado num painel, e concentrado tem conserto mais simples.

**Regra de conteúdo (§5.1):** nenhum gráfico sem dado que o sustente. Instalação
tem dezenas de eventos e um punhado de usuários — número grande, funil e tabela;
série temporal só quando houver período que a justifique. Decoração num painel
destrói a confiança em todos os números ao lado.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app import cert_installer
from app.settings_state import _supabase

logger = logging.getLogger(__name__)

# Faixas da curva de vencimento. O "já vencido" vem primeiro porque é o único
# que exige ação imediata; o resto é planejamento.
FAIXAS_VENCIMENTO = [
    ("vencido", None, 0),
    ("ate_7_dias", 0, 7),
    ("ate_30_dias", 7, 30),
    ("ate_60_dias", 30, 60),
    ("ate_90_dias", 60, 90),
    ("acima_de_90", 90, None),
]


# O PostgREST devolve no máximo 1.000 linhas por requisição e **não avisa** que
# truncou: a resposta chega bem-formada, só que incompleta. Descoberto ao ver
# `cert_history` (1.029 linhas) reportar 1.000 na curva de vencimento — 29
# certificados sumindo em silêncio, e o erro crescendo junto com o acervo.
#
# É a mesma família de falha que este projeto vem encontrando: nada quebra,
# o número só fica errado. Por isso toda leitura de tabela que pode passar de
# mil linhas usa `_todas_as_linhas`.
LOTE_POSTGREST = 1000


def _todas_as_linhas(consulta, lote: int = LOTE_POSTGREST) -> List[dict]:
    """
    Percorre a consulta em páginas até esgotar.

    `consulta` é uma fábrica: recebe (inicio, fim) e devolve o query builder já
    montado. Precisa ser fábrica porque o builder do supabase-py acumula estado
    e não pode ser reexecutado com outro `range`.
    """
    out: List[dict] = []
    inicio = 0
    while True:
        pagina = consulta(inicio, inicio + lote - 1).execute().data or []
        out.extend(pagina)
        if len(pagina) < lote:
            return out
        inicio += lote
        if inicio > 200_000:   # rede de segurança contra laço infinito
            logger.warning("Paginação interrompida em %s linhas", len(out))
            return out


def _dt(valor: Any) -> Optional[datetime]:
    """Converte ISO-8601 tolerando 'Z' e ausência de fuso. None se não der."""
    if not valor:
        return None
    try:
        s = str(valor).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


# ──────────────────────────────────────────────────────────────────────────
# Painéis baratos
# ──────────────────────────────────────────────────────────────────────────

def painel_instalacao(dias: int = 30) -> Dict[str, Any]:
    """
    Funil e causas — reaproveitando a agregação da trilha.

    É o painel que mais aponta para trabalho concreto: em produção, as falhas
    registradas tinham causa única, e isso só aparece contando os motivos.
    """
    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    cadeias = cert_installer.cadeias_de_instalacao(limite=2000, desde=desde)
    resumo = cert_installer.resumo_das_cadeias(cadeias)
    resumo["dias"] = dias
    return resumo


def painel_cofre() -> Dict[str, Any]:
    """
    Cobertura: quanto do acervo é instalável pelo portal.

    Era 6% antes da inversão da custódia (33 de 560). O número sozinho justifica
    o painel — ninguém sabia dele até alguém somar as duas contagens.
    """
    client = _supabase()
    if not client:
        return {"erro": "Supabase não configurado"}

    try:
        linhas = _todas_as_linhas(
            lambda i, f: client.table("cert_pfx_store")
            .select("fingerprint, machine_id")
            .range(i, f)
        )
        snap = (
            client.table("cert_snapshots")
            .select("items")
            .order("scanned_at", desc=True)
            .limit(1)
            .execute()
        )
        itens = (snap.data or [{}])[0].get("items") or []
    except Exception as e:  # noqa: BLE001
        logger.exception("Falha no painel do cofre")
        return {"erro": str(e)}

    inventario = len(itens)
    guardados = len(linhas)
    return {
        "guardados": guardados,
        "inventario": inventario,
        "cobertura_pct": round(100 * guardados / inventario) if inventario else None,
        "por_maquina": dict(Counter(str(l.get("machine_id") or "?") for l in linhas)),
    }


def painel_agente(dias: int = 30) -> Dict[str, Any]:
    """
    Saúde do agente pelas varreduras — sem tocar em `items`.

    Detecta agente parado, que já custou 11 horas de silêncio em 10/08 e dois
    minutos de confusão em 14/08. Só `scanned_at` e `machine_id`: 24 KB para as
    317 linhas, contra 160 MB se viessem os itens junto.
    """
    client = _supabase()
    if not client:
        return {"erro": "Supabase não configurado"}

    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    try:
        linhas = _todas_as_linhas(
            lambda i, f: client.table("cert_snapshots")
            .select("scanned_at, machine_id")
            .gte("scanned_at", desde)
            .range(i, f)
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("Falha no painel do agente")
        return {"erro": str(e)}

    por_dia: Counter = Counter()
    ultima_por_maquina: Dict[str, str] = {}
    for l in linhas:
        quando = str(l.get("scanned_at") or "")
        if not quando:
            continue
        por_dia[quando[:10]] += 1
        maq = str(l.get("machine_id") or "?")
        if quando > ultima_por_maquina.get(maq, ""):
            ultima_por_maquina[maq] = quando

    agora = datetime.now(timezone.utc)
    maquinas = []
    for maq, quando in sorted(ultima_por_maquina.items()):
        d = _dt(quando)
        horas = round((agora - d).total_seconds() / 3600, 1) if d else None
        maquinas.append(
            {
                "machine_id": maq,
                "ultima_varredura": quando,
                "horas_atras": horas,
                # O agente roda a cada 24h por padrão. Passar de 36h não é
                # atraso de relógio — é sinal de que parou.
                "atrasado": horas is not None and horas > 36,
            }
        )

    return {
        "dias": dias,
        "varreduras": len(linhas),
        "por_dia": dict(sorted(por_dia.items())),
        "maquinas": maquinas,
    }


def painel_acervo() -> Dict[str, Any]:
    """
    Vencimento e legibilidade, de `cert_history`.

    `status_ultimo` conta os arquivos que o robô **não consegue ler** — e esses
    nunca vão ao cofre, logo nunca são instaláveis pelo portal. É trabalho
    concreto: cada um é um arquivo para arrumar na origem.
    """
    client = _supabase()
    if not client:
        return {"erro": "Supabase não configurado"}

    try:
        linhas = _todas_as_linhas(
            lambda i, f: client.table("cert_history")
            .select("vencimento_certificado, status_ultimo")
            .range(i, f)
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("Falha no painel do acervo")
        return {"erro": str(e)}

    agora = datetime.now(timezone.utc)
    faixas = {nome: 0 for nome, _, _ in FAIXAS_VENCIMENTO}
    sem_data = 0
    for l in linhas:
        d = _dt(l.get("vencimento_certificado"))
        if not d:
            sem_data += 1
            continue
        dias = (d - agora).total_seconds() / 86400
        for nome, minimo, maximo in FAIXAS_VENCIMENTO:
            if minimo is None and dias < 0:
                faixas[nome] += 1
                break
            if minimo is not None and dias >= minimo and (maximo is None or dias < maximo):
                faixas[nome] += 1
                break

    status = Counter(str(l.get("status_ultimo") or "?") for l in linhas)
    ilegiveis = status.get("erro", 0) + status.get("fora_do_padrao", 0)

    return {
        "total": len(linhas),
        "vencimento": faixas,
        "sem_data_de_vencimento": sem_data,
        "por_status": dict(status),
        # Somado de propósito: separados, "41 erro" e "36 fora do padrão"
        # parecem ruído; juntos, são 77 arquivos que ninguém consegue instalar.
        "ilegiveis": ilegiveis,
    }


def painel_alertas(dias: int = 30) -> Dict[str, Any]:
    """Fecha o ciclo: avisamos — e adiantou?"""
    client = _supabase()
    if not client:
        return {"erro": "Supabase não configurado"}

    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    try:
        linhas = _todas_as_linhas(
            lambda i, f: client.table("sent_alerts")
            .select("tipo_alerta, sent_at, destinatario")
            .gte("sent_at", desde)
            .range(i, f)
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("Falha no painel de alertas")
        return {"erro": str(e)}

    return {
        "dias": dias,
        "total": len(linhas),
        "por_tipo": dict(Counter(str(l.get("tipo_alerta") or "?") for l in linhas)),
        "destinatarios": len({str(l.get("destinatario") or "") for l in linhas if l.get("destinatario")}),
    }


def painel_acesso() -> Dict[str, Any]:
    """
    Quem pode usar o portal, e quem consegue instalar alguma coisa.

    Operador sem carteira não instala nada — é o comportamento correto (o
    acesso fecha por padrão), mas é também o que trava a primeira pessoa que
    abrir a tela. Melhor ver o número aqui do que descobrir pelo chamado.
    """
    client = _supabase()
    if not client:
        return {"erro": "Supabase não configurado"}

    try:
        us = _todas_as_linhas(
            lambda i, f: client.table("users").select("role, ativo").range(i, f)
        )
        cart = _todas_as_linhas(
            lambda i, f: client.table("carteira").select("user_id").range(i, f)
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("Falha no painel de acesso")
        return {"erro": str(e)}

    from app.auth import conta_ativa

    ativos = [u for u in us if conta_ativa(u)]
    operadores = [u for u in ativos if (u.get("role") or "").lower() == "user"]
    com_carteira = {str(c.get("user_id")) for c in cart}

    return {
        "usuarios_ativos": len(ativos),
        "por_papel": dict(Counter((u.get("role") or "?") for u in ativos)),
        "operadores": len(operadores),
        "operadores_com_carteira": len(com_carteira),
        "documentos_atribuidos": len(cart),
    }


def painel_atividade(dias: int = 30) -> Dict[str, Any]:
    """
    Atividade por usuário: última vez, ações no período, e o que travou.

    **Não é tempo de uso.** Ver `app/atividade.py` para o porquê — em resumo,
    tempo alto neste portal significa que a pessoa não achou o que queria, e um
    número que sobe quando a ferramenta piora não serve para decidir nada.

    Junta as duas fontes em vez de duplicá-las: `user_activity` tem os logins,
    `install_log` tem as instalações. Cada fato mora num lugar só.

    O campo que responde "quem travou" é `sem_sucesso`: entrou, pediu, e não
    concluiu nenhuma. É gente que provavelmente está esperando alguém — o
    gestor atribuir carteira, o agente enviar o certificado — sem saber disso.
    """
    client = _supabase()
    if not client:
        return {"erro": "Supabase não configurado"}

    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    try:
        atividades = _todas_as_linhas(
            lambda i, f: client.table("user_activity")
            .select("user_email, evento, ocorrido_em")
            .gte("ocorrido_em", desde)
            .range(i, f)
        )
        eventos_inst = _todas_as_linhas(
            lambda i, f: client.table("install_log")
            .select("user_email, event, status, created_at")
            .gte("created_at", desde)
            .range(i, f)
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("Falha no painel de atividade")
        return {"erro": str(e)}

    por_usuario: Dict[str, Dict[str, Any]] = {}

    def _slot(email: str) -> Dict[str, Any]:
        return por_usuario.setdefault(
            email,
            {
                "user_email": email,
                "logins": 0,
                "logins_negados": 0,
                "instalacoes_pedidas": 0,
                "instalacoes_concluidas": 0,
                "instalacoes_falhadas": 0,
                "ultima_atividade": None,
            },
        )

    def _marcar(slot: Dict[str, Any], quando: Optional[str]) -> None:
        if quando and (slot["ultima_atividade"] is None or quando > slot["ultima_atividade"]):
            slot["ultima_atividade"] = quando

    for a in atividades:
        email = str(a.get("user_email") or "").strip().lower()
        if not email:
            continue
        s = _slot(email)
        if a.get("evento") == "login":
            s["logins"] += 1
        elif a.get("evento") == "login_negado":
            s["logins_negados"] += 1
        _marcar(s, a.get("ocorrido_em"))

    for e in eventos_inst:
        email = str(e.get("user_email") or "").strip().lower()
        if not email:
            continue
        s = _slot(email)
        evento = e.get("event")
        if evento == "SOLICITADO":
            s["instalacoes_pedidas"] += 1
        elif evento == "CONCLUIDO":
            s["instalacoes_concluidas"] += 1
        elif evento == "ERRO" or e.get("status") == "FALHA":
            s["instalacoes_falhadas"] += 1
        _marcar(s, e.get("created_at"))

    usuarios = sorted(
        por_usuario.values(), key=lambda u: u["ultima_atividade"] or "", reverse=True
    )
    travados = [
        u for u in usuarios
        if u["instalacoes_pedidas"] and not u["instalacoes_concluidas"]
    ]

    return {
        "dias": dias,
        "usuarios": usuarios,
        "ativos_no_periodo": len(usuarios),
        "sem_sucesso": len(travados),
        # Sem login registrado no período não quer dizer que ninguém entrou:
        # a instrumentação começou em 15/08. Dizer isso evita concluir que o
        # portal está abandonado quando só falta histórico.
        "logins_registrados": sum(u["logins"] for u in usuarios),
    }


def visao_geral(dias: int = 30) -> Dict[str, Any]:
    """
    Os painéis baratos, numa chamada.

    Cada bloco falha por conta própria: um `{"erro": ...}` num painel não pode
    derrubar os outros seis. Dashboard que some inteiro por causa de uma tabela
    instável é pior que dashboard com um buraco declarado.
    """
    return {
        "dias": dias,
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "instalacao": painel_instalacao(dias),
        "cofre": painel_cofre(),
        "agente": painel_agente(dias),
        "acervo": painel_acervo(),
        "alertas": painel_alertas(dias),
        "acesso": painel_acesso(),
        "atividade": painel_atividade(dias),
    }


# ──────────────────────────────────────────────────────────────────────────
# Painel caro: renovações
# ──────────────────────────────────────────────────────────────────────────

def _validade_por_documento(items: List[dict]) -> Dict[str, str]:
    """Documento → maior `not_after` visto. O maior, porque renovar é avançar."""
    out: Dict[str, str] = {}
    for i in items:
        doc = cert_installer.so_digitos(i.get("documento_numero"))
        na = i.get("not_after")
        if doc and na and str(na) > out.get(doc, ""):
            out[doc] = str(na)
    return out


def painel_renovacoes(dias: int = 30, machine_id: str = "ANALISESRV") -> Dict[str, Any]:
    """
    Certificados renovados: compara o inventário de hoje com o de N dias atrás.

    **Não sai de `cert_history`**, apesar do nome daquela tabela: ela é
    `upsert(on_conflict="file_name")`, guarda só o estado atual, e o valor
    anterior foi sobrescrito. Quem tentar por lá obtém zero.

    Dois snapshots, ~1 MB — contra os ~160 MB que varrer todos custaria.

    **`referencia` não é detalhe.** As varreduras têm lacunas: pedir 30 dias
    pode devolver a comparação com uma de 54 dias atrás, e apresentar isso como
    "renovados nos últimos 30 dias" seria mentira. Quem chama recebe a data que
    foi realmente usada.
    """
    client = _supabase()
    if not client:
        return {"erro": "Supabase não configurado"}

    corte = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    try:
        atual = (
            client.table("cert_snapshots")
            .select("items, scanned_at")
            .eq("machine_id", machine_id)
            .order("scanned_at", desc=True)
            .limit(1)
            .execute()
        ).data or []
        anterior = (
            client.table("cert_snapshots")
            .select("items, scanned_at")
            .eq("machine_id", machine_id)
            .lte("scanned_at", corte)
            .order("scanned_at", desc=True)
            .limit(1)
            .execute()
        ).data or []
    except Exception as e:  # noqa: BLE001
        logger.exception("Falha no painel de renovações")
        return {"erro": str(e)}

    if not atual:
        return {"erro": f"Sem varredura para {machine_id}"}
    if not anterior:
        return {
            "sem_referencia": True,
            "motivo": (
                f"Não há varredura anterior a {dias} dias para {machine_id}. "
                "O histórico começa depois desse ponto."
            ),
            "atual": atual[0]["scanned_at"],
        }

    hoje = _validade_por_documento(atual[0].get("items") or [])
    antes = _validade_por_documento(anterior[0].get("items") or [])

    renovados = sorted(d for d, na in hoje.items() if d in antes and na > antes[d])
    novos = sorted(d for d in hoje if d not in antes)
    sairam = sorted(d for d in antes if d not in hoje)

    return {
        "dias_pedidos": dias,
        "referencia": anterior[0]["scanned_at"],
        "atual": atual[0]["scanned_at"],
        "documentos_hoje": len(hoje),
        "documentos_na_referencia": len(antes),
        "renovados": len(renovados),
        "novos": len(novos),
        # "Saíram" e não "sumiram": o agente move vencidos para a pasta de
        # expirados, então a saída é o fluxo normal do acervo. Chamar de
        # desaparecimento alarmaria por engano.
        "sairam": len(sairam),
        "amostra_renovados": renovados[:20],
    }
