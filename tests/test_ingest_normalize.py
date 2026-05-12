"""Normalizacao de status no ingest (/api/ingest)."""

from datetime import datetime, timezone

from app.main import _normalize_ingest_items_status


def test_ingest_normaliza_ok_para_expirado_quando_not_after_passou() -> None:
    agora = datetime(2026, 6, 1, tzinfo=timezone.utc)
    items = [
        {
            "file_name": "x.pfx",
            "status": "ok",
            "not_after": "2020-01-01T00:00:00+00:00",
        }
    ]
    out = _normalize_ingest_items_status(items, agora)
    assert out[0]["status"] == "expirado"


def test_ingest_mantem_ok_quando_not_after_no_futuro() -> None:
    agora = datetime(2026, 6, 1, tzinfo=timezone.utc)
    items = [
        {
            "file_name": "x.pfx",
            "status": "ok",
            "not_after": "2030-01-01T00:00:00+00:00",
        }
    ]
    out = _normalize_ingest_items_status(items, agora)
    assert out[0]["status"] == "ok"


def test_ingest_nao_altera_erro() -> None:
    agora = datetime(2026, 6, 1, tzinfo=timezone.utc)
    items = [
        {
            "file_name": "x.pfx",
            "status": "erro",
            "not_after": "2020-01-01T00:00:00+00:00",
        }
    ]
    out = _normalize_ingest_items_status(items, agora)
    assert out[0]["status"] == "erro"


def test_ingest_mantem_expirado() -> None:
    agora = datetime(2026, 6, 1, tzinfo=timezone.utc)
    items = [
        {
            "file_name": "x.pfx",
            "status": "expirado",
            "not_after": "2020-01-01T00:00:00+00:00",
        }
    ]
    out = _normalize_ingest_items_status(items, agora)
    assert out[0]["status"] == "expirado"
