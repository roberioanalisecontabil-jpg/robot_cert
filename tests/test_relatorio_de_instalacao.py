"""
Relatório da instalação (`/report` e `/report-avulso`), auditoria de 10/10/2026:
o token resgatado servia para gravar quantas linhas se quisesse, de quaisquer
certificados e a qualquer tempo, em nome de quem pediu. A trilha do Instalador
e o /acompanhar mostravam essas linhas como verdade.
"""

import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.rotas import instalador as ins
from tests.test_recuperacao_de_senha import _Fake

TOKEN = "token-resgatado"


def _banco(monkeypatch: pytest.MonkeyPatch, consumido: datetime) -> _Fake:
    fake = _Fake({
        "install_token": [{
            "id": "t1", "token_hash": hashlib.sha256(TOKEN.encode()).hexdigest(), "user_id": "u-ana",
            "user_email": "ana@x.com", "target_machine": "estacao-a",
            "certificate_ids": ["c1", "c2"], "consumed_at": consumido.isoformat(),
        }],
        "install_log": [],
    })
    monkeypatch.setattr("app.settings_state._banco", lambda: fake)
    return fake


def _relatar(*resultados):
    corpo = ins.ReportRequest(token=TOKEN, results=[
        ins.InstallResultItem(certificateId=c, status=s) for c, s in resultados])
    return ins._registrar_relatorio(corpo, SimpleNamespace(client=None))


def test_so_os_certificados_do_token_e_uma_vez(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _banco(monkeypatch, datetime.now(timezone.utc))
    assert _relatar(("c1", "OK"), ("c-alheio", "OK"))["processed"] == 1
    assert _relatar(("c1", "FALHA"), ("c2", "OK"))["processed"] == 1, "c1 já relatado"
    log = fake.tabelas["install_log"]
    assert sorted((x["certificate_id"], x["event"]) for x in log) == [("c1", "CONCLUIDO"), ("c2", "CONCLUIDO")]


def test_relatorio_tem_prazo(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _banco(monkeypatch, datetime.now(timezone.utc) - timedelta(days=2))
    with pytest.raises(HTTPException) as e:
        _relatar(("c1", "OK"))
    assert e.value.status_code == 403
    assert not fake.tabelas["install_log"]
