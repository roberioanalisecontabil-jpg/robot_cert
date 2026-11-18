"""Rotas da coleta de uso e o mapa de contêineres na conferência (Frente C, Task 3)."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import remocao, uso
from tests.test_computadores_rotas import PC_FIS, PC_SOL, _bandeja, _chave, _entrar
from tests.test_computadores_rotas import banco  # noqa: F401
from tests.test_remocao_rotas import FA, FB, _corpo, _fixar, _sem_conta, ligado  # noqa: F401
from tests.test_seguranca_lote1 import _Fake
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401

SID = "S-1-5-21-1-2-3-1001"


def _evento(i: int = 1, **extra) -> dict:
    return {"record_id": i, "quando": "2026-11-15T12:30:00Z", "sid": SID, "usuario": "Fis",
            "conteiner": "cont-1", **extra}


def _lote(maquina: str = PC_SOL, **extra) -> dict:
    return {"machine_id": maquina, "chave": _chave(maquina), "auditoria": "ligada",
            "eventos": [_evento()], **extra}


def test_uso_exige_chave_da_maquina(client: TestClient, banco: _Fake) -> None:
    _fixar(banco, PC_SOL)
    r = client.post("/api/estacao/uso", json=_lote(chave="errada"))
    assert r.status_code == 403
    r = client.post("/api/estacao/uso", json=_lote(PC_FIS))  # sem chave fixada: também 403
    assert r.status_code == 403


def test_uso_grava_e_responde_contagem(client: TestClient, banco: _Fake, monkeypatch) -> None:
    _fixar(banco, PC_SOL)
    chamadas = []

    def _grava(mid, eventos, auditoria, agora):
        chamadas.append((mid, eventos, auditoria))
        return 1

    monkeypatch.setattr(uso, "registrar_usos", _grava)
    monkeypatch.setattr(uso, "limpar", lambda agora: None)
    r = client.post("/api/estacao/uso", json=_lote())
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "gravadas": 1}
    mid, eventos, auditoria = chamadas[0]
    assert auditoria == "ligada" and eventos[0].usuario == "fis" and eventos[0].record_id == 1
    assert isinstance(eventos[0].quando, datetime)


def test_uso_banco_fora_503(client: TestClient, banco: _Fake, monkeypatch) -> None:
    _fixar(banco, PC_SOL)

    def _fora(*_a):
        raise RuntimeError("banco fora")

    monkeypatch.setattr(uso, "registrar_usos", _fora)
    assert client.post("/api/estacao/uso", json=_lote()).status_code == 503


def test_lote_acima_de_2000_recusado(client: TestClient, banco: _Fake) -> None:
    _fixar(banco, PC_SOL)
    r = client.post("/api/estacao/uso", json=_lote(eventos=[_evento(i) for i in range(2001)]))
    assert r.status_code == 422


def _jan(**extra) -> dict:
    return {"quando": "2026-11-15T12:29:00Z", "programa": "chrome.exe", "titulo": "Portal", **extra}


def test_rota_aceita_lote_sem_janelas_e_recusa_4(client: TestClient, banco: _Fake, monkeypatch) -> None:
    _fixar(banco, PC_SOL)
    recebidos = []
    monkeypatch.setattr(uso, "registrar_usos", lambda mid, ev, aud, ag: recebidos.append(ev) or 1)
    monkeypatch.setattr(uso, "limpar", lambda agora: None)
    assert client.post("/api/estacao/uso", json=_lote()).status_code == 200
    assert recebidos[0][0].janelas == []
    r = client.post("/api/estacao/uso", json=_lote(eventos=[_evento(janelas=[_jan()] * 3)]))
    assert r.status_code == 200, r.text
    assert recebidos[1][0].janelas[0]["programa"] == "chrome.exe"
    assert client.post("/api/estacao/uso", json=_lote(eventos=[_evento(janelas=[_jan()] * 4)])).status_code == 422
    assert client.post("/api/estacao/uso",
                       json=_lote(eventos=[_evento(janelas=[_jan(titulo="x" * 301)])])).status_code == 422


def test_janela_perde_o_nul(client: TestClient, banco: _Fake, monkeypatch) -> None:
    # Postgres `text` recusa NUL: a rota tira antes de gravar.
    _fixar(banco, PC_SOL)
    recebidos = []
    monkeypatch.setattr(uso, "registrar_usos", lambda mid, ev, aud, ag: recebidos.append(ev) or 1)
    monkeypatch.setattr(uso, "limpar", lambda agora: None)
    r = client.post("/api/estacao/uso",
                    json=_lote(eventos=[_evento(janelas=[_jan(programa="a\u0000b.exe", titulo="t\u0000i")])]))
    assert r.status_code == 200, r.text
    j = recebidos[0][0].janelas[0]
    assert (j["programa"], j["titulo"]) == ("ab.exe", "ti")


def test_conferencia_grava_mapa_com_remocao_desligada(client: TestClient, banco: _Fake, monkeypatch) -> None:
    monkeypatch.setattr(remocao, "modo_sem_login", lambda: "desligado")
    chamadas = []
    monkeypatch.setattr(uso, "registrar_mapa", lambda *a: chamadas.append(a) or 0)
    # FB não está em `certificados`: o contêiner dele não entra no mapa.
    r = _sem_conta(client, PC_SOL, sid=SID, certificados=[FA],
                   conteineres={FA: "cont-a", FB: "cont-b"})
    assert r.status_code == 200, r.text
    mid, sid, usuario, uid, mapa, _agora = chamadas[0]
    assert (sid, usuario, uid, mapa) == (SID, "fis", None, {"cont-a": FA})


def test_mapa_falhando_nao_derruba_conferencia(client: TestClient, banco: _Fake, ligado: None,
                                               monkeypatch) -> None:
    def _fora(*_a):
        raise RuntimeError("mapa fora")

    monkeypatch.setattr(uso, "registrar_mapa", _fora)
    seg = _entrar(client, "fis@x.com", PC_FIS)["segredo"]
    r = client.post("/api/estacao/conferencia", headers=_bandeja(seg),
                    json=_corpo(sid=SID, conteineres={FA: "cont-a"}))
    assert r.status_code == 200, r.text
    assert "remover" in r.json() and "avisos" in r.json()


def test_conferencia_antiga_sem_sid_continua_valendo(client: TestClient, banco: _Fake, ligado: None,
                                                     monkeypatch) -> None:
    chamadas = []
    monkeypatch.setattr(uso, "registrar_mapa", lambda *a: chamadas.append(a) or 0)
    r = _sem_conta(client, PC_SOL)
    assert r.status_code == 200, r.text
    assert chamadas == []
