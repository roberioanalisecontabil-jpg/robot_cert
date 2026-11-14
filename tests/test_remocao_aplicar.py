"""Aplicar o modo e gravar o estado da remoção por estação (Frente B)."""

from datetime import datetime, timedelta, timezone

import pytest

import app.cert_installer as ci
import app.remocao as rem
from app.remocao import Decisao
from tests.test_seguranca_lote1 import _Fake

AGORA = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
MID, USU = "AA:BB:CC:DD:EE:FF", "ana"
F1, F2 = "a" * 64, "b" * 64


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake({"remocao_estacao": []})
    monkeypatch.setattr(ci, "_banco", lambda: fake)
    return fake


@pytest.fixture
def trilha(monkeypatch: pytest.MonkeyPatch) -> list:
    eventos: list = []
    monkeypatch.setattr(ci, "log_event", lambda *a, **k: eventos.append((a, k)))
    return eventos


def _linhas(banco: _Fake) -> dict:
    return {r["fingerprint"]: r for r in banco.tabelas["remocao_estacao"]}


def _sem_login(fp: str = F1) -> Decisao:
    return Decisao(fp, "111", "sem_login", "perfil sem login na bandeja", None)


def _aplicar(decisoes, modo, agora=AGORA, user_id="u1"):
    return rem.aplicar(MID, USU, user_id, decisoes, modo, agora)


def test_desligado_nao_grava_nem_devolve(banco):
    assert _aplicar([Decisao(F1, "111", "carteira", "x", None)], "desligado") == {"remover": [], "avisos": []}
    assert banco.tabelas["remocao_estacao"] == []
    assert banco.gravados == []
    # Só zera o relógio do que estava pendente; o resto fica como está.
    _aplicar([Decisao(F1, "111", "carteira", "x", None), _sem_login(F2)], "ligado")
    banco.tabelas["remocao_estacao"].append({"machine_id": MID.lower(), "usuario_windows": USU,
                                             "fingerprint": "c" * 64, "estado": "removido"})
    banco.tabelas["remocao_estacao"].append({"machine_id": MID.lower(), "usuario_windows": "outro",
                                             "fingerprint": "d" * 64, "estado": "aviso",
                                             "aviso_desde": AGORA.isoformat()})
    assert _aplicar([Decisao("e" * 64, "333", "carteira", "x", None)], "desligado") == {"remover": [], "avisos": []}
    estados = {(r["usuario_windows"], r["fingerprint"][0]): (r["estado"], r.get("aviso_desde"))
               for r in banco.tabelas["remocao_estacao"]}
    assert estados == {("ana", "a"): ("removeria", None), ("ana", "b"): ("removeria", None),
                       ("ana", "c"): ("removido", None), ("outro", "d"): ("aviso", AGORA.isoformat())}


def test_desligado_zera_relogio_pendente(banco):
    _aplicar([_sem_login()], "ligado", AGORA - timedelta(days=5))
    assert _aplicar([_sem_login()], "ligado")["avisos"][0]["dias"] == 2
    _aplicar([_sem_login()], "desligado")
    assert _aplicar([_sem_login()], "ligado")["avisos"][0]["dias"] == 7


@pytest.mark.parametrize("fim", ["removido", "falhou"])
def test_sem_login_reinstalado_ganha_aviso_novo(banco, fim):
    _aplicar([_sem_login()], "ligado", AGORA - timedelta(days=10))
    assert _aplicar([_sem_login()], "ligado", AGORA - timedelta(days=2))["remover"]
    rem.registrar_resultado(MID, USU, None, None, [{"fingerprint": F1, "ok": fim == "removido", "erro": "e"}])
    assert _linhas(banco)[F1]["estado"] == fim
    saida = _aplicar([_sem_login()], "ligado")
    assert saida["remover"] == [] and saida["avisos"][0]["dias"] == 7
    assert _linhas(banco)[F1]["estado"] == "aviso"


def test_relatorio_grava_removeria_e_nao_manda_remover(banco):
    saida = _aplicar([Decisao(F1, "111", "carteira", "retirado", None), _sem_login(F2)], "relatorio")
    assert saida == {"remover": [], "avisos": []}
    linhas = _linhas(banco)
    assert {fp: (r["estado"], r["aviso_desde"]) for fp, r in linhas.items()} == {
        F1: ("removeria", None), F2: ("removeria", None)}
    assert linhas[F1]["machine_id"] == MID.lower() and linhas[F1]["usuario_windows"] == USU


def test_ligado_remove_ja_o_que_venceu(banco):
    futuro = AGORA + timedelta(days=2, hours=1)
    saida = _aplicar([Decisao(F1.upper(), "111", "carteira", "retirado", None),
                      Decisao(F2, "222", "vinculo", "computador recusado", futuro)], "ligado")
    assert saida["remover"] == [{"fingerprint": F1, "documento": "111", "motivo": "retirado"}]
    # 2 dias e 1 hora arredondam para cima.
    assert saida["avisos"] == [{"fingerprint": F2, "documento": "222", "motivo": "computador recusado", "dias": 3}]
    assert {fp: r["estado"] for fp, r in _linhas(banco).items()} == {F1: "remover", F2: "aviso"}


def test_sem_login_relogio_comeca_ao_ligar(banco):
    # Semanas de relatório antes: nenhuma conta como aviso.
    _aplicar([_sem_login()], "relatorio", AGORA - timedelta(days=30))
    saida = _aplicar([_sem_login()], "ligado")
    assert saida["remover"] == []
    assert saida["avisos"] == [{"fingerprint": F1, "documento": "111",
                                "motivo": "perfil sem login na bandeja", "dias": 7}]
    assert rem.comp._quando(_linhas(banco)[F1]["aviso_desde"]) == AGORA


def test_sem_login_remove_no_oitavo_dia(banco):
    _aplicar([_sem_login()], "ligado")
    assert _aplicar([_sem_login()], "ligado", AGORA + timedelta(days=6, hours=23))["avisos"][0]["dias"] == 1
    saida = _aplicar([_sem_login()], "ligado", AGORA + timedelta(days=7))
    assert saida["avisos"] == []
    assert [r["fingerprint"] for r in saida["remover"]] == [F1]
    # O relógio não recomeça a cada chamada.
    assert rem.comp._quando(_linhas(banco)[F1]["aviso_desde"]) == AGORA
    # Bandeja desligada: continua na fila nas chamadas seguintes.
    assert [r["fingerprint"] for r in _aplicar([_sem_login()], "ligado", AGORA + timedelta(days=9))["remover"]] == [F1]
    assert _linhas(banco)[F1]["estado"] == "remover"


def test_regra_trocada_reinicia_o_relogio(banco):
    _aplicar([Decisao(F1, "111", "carteira", "x", None)], "ligado", AGORA - timedelta(days=20))
    banco.tabelas["remocao_estacao"][0]["estado"] = "aviso"  # p.ex. sem a bandeja ter removido
    saida = _aplicar([_sem_login()], "ligado")
    assert saida["avisos"][0]["dias"] == 7


def test_naive_conta_como_utc(banco):
    _aplicar([_sem_login()], "ligado", AGORA.replace(tzinfo=None))
    assert rem.comp._quando(_linhas(banco)[F1]["aviso_desde"]) == AGORA


def test_situacao_resolvida_apaga_aviso(banco):
    _aplicar([_sem_login(F1), _sem_login(F2)], "ligado")
    banco.tabelas["remocao_estacao"].append({"machine_id": MID.lower(), "usuario_windows": USU,
                                             "fingerprint": "c" * 64, "estado": "removido"})
    banco.tabelas["remocao_estacao"].append({"machine_id": MID.lower(), "usuario_windows": "outro",
                                             "fingerprint": "d" * 64, "estado": "aviso"})
    _aplicar([_sem_login(F2)], "ligado")
    assert sorted((r["usuario_windows"], r["fingerprint"][0]) for r in banco.tabelas["remocao_estacao"]) == [
        ("ana", "b"), ("ana", "c"), ("outro", "d")]
    # Nada mais a decidir: o aviso que sobrou também some.
    _aplicar([], "relatorio")
    assert sorted(r["fingerprint"][0] for r in banco.tabelas["remocao_estacao"]) == ["c", "d"]


def test_removido_volta_se_reinstalado(banco):
    _aplicar([Decisao(F1, "111", "carteira", "x", None)], "ligado")
    rem.registrar_resultado(MID, USU, None, None, [{"fingerprint": F1, "ok": True, "erro": ""}])
    assert _linhas(banco)[F1]["estado"] == "removido"
    assert _aplicar([Decisao(F1, "111", "carteira", "x", None)], "ligado")["remover"][0]["fingerprint"] == F1
    assert _linhas(banco)[F1]["estado"] == "remover"


def test_resultado_so_vale_para_o_que_foi_mandado(banco, trilha):
    _aplicar([Decisao(F1, "111", "carteira", "x", None)], "ligado")
    banco.tabelas["remocao_estacao"].append({"machine_id": MID.lower(), "usuario_windows": USU,
                                             "fingerprint": F2, "estado": "aviso", "motivo": "m"})
    rem.registrar_resultado(MID, USU, "u1", "a@x", [
        {"fingerprint": F1.upper(), "ok": False, "erro": "acesso negado"},
        {"fingerprint": F2, "ok": True, "erro": ""},
        {"fingerprint": "e" * 64, "ok": True, "erro": ""},
    ])
    linhas = _linhas(banco)
    assert (linhas[F1]["estado"], linhas[F1]["detalhe"]) == ("falhou", "acesso negado")
    assert linhas[F2]["estado"] == "aviso"
    assert "e" * 64 not in linhas
    assert trilha == []


def test_removido_vai_a_trilha_com_motivo(banco, trilha):
    _aplicar([Decisao(F1, "111", "carteira", "retirado por g@x", None)], "ligado")
    rem.registrar_resultado(MID, USU, "u1", "a@x", [{"fingerprint": F1, "ok": True, "erro": ""}])
    assert _linhas(banco)[F1]["estado"] == "removido"
    assert trilha == [(("REMOVIDO", "u1", "a@x"), {"fingerprint": F1, "target_machine": MID.lower(),
                                                    "status": "OK", "detail": "retirado por g@x"})]


def test_sem_usuario_nao_vai_a_trilha(banco, trilha):
    _aplicar([_sem_login()], "ligado", AGORA - timedelta(days=8), user_id=None)
    _aplicar([_sem_login()], "ligado", user_id=None)
    rem.registrar_resultado(MID, USU, None, None, [{"fingerprint": F1, "ok": True, "erro": ""}])
    assert _linhas(banco)[F1]["estado"] == "removido"
    assert trilha == []


def test_falha_de_escrita_propaga(banco):
    banco.quebrado["remocao_estacao"] = True
    with pytest.raises(Exception):
        _aplicar([Decisao(F1, "111", "carteira", "x", None)], "ligado")
