"""
Cache em memória (TTL) da agregação de histórico (Supabase / snapshot local).

- Chave: (Supabase ativo?, limite_snapshots).
- Invalidação ao gravar novo snapshot (`save_snapshot`).
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Dict, Tuple

from app import config

# Quando mudar a forma como os agregados são construídos, incrementar para ignorar caches antigos
# no mesmo processo (TTL sozinho poderia prolongar payloads obsoletos).
_CACHE_PAYLOAD_VERSION = 2

CacheKey = Tuple[int, bool, int]
_CacheEntry = Tuple[float, Dict[str, dict], int]

_lock = threading.Lock()
_store: Dict[CacheKey, _CacheEntry] = {}


def invalidate_all() -> None:
    """Limpa entradas (após ingest ou para testes)."""
    with _lock:
        _store.clear()


def _purge_expired_unlocked(now: float) -> None:
    stale = [k for k, (expiry, _, _) in _store.items() if expiry <= now]
    for k in stale:
        del _store[k]


def get_or_build(
    uses_supabase: bool,
    limite_snapshots: int,
    builder: Callable[[], Tuple[Dict[str, dict], int]],
) -> Tuple[Dict[str, dict], int]:
    ttl = int(config.HISTORICO_CACHE_TTL_SEC or 0)
    if ttl <= 0:
        return builder()

    key: CacheKey = (_CACHE_PAYLOAD_VERSION, uses_supabase, int(limite_snapshots))

    now0 = time.monotonic()
    with _lock:
        _purge_expired_unlocked(now0)
        hit = _store.get(key)
        if hit is not None and hit[0] > now0:
            return hit[1], hit[2]

    built_ag, built_n = builder()

    expiry = time.monotonic() + float(ttl)
    now1 = time.monotonic()
    with _lock:
        _purge_expired_unlocked(now1)
        cur = _store.get(key)
        if cur is not None and cur[0] > now1:
            return cur[1], cur[2]
        _store[key] = (expiry, built_ag, built_n)

    return built_ag, built_n
