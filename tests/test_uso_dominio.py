from datetime import datetime, timedelta, timezone

import pytest

import app.cert_installer as ci
import app.uso as uso
from app.uso import BRASILIA, Evento
from tests.test_seguranca_lote1 import _Fake

UTC = timezone.utc
AGORA = datetime(2026, 11, 15, 16, 30, tzinfo=UTC)
FP = "a" * 64
M = "aa:bb:cc:dd:ee:ff"


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake({"cert_pfx_store": [{"fingerprint": FP, "documento": "12345678000199"}]})
    monkeypatch.setattr(ci, "_banco", lambda: fake)
    return fake


def _ev(rid: int, minuto: int = 6, conteiner: str = "C1") -> Evento:
    return Evento(rid, datetime(2026, 11, 15, 16, minuto, tzinfo=UTC), "S-1", "ana", conteiner)


def _usos(banco: _Fake) -> list:
    return banco.tabelas["uso_certificado"]


def test_hora_de_brasilia():
    assert uso.hora_de(datetime(2026, 11, 15, 16, 6, 51, tzinfo=UTC)) == datetime(2026, 11, 15, 13, 0, tzinfo=BRASILIA)


def test_mesma_hora_soma_e_nao_duplica(banco):
    uso.registrar_usos(M, [_ev(10, 6), _ev(11, 9)], "ligada", AGORA)
    uso.registrar_usos(M, [_ev(12, 40)], "ligada", AGORA)
    (linha,) = _usos(banco)
    assert linha["quantidade"] == 3 and linha["ultimo_record"] == 12
    assert linha["primeiro_em"] < linha["ultimo_em"]


def test_reenvio_nao_soma(banco):
    uso.registrar_usos(M, [_ev(10), _ev(11)], "ligada", AGORA)
    uso.registrar_usos(M, [_ev(10), _ev(11)], "ligada", AGORA)
    assert _usos(banco)[0]["quantidade"] == 2


def test_uso_antes_do_mapa_resolve_depois(banco):
    uso.registrar_usos(M, [_ev(10)], "ligada", AGORA)
    assert _usos(banco)[0]["fingerprint"] is None
    n = uso.registrar_mapa(M, "S-1", "ana", "u-1", {"C1": FP}, AGORA)
    assert n == 1
    linha = _usos(banco)[0]
    assert (linha["fingerprint"], linha["documento"], linha["user_id"]) == (FP, "12345678000199", "u-1")


def test_uso_depois_do_mapa_ja_nasce_resolvido(banco):
    uso.registrar_mapa(M, "S-1", "ana", "u-1", {"C1": FP}, AGORA)
    uso.registrar_usos(M, [_ev(10)], "ligada", AGORA)
    assert _usos(banco)[0]["documento"] == "12345678000199"


def test_conteiner_fora_do_acervo_fica_pendente_e_some_em_30_dias(banco):
    uso.registrar_usos(M, [_ev(10)], "ligada", AGORA)
    assert uso.registrar_mapa(M, "S-1", "ana", "u-1", {"C1": "b" * 64}, AGORA) == 0
    assert _usos(banco)[0]["fingerprint"] is None
    uso.limpar(AGORA + timedelta(days=29))
    assert len(_usos(banco)) == 1
    uso.limpar(AGORA + timedelta(days=31))
    assert _usos(banco) == []


def test_guarda_de_5_anos(banco):
    uso.registrar_mapa(M, "S-1", "ana", "u-1", {"C1": FP}, AGORA)
    uso.registrar_usos(M, [_ev(10)], "ligada", AGORA)
    uso.limpar(AGORA + timedelta(days=5 * 365 - 2))
    assert len(_usos(banco)) == 1
    uso.limpar(AGORA + timedelta(days=5 * 365 + 2))
    assert _usos(banco) == []


def test_coleta_grava_auditoria(banco):
    uso.registrar_usos(M, [_ev(10)], "desligada", AGORA)
    (coleta,) = banco.tabelas["uso_coleta"]
    assert coleta["auditoria"] == "desligada" and coleta["machine_id"] == M
