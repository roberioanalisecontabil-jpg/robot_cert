"""
Rate limit por chave que sobrevive ao serverless (item 13 da Frente 2 — R5).

O limitador anterior (`_claim_rate_limit` em main.py) era um dicionário em
memória de processo — e na Vercel cada instância tem o seu: o teto de 10
tentativas/minuto valia por instância, não por IP. Com cold starts frequentes,
um atacante paciente falava com várias instâncias e o limite real era
"10 × quantas instâncias a plataforma quiser subir". Memória de instância em
serverless não é limite; é sugestão.

Aqui a janela vive numa tabela pequena do banco (`rate_limit_tentativas`),
compartilhada por todas as instâncias. Cada tentativa é uma linha; permitir é
contar as linhas da chave dentro da janela. A poda é oportunista, na própria
chave, a cada chamada — o volume por chave é limitado pelo próprio teto, então
a tabela não cresce além de (chaves ativas × máximo).

── Falha do banco NÃO abre o portão nem fecha o portal ───────────────────

Sem banco (dev, ou indisponibilidade), cai na janela em memória — que é
exatamente o comportamento que existia antes: por instância, imperfeito, e
melhor que negar serviço a todo mundo por causa do limitador. A queda é
logada; um limitador que degrada em silêncio é o defeito que este módulo veio
corrigir.

── Conta depois de inserir ───────────────────────────────────────────────

Até 14/10/2026 contava e só depois inseria, e pedidos simultâneos viam todos
o mesmo número abaixo do teto: a rajada passava inteira (auditoria run-2,
item 8 — o código do app autenticador, que não queima no erro, só tem este
teto por conta). Agora insere, conta incluindo a própria linha e, passando do
teto, apaga a própria linha e recusa — o padrão de `senha_reset.criar_codigo`.
Numa rajada, quem chega depois enxerga os outros; no pior caso todos se veem e
todos ficam de fora, o que erra para o lado seguro.
"""

from __future__ import annotations

import contextlib
import logging
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

TABELA = "rate_limit_tentativas"

# Poda: linhas desta chave mais velhas que isto saem a cada chamada. Muito
# maior que qualquer janela em uso, para nunca podar o que ainda conta.
IDADE_MAXIMA_SEG = 3600.0
# Uma em cada N tentativas também poda as chaves velhas de toda a tabela.
PODA_GERAL_A_CADA = 200

_memoria: dict[str, list[float]] = {}
_memoria_lock = threading.Lock()

# O último `permitir` conseguiu usar o banco? None = nunca tentou. Vai para
# /api/health/detalhado (achado #47): a degradação para memória de instância
# era silenciosa para tudo que não fosse o log — e o log a apagava se a
# mensagem contivesse "senha".
_estado_persistente: bool | None = None


def estado_persistente() -> bool | None:
    return _estado_persistente


def _banco():
    from app.settings_state import _banco as _sb

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

    Conta e registra no banco — o mapa vale para TODAS as instâncias. Sem
    banco, degrada para a janela em memória com aviso no log.
    """
    client = _banco()
    if client:
        agora = datetime.now(timezone.utc)
        corte_janela = (agora - timedelta(seconds=janela_seg)).isoformat()
        try:
            inserida = client.table(TABELA).insert(
                {"chave": chave, "quando": agora.isoformat()}
            ).execute()
            global _estado_persistente
            _estado_persistente = True
            r = (
                client.table(TABELA)
                .select("id")
                .eq("chave", chave)
                .gte("quando", corte_janela)
                .execute()
            )
            if len(r.data or []) > maximo:
                # Apagada, não mantida: recusa não conta, como antes, senão
                # uma rajada recusada manteria a chave travada pela janela toda.
                minha_id = ((inserida.data or [{}])[0]).get("id")
                apagar = client.table(TABELA).delete()
                if minha_id is not None:
                    apagar = apagar.eq("id", minha_id)
                else:
                    apagar = apagar.eq("chave", chave).eq("quando", agora.isoformat())
                with contextlib.suppress(Exception):
                    apagar.execute()
                return False
            # Poda da própria chave: barata (índice em chave+quando) e mantém a
            # tabela no tamanho de (chaves ativas × máximo).
            with contextlib.suppress(Exception):
                corte_antigo = (agora - timedelta(seconds=IDADE_MAXIMA_SEG)).isoformat()
                client.table(TABELA).delete().eq("chave", chave).lt(
                    "quando", corte_antigo
                ).execute()
                # E, de vez em quando, a tabela inteira: chave que aparece uma
                # vez só (um endereço por tentativa) nunca voltava para ser
                # podada e ficava para sempre (auditoria de 10/10/2026).
                if secrets.randbelow(PODA_GERAL_A_CADA) == 0:
                    client.table(TABELA).delete().lt("quando", corte_antigo).execute()
            return True
        except Exception:  # noqa: BLE001
            _estado_persistente = False
            logger.warning(
                "Rate limit no banco indisponível (tabela %s ausente? rode a "
                "migration 20260902100000); usando a janela em memória desta "
                "instância.",
                TABELA,
                exc_info=True,
            )
    return _permitir_em_memoria(chave, maximo, janela_seg)
