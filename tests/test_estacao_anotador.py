"""Anotador (SYSTEM na sessão da pessoa) e vigia (SYSTEM, sobe um anotador por sessão)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from estacao import anotador, janelas

RAIZ = Path(__file__).resolve().parent.parent
SID = "S-1-5-21-1-2-3-1001"
T = datetime(2026, 11, 18, 11, 17, 0, tzinfo=timezone.utc)
ACTIVE, DISCONNECTED = anotador.WTS_ACTIVE, anotador.WTS_DISCONNECTED


def test_grava_so_quando_muda():
    gravadas, estado = [], {}
    for lida in [("chrome", "A"), ("chrome", "A"), ("chrome", "B"), None, ("chrome", "B")]:
        anotador.passo(estado, T, lida, lambda q, p, t: gravadas.append((p, t)))
    assert gravadas == [("chrome", "A"), ("chrome", "B"), ("chrome", "B")]


def test_gravacao_que_falha_tenta_de_novo_no_proximo_passo():
    gravadas, estado, falhas = [], {}, [OSError("disco")]

    def gravar(q, p, t):
        if falhas:
            raise falhas.pop()
        gravadas.append((p, t))

    for _ in range(2):
        try:
            anotador.passo(estado, T, ("chrome", "A"), gravar)
        except OSError:
            pass
    assert gravadas == [("chrome", "A")]


def test_vigia_lanca_so_onde_falta():
    vivo, morto = SimpleNamespace(poll=lambda: None), SimpleNamespace(poll=lambda: 1)
    sessoes = [{"SessionId": 1, "State": ACTIVE}, {"SessionId": 2, "State": ACTIVE},
               {"SessionId": 3, "State": ACTIVE}, {"SessionId": 4, "State": DISCONNECTED}]
    assert anotador.sessoes_sem_anotador(sessoes, {1: vivo, 2: morto}) == [2, 3]


def test_laco_sobrevive_a_erro_e_para_quando_a_sessao_some(tmp_path):
    relogio = iter(T + timedelta(seconds=10 * i) for i in range(100))
    leituras = iter([RuntimeError("titulo ruim"), ("chrome", "gov.br"), ("chrome", "gov.br"), ("Acrobat", "Nota")])
    vivas = iter([True, True, False])  # conferida a cada 30 s: t=0, 30, 60

    def ler():
        x = next(leituras, ("Acrobat", "Nota"))
        if isinstance(x, Exception):
            raise x
        return x

    anotador.laco(str(tmp_path), SID, dormir=lambda s: None, ler=ler, relogio=lambda: next(relogio),
                  viva=lambda: next(vivas))
    linhas = janelas.ler(str(tmp_path), SID, T + timedelta(minutes=5))
    assert [(l["p"], l["j"]) for l in linhas] == [("chrome", "gov.br"), ("Acrobat", "Nota")]


def test_anotador_recusa_sid_invalido(monkeypatch):
    from estacao import tarefa

    monkeypatch.setattr(tarefa, "configurar_log", lambda nome: None)
    assert anotador.rodar_anotador("..\\..\\Windows") == 2


def test_main_despacha_vigia_e_anotador(monkeypatch):
    from estacao.__main__ import main

    chamadas = []
    monkeypatch.setattr(anotador, "rodar_vigia", lambda: chamadas.append("vigia") or 0)
    monkeypatch.setattr(anotador, "rodar_anotador", lambda sid: chamadas.append(("anotador", sid)) or 0)
    assert main(["--vigia"]) == 0
    assert main(["--anotador", "--sid", "S"]) == 0
    assert main(["--anotador"]) == 2
    assert chamadas == ["vigia", ("anotador", "S")]


def test_spec_inclui_win32security():
    spec = (RAIZ / "CertguardAnalise.spec").read_text(encoding="utf-8")
    for modulo in ("estacao.anotador", "win32security", "win32api", "win32event"):
        assert f'"{modulo}"' in spec, modulo
