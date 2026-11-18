"""Registro local das janelas em primeiro plano (anotador SYSTEM -> coletor)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from estacao import janelas

SID = "S-1-5-21-1-2-3-1001"
T = datetime(2026, 11, 18, 11, 17, 0, tzinfo=timezone.utc)


def test_vigente_e_duas_anteriores_dentro_de_30s(tmp_path):
    for s, p, j in [(0, "outlook", "Caixa"), (10, "chrome", "eCAC - Centro Virtual de Atendimento"),
                    (40, "chrome", "gov.br - Acesse sua conta"), (50, "Acrobat", "Relatório")]:
        janelas.anotar(str(tmp_path), SID, T + timedelta(seconds=s), p, j)
    ev = T + timedelta(seconds=44)
    r = janelas.janelas_do_evento(janelas.ler(str(tmp_path), SID, ev), ev)
    assert [x["titulo"] for x in r] == ["gov.br - Acesse sua conta", "eCAC - Centro Virtual de Atendimento"]
    assert r[0]["programa"] == "chrome" and r[0]["quando"] == "2026-11-18T11:17:40+00:00"


def test_anterior_conta_pelo_fim_e_nao_pelo_inicio(tmp_path):
    # A comecou 100 s antes mas acabou 20 s antes (entra); B acabou 100 s antes (sai)
    for s, j in [(-300, "B"), (-100, "A"), (-20, "Vigente")]:
        janelas.anotar(str(tmp_path), SID, T + timedelta(seconds=s), "p", j)
    r = janelas.janelas_do_evento(janelas.ler(str(tmp_path), SID, T), T)
    assert [x["titulo"] for x in r] == ["Vigente", "A"]
    # fronteira: acabou 31 s antes sai, 30 s antes entra
    linhas = [{"t": (T + timedelta(seconds=s)).isoformat(), "p": "p", "j": j}
              for s, j in [(-200, "X"), (-31, "Y"), (-30, "Z")]]
    assert [x["titulo"] for x in janelas.janelas_do_evento(linhas, T)] == ["Z", "Y"]


def test_linha_no_mesmo_segundo_do_evento_e_vigente(tmp_path):
    janelas.anotar(str(tmp_path), SID, T, "chrome", "Portal")
    r = janelas.janelas_do_evento(janelas.ler(str(tmp_path), SID, T), T)
    assert [x["titulo"] for x in r] == ["Portal"]


def test_sem_linha_antes_do_evento_devolve_vazio(tmp_path):
    janelas.anotar(str(tmp_path), SID, T + timedelta(seconds=5), "chrome", "Depois")
    assert janelas.janelas_do_evento(janelas.ler(str(tmp_path), SID, T), T) == []
    assert janelas.ler(str(tmp_path), "S-outro", T) == []


def test_titulo_hostil_fica_numa_linha_e_cortado(tmp_path):
    janelas.anotar(str(tmp_path), SID, T, "chrome", "a\nb\"<script>😀" + "x" * 10_000)
    [l] = janelas.ler(str(tmp_path), SID, T)
    assert len(l["j"]) == 300 and l["j"].startswith("a\nb\"<script>😀")
    with open(janelas.arquivo(str(tmp_path), SID, T), encoding="utf-8") as f:
        assert len(f.read().splitlines()) == 1


def test_titulo_com_surrogate_solto_nao_levanta(tmp_path):
    janelas.anotar(str(tmp_path), SID, T, "chrome", "abc\ud800def")
    [l] = janelas.ler(str(tmp_path), SID, T)
    assert l["j"] == "abc\ud800def"


def test_linha_corrompida_e_ignorada(tmp_path):
    janelas.anotar(str(tmp_path), SID, T, "chrome", "Inteira")
    with open(janelas.arquivo(str(tmp_path), SID, T), "a", encoding="utf-8") as f:
        f.write('{"t": "2026-11-18T11:17:')
    assert [l["j"] for l in janelas.ler(str(tmp_path), SID, T)] == ["Inteira"]


def test_poda_apaga_so_dias_inteiros_fora_das_48h(tmp_path):
    agora = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)
    for dias in (0, 1, 2, 3):
        janelas.anotar(str(tmp_path), SID, agora - timedelta(days=dias), "p", "j")
    # corte = 16/11 12:00: o dia 16 ainda tem linhas dentro das 48h, o 15 nao
    assert janelas.podar(str(tmp_path), agora) == 1
    assert not os.path.exists(janelas.arquivo(str(tmp_path), SID, agora - timedelta(days=3)))
    assert os.path.exists(janelas.arquivo(str(tmp_path), SID, agora - timedelta(days=2)))


def test_evento_perto_da_meia_noite_le_o_dia_anterior(tmp_path):
    janelas.anotar(str(tmp_path), SID, datetime(2026, 11, 18, 23, 59, 50, tzinfo=timezone.utc), "chrome", "Antes")
    ev = datetime(2026, 11, 19, 0, 0, 5, tzinfo=timezone.utc)
    r = janelas.janelas_do_evento(janelas.ler(str(tmp_path), SID, ev), ev)
    assert [x["titulo"] for x in r] == ["Antes"]


def test_fuso_local_e_normalizado_para_utc(tmp_path):
    br = timezone(timedelta(hours=-3))
    janelas.anotar(str(tmp_path), SID, datetime(2026, 11, 18, 22, 0, 0, tzinfo=br), "p", "j")
    assert janelas.arquivo(str(tmp_path), SID, T).endswith("20261118.jsonl")
    assert os.path.exists(janelas.arquivo(str(tmp_path), SID, datetime(2026, 11, 19, 1, 0, tzinfo=timezone.utc)))
