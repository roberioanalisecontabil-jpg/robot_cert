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


def _jan(minuto: int, programa: str = "chrome.exe", titulo: str = "Portal") -> dict:
    return {"quando": datetime(2026, 11, 15, 16, minuto, tzinfo=UTC), "programa": programa, "titulo": titulo}


def _ev_j(rid: int, janelas: list, minuto: int = 6) -> Evento:
    e = _ev(rid, minuto)
    e.janelas = janelas
    return e


def _janelas(banco: _Fake) -> list:
    return banco.tabelas["uso_janela"]


def test_janelas_gravadas_com_a_ordem(banco):
    uso.registrar_usos(M, [_ev_j(10, [_jan(5, "a.exe"), _jan(4, "b.exe")])], "ligada", AGORA)
    js = sorted(_janelas(banco), key=lambda j: j["ordem"])
    assert [(j["ordem"], j["programa"], j["record_id"]) for j in js] == [(0, "a.exe", 10), (1, "b.exe", 10)]
    assert all(j["uso_id"] == _usos(banco)[0]["id"] and j["machine_id"] == M for j in js)


def test_reenvio_nao_duplica_janelas(banco):
    lote = [_ev_j(10, [_jan(5), _jan(4)])]
    uso.registrar_usos(M, lote, "ligada", AGORA)
    uso.registrar_usos(M, lote, "ligada", AGORA)
    assert len(_janelas(banco)) == 2 and _usos(banco)[0]["quantidade"] == 1


def test_janela_leva_a_hora_do_evento(banco):
    uso.registrar_usos(M, [_ev_j(10, [_jan(5), _jan(4)], minuto=6)], "ligada", AGORA)
    assert {j["evento_em"] for j in _janelas(banco)} == {datetime(2026, 11, 15, 16, 6, tzinfo=UTC).isoformat()}


def test_mesmo_record_id_em_outra_linha_de_uso_e_gravado(banco):
    # Log de Segurança limpo: o record_id recomeça, mas a linha de uso (outra hora) é outra.
    uso.registrar_usos(M, [_ev_j(10, [_jan(5, "a.exe")], minuto=6)], "ligada", AGORA)
    outra = Evento(10, datetime(2026, 11, 16, 10, 6, tzinfo=UTC), "S-1", "ana", "C1", [_jan(5, "b.exe")])
    uso.registrar_usos(M, [outra], "ligada", AGORA)
    assert len(_usos(banco)) == 2
    assert sorted(j["programa"] for j in _janelas(banco)) == ["a.exe", "b.exe"]
    assert len({j["uso_id"] for j in _janelas(banco)}) == 2


def test_janela_de_evento_ja_contado_e_gravada(banco):
    uso.registrar_usos(M, [_ev(10)], "ligada", AGORA)
    assert "uso_janela" not in banco.tabelas or _janelas(banco) == []
    uso.registrar_usos(M, [_ev_j(10, [_jan(5)])], "ligada", AGORA)
    assert _usos(banco)[0]["quantidade"] == 1
    assert len(_janelas(banco)) == 1 and _janelas(banco)[0]["uso_id"] == _usos(banco)[0]["id"]


def test_coleta_grava_auditoria(banco):
    uso.registrar_usos(M, [_ev(10)], "desligada", AGORA)
    (coleta,) = banco.tabelas["uso_coleta"]
    assert coleta["auditoria"] == "desligada" and coleta["machine_id"] == M


def _ev_s(rid: int, segundo: float, conteiner: str, sid: str = "S-1") -> Evento:
    return Evento(rid, datetime(2026, 11, 15, 16, 6, tzinfo=UTC) + timedelta(seconds=segundo), sid, "ana", conteiner)


def test_listagem_de_certificados_nao_conta(banco):
    # O SPED (Java) abre a chave de todos os certificados para montar a lista.
    lista = [_ev_s(10 + i, i * 0.01, f"C{i}") for i in range(22)]
    assert uso.registrar_usos(M, lista, "ligada", AGORA) == 0
    assert banco.tabelas.get("uso_certificado", []) == []


def test_selecao_isolada_conta_mesmo_perto_de_listagem(banco):
    lista = [_ev_s(10 + i, i * 0.01, f"C{i}") for i in range(5)]
    escolhido = _ev_s(50, 30, "C2")
    uso.registrar_usos(M, lista + [escolhido], "ligada", AGORA)
    (linha,) = _usos(banco)
    assert (linha["conteiner"], linha["quantidade"]) == ("C2", 1)


def test_dois_certificados_juntos_ainda_contam(banco):
    uso.registrar_usos(M, [_ev_s(10, 0, "C1"), _ev_s(11, 0.5, "C2"), _ev_s(12, 0.6, "C1")], "ligada", AGORA)
    assert sorted(l["conteiner"] for l in _usos(banco)) == ["C1", "C2"]


def test_listagem_e_por_pessoa(banco):
    # Três pessoas na mesma máquina, cada uma com um certificado no mesmo segundo.
    evs = [_ev_s(10, 0, "C1", "S-1"), _ev_s(11, 0.1, "C2", "S-2"), _ev_s(12, 0.2, "C3", "S-3")]
    uso.registrar_usos(M, evs, "ligada", AGORA)
    assert len(_usos(banco)) == 3
