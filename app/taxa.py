"""
Rate limit por chave que sobrevive ao serverless (item 13 da Frente 2 — R5).

O limitador anterior (`_claim_rate_limit` em main.py) era um dicionário em
memória de processo — e na Vercel cada instância tem o seu: o teto de 10
tentativas/minuto valia por instância, não por IP. Com cold starts frequentes,
um atacante paciente falava com várias instâncias e o limite real era
"10 × quantas instâncias a plataforma quiser subir". Memória de instância em
serverless não é limite; é sugestão.

Aqui a janela vive numa tabela pequena do Supabase (`rate_limit_tentativas`),
compartilhada por todas as instâncias. Cada tentativa é uma linha; permitir é
contar as linhas da chave dentro da janela. A poda é oportunista, na própria
chave, a cada chamada — o volume por chave é limitado pelo próprio teto, então
a tabela não cresce além de (chaves ativas × máximo).

── Falha do banco NÃO abre o portão nem fecha o portal ───────────────────

Sem Supabase (dev, ou indisponibilidade), cai na janela em memória — que é
exatamente o comportamento que existia antes: por instância, imperfeito, e
melhor que negar serviço a todo mundo por causa do limitador. A queda é
logada; um limitador que degrada em silêncio é o defeito que este módulo veio
corrigir.

── A corrida entre instâncias é aceita ───────────────────────────────────

Duas instâncias podem contar 9 ao mesmo tempo e ambas inserirem — o teto vira
11 por um instante. Rate limit é amortecedor, não catraca: o custo de fechar a
corrida (lock/RPC) não paga o ganho de uma tentativa a menos.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

TABELA = "rate_limit_tentativas"

# Poda: linhas desta chave mais velhas que isto saem a cada chamada. Muito
# maior que qualquer janela em uso, para nunca podar o que ainda conta.
IDADE_MAXIMA_SEG = 3600.0

_memoria: dict[str, list[float]] = {}
_memoria_lock = threading.Lock()


def _supabase():
    from app.settings_state import _supabase as _sb

    return _sb()


def _permitir_em_memoria(chave: str, maximo: int, janela_seg: float) -> bool:
    """A janela por instância — o fallback, e o comportamento antigo."""
    agora = time.time()
    with _memoria_lock:
        tentativas = [t for t in _memoria.get(chave, []) if agora - t < janela_seg]
        if len(tentativas) >= maximo:
            _memoria[chave] = tentativas
            return False
        tentativas.append(agora)
        _memoria[chave] = tentativas
        # Limpeza oportunista: chaves que apareceram uma vez não podem acumular.
        if len(_memoria) > 1000:
            for k in [
                k for k, v in _memoria.items() if not v or agora - v[-1] > janela_seg
            ]:
                _memoria.pop(k, None)
        return True


def permitir(chave: str, maximo: int, janela_seg: float) -> bool:
    """True se esta chave ainda pode tentar dentro da janela.

    Conta e registra no Supabase — o mapa vale para TODAS as instâncias. Sem
    banco, degrada para a janela em memória com aviso no log.
    """
    client = _supabase()
    if client:
        agora = datetime.now(timezone.utc)
        corte_janela = (agora - timedelta(seconds=janela_seg)).isoformat()
        try:
            r = (
                client.table(TABELA)
                .select("id")
                .eq("chave", chave)
                .gte("quando", corte_janela)
                .execute()
            )
            if len(r.data or []) >= maximo:
                return False
            client.table(TABELA).insert(
                {"chave": chave, "quando": agora.isoformat()}
            ).execute()
            # Poda da própria chave: barata (índice em chave+quando) e mantém a
            # tabela no tamanho de (chaves ativas × máximo).
            with contextlib.suppress(Exception):
                corte_antigo = (agora - timedelta(seconds=IDADE_MAXIMA_SEG)).isoformat()
                client.table(TABELA).delete().eq("chave", chave).lt(
                    "quando", corte_antigo
                ).execute()
            return True
        except Exception:  # noqa: BLE001
            logger.warning(
                "Rate limit no Supabase indisponível (tabela %s ausente? rode a "
                "migration 20260902100000); usando a janela em memória desta "
                "instância.",
                TABELA,
                exc_info=True,
            )
    return _permitir_em_memoria(chave, maximo, janela_seg)
