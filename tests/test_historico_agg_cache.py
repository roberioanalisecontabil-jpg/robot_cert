"""Unitário do TTL cache da agregação de histórico."""

import pytest

from app import config
from app.historico_agg_cache import get_or_build, invalidate_all


def test_ttl_zero_never_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "HISTORICO_CACHE_TTL_SEC", 0)
    invalidate_all()
    calls: list[int] = []

    def b() -> tuple[dict, int]:
        calls.append(1)
        return ({"k": {}}, 2)

    a1, n1 = get_or_build(False, 10, b)
    a2, n2 = get_or_build(False, 10, b)
    assert len(calls) == 2
    assert n1 == n2 == 2
    assert a1 is not a2


def test_ttl_reuso_por_limite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "HISTORICO_CACHE_TTL_SEC", 3600)
    invalidate_all()
    calls: list[int] = []

    def mk(supabase: bool, lim: int):

        def b() -> tuple[dict, int]:
            calls.append(len(calls))
            return ({f"{supabase}:{lim}": {}}, lim)

        return b

    get_or_build(False, 20, mk(False, 20))
    get_or_build(False, 20, mk(False, 20))
    get_or_build(False, 30, mk(False, 30))
    assert len(calls) == 2


def test_invalidate_all_forca_rebuild(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "HISTORICO_CACHE_TTL_SEC", 3600)
    invalidate_all()
    calls: list[int] = []

    def b() -> tuple[dict, int]:
        calls.append(1)
        return ({}, 0)

    get_or_build(True, 5, b)
    invalidate_all()
    get_or_build(True, 5, b)
    assert len(calls) == 2
