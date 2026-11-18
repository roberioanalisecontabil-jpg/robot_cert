"""Coletor do uso dos certificados na tarefa SYSTEM (Frente C, bandeja 1.4.0)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from estacao import atualizador, chave_maquina, tarefa, uso

CSV_PT = (
    '"Nome do Computador","Destino da Política","Subcategoria","GUID de Subcategoria",'
    '"Configuração de Inclusão","Configuração de Exclusão"\n'
    'PC01,Sistema,Integridade do Sistema,{0CCE9212-69AE-11D9-BED3-505054503030},Êxito e Falha,\n'
)


def _r(stdout: str = "", code: int = 0) -> SimpleNamespace:
    return SimpleNamespace(stdout=stdout, stderr="", returncode=code)


class _Executor:
    """PowerShell de mentira: guarda os comandos e responde por trecho do comando."""

    def __init__(self, maior: int = 0, eventos: list | None = None, csv: str = CSV_PT) -> None:
        self.maior, self.eventos, self.csv = maior, eventos or [], csv
        self.comandos: list[str] = []

    def __call__(self, script: str) -> SimpleNamespace:
        self.comandos.append(script)
        if "auditpol /get" in script:
            return _r(self.csv)
        if "auditpol /set" in script:
            return _r()
        if "-MaxEvents 1" in script:
            return _r(str(self.maior))
        return _r(json.dumps(self.eventos) if self.eventos else "")


class _Http:
    def __init__(self, status: int = 200) -> None:
        self.status, self.posts = status, []

    def post(self, url: str, json: dict | None = None, **_k) -> SimpleNamespace:
        self.posts.append((url, json))

        def _levantar() -> None:
            if self.status >= 400:
                raise RuntimeError(f"HTTP {self.status}")

        return SimpleNamespace(status_code=self.status, raise_for_status=_levantar)


def _eventos(n: int, inicio: int = 1) -> list[dict]:
    return [{"record_id": inicio + i, "quando": "2026-11-15T10:00:00Z", "sid": "S-1-5-21-1",
             "usuario": "ana", "conteiner": f"c{i}"} for i in range(n)]


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(tarefa, "pastas", lambda: atualizador.Pastas(str(tmp_path)))
    monkeypatch.setattr(chave_maquina, "ler", lambda: "k" * 43)
    from estacao import bandeja

    monkeypatch.setattr(bandeja, "machine_id", lambda: "aa:bb")
    return tmp_path


def _marcador(pasta) -> int:
    arquivo = pasta / "uso-marcador.json"
    return json.loads(arquivo.read_text(encoding="utf-8"))["record_id"] if arquivo.exists() else 0


def test_liga_auditoria_pelo_guid() -> None:
    ex = _Executor()
    uso.ligar_auditoria(ex)
    assert "{0CCE9212-69AE-11D9-BED3-505054503030}" in ex.comandos[0]
    assert "/success:enable /failure:enable" in ex.comandos[0]
    assert all("0CCE9214" not in c and "System Integrity" not in c for c in ex.comandos)


def test_auditoria_lida_por_posicao_em_portugues() -> None:
    assert uso.ligar_auditoria(_Executor(csv=CSV_PT)) == "ligada"


def test_auditoria_sem_auditoria_e_erro() -> None:
    sem = CSV_PT.replace("Êxito e Falha", "Sem Auditoria")
    assert uso.ligar_auditoria(_Executor(csv=sem)) == "desligada"
    assert uso.ligar_auditoria(_Executor(csv="")) == "desconhecida"


def test_so_avanca_marcador_depois_do_200(ambiente) -> None:
    ex = _Executor(maior=50, eventos=_eventos(3))
    with pytest.raises(RuntimeError):
        uso.coletar(_Http(503), ex)
    assert _marcador(ambiente) == 0
    assert uso.coletar(_Http(200), ex) == 3
    assert _marcador(ambiente) == 3


def test_sem_eventos_manda_um_lote_vazio_com_a_auditoria(ambiente) -> None:
    http = _Http()
    assert uso.coletar(http, _Executor(maior=5, csv=CSV_PT.replace("Êxito e Falha", "Sem Auditoria"))) == 0
    assert len(http.posts) == 1
    assert http.posts[0][1]["eventos"] == [] and http.posts[0][1]["auditoria"] == "desligada"
    assert _marcador(ambiente) == 0


def test_evento_invalido_sai_do_lote_mas_o_marcador_passa(ambiente) -> None:
    eventos = _eventos(3)
    eventos[1]["conteiner"] = None
    eventos[2]["usuario"] = None
    http = _Http()
    assert uso.coletar(http, _Executor(maior=50, eventos=eventos)) == 2
    enviados = http.posts[0][1]["eventos"]
    assert [e["record_id"] for e in enviados] == [1, 3] and enviados[1]["usuario"] == ""
    assert _marcador(ambiente) == 3


def test_lotes_de_2000(ambiente) -> None:
    http = _Http()
    assert uso.coletar(http, _Executor(maior=9999, eventos=_eventos(4500))) == 4500
    assert [len(c[1]["eventos"]) for c in http.posts] == [2000, 2000, 500]
    assert http.posts[0][1]["auditoria"] == "ligada" and http.posts[0][1]["machine_id"] == "aa:bb"
    assert _marcador(ambiente) == 4500


def test_log_limpo_volta_a_7_dias(ambiente) -> None:
    (ambiente / "uso-marcador.json").write_text('{"record_id": 9000}', encoding="utf-8")
    ex = _Executor(maior=120)
    uso.coletar(_Http(), ex)
    leitura = ex.comandos[-1]
    assert "timediff" in leitura and "EventRecordID>" not in leitura


def test_marcador_normal_filtra_por_record(ambiente) -> None:
    (ambiente / "uso-marcador.json").write_text('{"record_id": 100}', encoding="utf-8")
    ex = _Executor(maior=150)
    uso.coletar(_Http(), ex)
    assert "EventRecordID>100" in ex.comandos[-1]


def test_sem_chave_nao_envia(ambiente, monkeypatch) -> None:
    monkeypatch.setattr(chave_maquina, "ler", lambda: None)
    http = _Http()
    assert uso.coletar(http, _Executor(eventos=_eventos(2))) == 0
    assert http.posts == [] and _marcador(ambiente) == 0


def _anotar(ambiente, programa="chrome", titulo="eCAC", segundos_antes=5, sid="S-1-5-21-1"):
    from datetime import datetime, timedelta, timezone

    from estacao import janelas

    evento = datetime(2026, 11, 15, 10, 0, 0, tzinfo=timezone.utc)
    janelas.anotar(str(ambiente), sid, evento - timedelta(seconds=segundos_antes), programa, titulo)


def test_evento_leva_as_janelas_do_sid(ambiente) -> None:
    _anotar(ambiente)
    _anotar(ambiente, "outro", "nao e dele", sid="S-1-5-21-2")
    http = _Http()
    uso.coletar(http, _Executor(maior=50, eventos=_eventos(1)))
    lote = http.posts[0][1]["eventos"]
    assert lote[0]["janelas"] == [{"quando": "2026-11-15T09:59:55+00:00", "programa": "chrome", "titulo": "eCAC"}]


def test_sem_registro_vai_lista_vazia_e_nao_quebra(ambiente) -> None:
    http = _Http()
    assert uso.coletar(http, _Executor(maior=50, eventos=_eventos(2))) == 2
    assert [e["janelas"] for e in http.posts[0][1]["eventos"]] == [[], []]
    assert _marcador(ambiente) == 2


def test_erro_lendo_janelas_nao_impede_a_coleta(ambiente, monkeypatch) -> None:
    from estacao import janelas

    def quebrar(*_a):
        raise OSError("disco")

    monkeypatch.setattr(janelas, "ler", quebrar)
    http = _Http()
    assert uso.coletar(http, _Executor(maior=50, eventos=_eventos(1))) == 1
    assert http.posts[0][1]["eventos"][0]["janelas"] == []
    assert _marcador(ambiente) == 1


def test_surrogate_solto_no_titulo_vira_substituto(ambiente) -> None:
    _anotar(ambiente, "chr\ud800ome", "eC\ud800AC")
    http = _Http()
    uso.coletar(http, _Executor(maior=50, eventos=_eventos(1)))
    j = http.posts[0][1]["eventos"][0]["janelas"][0]
    assert j["programa"] == "chr�ome" and j["titulo"] == "eC�AC"
    json.dumps(j, ensure_ascii=False).encode("utf-8")  # o portal recebe UTF-8 valido


# ── rodar_tarefa ─────────────────────────────────────────────────────────


@pytest.fixture
def rodada(tmp_path, monkeypatch):
    monkeypatch.setattr(tarefa, "configurar_log", lambda nome: None)
    monkeypatch.setattr(tarefa, "_unica", lambda: True)
    monkeypatch.setattr(tarefa, "pastas", lambda: atualizador.Pastas(str(tmp_path)))
    monkeypatch.setattr(tarefa, "e_estacao", lambda: True)
    ordem: list[str] = []
    return ordem


def test_falha_na_coleta_nao_impede_atualizacao(rodada, monkeypatch) -> None:
    def coletar(http):
        rodada.append("coletar")
        raise RuntimeError("log ilegível")

    monkeypatch.setattr(uso, "coletar", coletar)
    monkeypatch.setattr(tarefa, "buscar_pacote", lambda http: rodada.append("buscar"))
    assert tarefa.rodar_tarefa() == 0
    assert rodada == ["coletar", "buscar"]


def test_atualizacao_fora_nao_impede_coleta(rodada, monkeypatch) -> None:
    def fora(http):
        rodada.append("buscar")
        raise ConnectionError("fora do ar")

    monkeypatch.setattr(uso, "coletar", lambda http: rodada.append("coletar") or 0)
    monkeypatch.setattr(tarefa, "buscar_pacote", fora)
    assert tarefa.rodar_tarefa() == 1
    assert rodada == ["coletar", "buscar"]


def test_nao_estacao_nao_coleta(rodada, monkeypatch) -> None:
    monkeypatch.setattr(tarefa, "e_estacao", lambda: False)
    monkeypatch.setattr(uso, "coletar", lambda http: rodada.append("coletar") or 0)
    monkeypatch.setattr(tarefa, "buscar_pacote", lambda http: None)
    tarefa.rodar_tarefa()
    assert rodada == []
