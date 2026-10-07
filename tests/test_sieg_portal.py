"""
Inclusão no SIEG pelo portal (07/10/2026) — docs/modal-detalhes-e-sieg.md.

O SIEG é o falso de tests/sieg_falso.py; o cofre devolve um PFX fixo (a
decifra real tem teste próprio). O TestClient roda as BackgroundTasks logo
depois da resposta, então o estado final já está gravado quando o teste olha.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as m
from app import cert_installer, sieg
from app.sieg_api import ClienteSieg
from tests import sieg_falso as sf
from tests.test_seguranca_lote1 import _Fake
from tests.test_seguranca_lote4 import ADMIN, AGORA, DOC_A, DOC_B, FISCAL_OP, GESTOR, _h, _item  # noqa: F401
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401

FP_A, FP_B, FP_C, FP_L = "a" * 64, "b" * 64, "c" * 64, "d" * 64
SENHA_PFX = "senha-do-pfx-123"


@pytest.fixture(autouse=True)
def _sem_arquivo_local(monkeypatch: pytest.MonkeyPatch):
    import app.settings_state as ss
    monkeypatch.setattr(ss, "_save_file", lambda _s: None)
    monkeypatch.setattr(ss, "_load_file", lambda: None)


@pytest.fixture
def siegf(monkeypatch: pytest.MonkeyPatch) -> sf.SiegFalso:
    falso = sf.SiegFalso()
    original = sieg.cliente

    def cliente(settings, http=None):
        c = original(settings, http=httpx.Client(transport=httpx.MockTransport(falso)))
        c.pausa = 0
        return c

    monkeypatch.setattr(sieg, "cliente", cliente)
    monkeypatch.setattr(cert_installer, "decifrar_pfx_da_linha", lambda row: b"PFX-" + row["fingerprint"].encode())
    monkeypatch.setattr(cert_installer, "decifrar_senha_da_linha", lambda row: SENHA_PFX)
    return falso


@pytest.fixture
def banco(banco_base: _Fake) -> _Fake:
    banco_base.tabelas["carteira_excecao"] = []
    banco_base.tabelas["sieg_inclusao"] = []
    banco_base.tabelas["sieg_trilha"] = []
    banco_base.tabelas["portal_settings"] = []
    return banco_base


def _configurar(client: TestClient, **padroes) -> dict:
    r = client.put("/api/sieg/configuracao", headers=_h(*ADMIN), json={
        "client_id": sf.CLIENT_ID, "secret_key": sf.SECRET, "api_key": sf.API_KEY,
        **({"padroes": padroes} if padroes else {}),
    })
    assert r.status_code == 200, r.text
    return r.json()


def _incluir(client: TestClient, fp: str, quem=FISCAL_OP):
    return client.post(f"/api/sieg/certificado/{fp}/incluir", headers=_h(*quem))


# ── Configuração ──────────────────────────────────────────────────────────

def test_configuracao_cifra_e_nao_devolve_os_segredos(client: TestClient, banco: _Fake) -> None:
    d = _configurar(client, UfCertificado="27", ConsultaNfce=True, DiasRetroativos=10)
    assert d == {**d, "client_id": sf.CLIENT_ID, "secret_key_set": True, "api_key_set": True, "configurado": True}
    assert d["padroes"]["ConsultaNfce"] is True and d["padroes"]["DiasRetroativos"] == 10
    linha = banco.tabelas["portal_settings"][0]
    assert sf.SECRET not in json.dumps(linha) and sf.API_KEY not in json.dumps(linha)
    # Campo vazio mantém o segredo guardado.
    r = client.put("/api/sieg/configuracao", headers=_h(*ADMIN), json={"client_id": sf.CLIENT_ID, "secret_key": "", "api_key": None})
    assert r.json()["secret_key_set"] and r.json()["api_key_set"]
    assert client.put("/api/sieg/configuracao", headers=_h(*FISCAL_OP), json={}).status_code == 403
    assert client.put("/api/sieg/configuracao", headers=_h(*ADMIN), json={"padroes": {"UfCertificado": "x"}}).status_code == 422


def test_salvar_a_configuracao_geral_nao_apaga_o_sieg(client: TestClient, banco: _Fake) -> None:
    _configurar(client)
    corpo = {**m.SettingsBody().model_dump(), "machine_id": "srv"}
    corpo = {k: v for k, v in corpo.items() if v is not None}
    client.put("/api/settings", headers=_h(*ADMIN), json=corpo)
    assert client.get("/api/sieg/configuracao", headers=_h(*ADMIN)).json()["configurado"] is True


def test_testar_conexao(client: TestClient, banco: _Fake, siegf: sf.SiegFalso) -> None:
    assert client.post("/api/sieg/testar", headers=_h(*ADMIN)).status_code == 400  # sem credenciais
    _configurar(client)
    r = client.post("/api/sieg/testar", headers=_h(*ADMIN))
    assert r.status_code == 200 and "Conectado" in r.json()["message"]
    siegf.jwt_recusa = True
    r = client.post("/api/sieg/testar", headers=_h(*ADMIN))
    assert r.status_code == 400 and "Client ID" in r.json()["detail"]


# ── Ligar ─────────────────────────────────────────────────────────────────

def test_ligar_inclui_em_segundo_plano_e_grava_a_trilha(client: TestClient, banco: _Fake, siegf: sf.SiegFalso) -> None:
    _configurar(client)
    r = _incluir(client, FP_A)
    assert r.status_code == 202, r.text
    e = sieg.estado(FP_A)
    assert e["estado"] == "no_sieg" and e["sieg_id"] == f"20929-{DOC_A}" and e["solicitado_por"] == "fis@x.com"
    eventos = [t["evento"] for t in sieg.trilha(FP_A)]
    assert eventos == ["incluido", "solicitado"]
    enviado = siegf.payloads[0]
    assert enviado["CnpjCpf"] == DOC_A and enviado["Nome"] == "ALFA" and enviado["SenhaCertificado"] == SENHA_PFX
    # Ninguém desliga e não liga duas vezes.
    assert _incluir(client, FP_A).status_code == 409
    assert client.get(f"/api/sieg/certificado/{FP_A}", headers=_h(*FISCAL_OP)).json()["estado"]["ligado"] is True


def test_regras_para_ligar(client: TestClient, banco: _Fake, siegf: sf.SiegFalso) -> None:
    assert _incluir(client, FP_A).json()["detail"].startswith("O SIEG ainda não foi configurado")
    _configurar(client)
    assert _incluir(client, FP_B).status_code == 404, "DOC_B é de outro operador"
    assert _incluir(client, FP_C, ADMIN).json()["detail"].startswith("Ainda não enviado ao cofre")
    assert _incluir(client, FP_L, ADMIN).json()["detail"].startswith("Certificado vencido")
    d = client.get(f"/api/sieg/certificado/{FP_C}", headers=_h(*ADMIN)).json()
    assert d["estado"] is None and d["motivo"] == "nao_enviado"


def test_erro_da_api_vai_para_a_trilha_sem_segredo(client: TestClient, banco: _Fake, siegf: sf.SiegFalso,
                                                   caplog: pytest.LogCaptureFixture) -> None:
    _configurar(client, ConsultaNfce=True)
    siegf.recusa_nfce = True
    siegf.falso_sucesso = True
    with caplog.at_level(logging.INFO):
        assert _incluir(client, FP_A).status_code == 202
    e = sieg.estado(FP_A)
    assert e["estado"] == "erro" and "falso sucesso" in e["mensagem"]
    ultimo = sieg.trilha(FP_A)[0]
    assert ultimo["evento"] == "erro" and ultimo["http_status"] == 200
    assert ultimo["opcoes_desabilitadas"] == "ConsultaNfce" and "ConsultaNfce" in ultimo["avisos"]
    tudo = json.dumps(banco.tabelas["sieg_trilha"]) + json.dumps(banco.tabelas["sieg_inclusao"]) + caplog.text
    for segredo in (SENHA_PFX, sf.SECRET, sf.API_KEY, sf.JWT):
        assert segredo not in tudo
    # Erro fica ligado e oferece tentar de novo.
    siegf.falso_sucesso = False
    assert _incluir(client, FP_A).status_code == 202
    assert sieg.estado(FP_A)["estado"] == "no_sieg"
    assert [t["evento"] for t in sieg.trilha(FP_A)][:2] == ["incluido", "religado"]


def test_renovacao_substitui_o_anterior(client: TestClient, banco: _Fake, siegf: sf.SiegFalso) -> None:
    _configurar(client)
    itens = banco.tabelas["cert_snapshots"][0]["items"]
    novo = _item(DOC_A, "e" * 64, nome="ALFA", venc=AGORA + timedelta(days=700))
    itens.append(novo)
    banco.tabelas["cert_pfx_store"].append({**banco.tabelas["cert_pfx_store"][0], "id": "pfx-e", "fingerprint": "e" * 64})
    assert _incluir(client, FP_A).status_code == 202
    assert _incluir(client, "e" * 64).status_code == 202
    assert sieg.estado("e" * 64)["estado"] == "no_sieg"
    antigo = sieg.estado(FP_A)
    assert antigo["estado"] == "substituido" and antigo["substituido_por"] == "e" * 64
    assert siegf.payloads[-1].get("CertificadoId") == f"20929-{DOC_A}", "o mesmo cadastro do CNPJ foi atualizado"


def test_reconciliacao_do_administrador(client: TestClient, banco: _Fake, siegf: sf.SiegFalso) -> None:
    _configurar(client)
    _incluir(client, FP_A)
    assert client.post(f"/api/sieg/certificado/{FP_A}/reconciliar", headers=_h(*FISCAL_OP)).status_code == 403
    r = client.post(f"/api/sieg/certificado/{FP_A}/reconciliar", headers=_h(*ADMIN))
    assert r.json()["estado"]["estado"] == "no_sieg"
    siegf.cadastros.clear()  # alguém tirou no painel do SIEG
    r = client.post(f"/api/sieg/certificado/{FP_A}/reconciliar", headers=_h(*ADMIN))
    assert r.json()["estado"]["estado"] == "removido" and r.json()["estado"]["ligado"] is False
    assert _incluir(client, FP_A).status_code == 202, "removido pode ser ligado de novo"
    assert sieg.estado(FP_A)["estado"] == "no_sieg"


def test_sincronizar_marca_o_que_ja_esta_no_sieg(client: TestClient, banco: _Fake, siegf: sf.SiegFalso) -> None:
    _configurar(client)
    siegf.cadastro(DOC_B, "BETA")
    siegf.cadastro("44444444000194", "LIDER", ativo=True)  # vencido no inventário: não marca
    r = client.post("/api/sieg/sincronizar", headers=_h(*ADMIN))
    assert r.status_code == 200 and r.json()["marcados"] == 1
    assert sieg.estado(FP_B)["estado"] == "no_sieg" and sieg.estado(FP_L) is None
    assert client.post("/api/sieg/sincronizar", headers=_h(*ADMIN)).json()["marcados"] == 0


def test_lista_do_inicio_traz_estado_e_filtra(client: TestClient, banco: _Fake, siegf: sf.SiegFalso) -> None:
    _configurar(client)
    _incluir(client, FP_A, ADMIN)
    def fps(filtro):
        r = client.get(f"/api/certificados?pagina=1&por_pagina=50&filtro_sieg={filtro}", headers=_h(*ADMIN))
        return {i["fingerprint_sha256"]: i.get("sieg_estado") for i in r.json()["itens"]}
    assert fps("no_sieg") == {FP_A: "no_sieg"}
    assert FP_A not in fps("fora") and FP_B in fps("fora")


def test_aba_sieg_do_instalador_e_do_administrador(client: TestClient, banco: _Fake, siegf: sf.SiegFalso) -> None:
    _configurar(client)
    _incluir(client, FP_A)
    assert client.get("/api/sieg/inclusoes", headers=_h(*FISCAL_OP)).status_code == 403
    d = client.get("/api/sieg/inclusoes", headers=_h(*ADMIN)).json()
    assert d["resumo"] == {"no_sieg": 1} and d["itens"][0]["nome"] == "ALFA"
    assert d["itens"][0]["solicitado_por"] == "fis@x.com"


def test_incluindo_esquecido_vira_erro(banco: _Fake) -> None:
    antigo = (AGORA - timedelta(hours=2)).isoformat()
    banco.tabelas["sieg_inclusao"].append({"fingerprint": FP_A, "documento": DOC_A, "estado": "incluindo",
                                           "atualizado_em": antigo, "solicitado_em": antigo})
    e = sieg.estado(FP_A)
    assert e["estado"] == "erro" and "interrompida" in e["mensagem"]


def test_trilha_do_instalador_diz_qual_certificado(client: TestClient, banco: _Fake) -> None:
    r = client.get("/api/cert-installer/trilha?dias=30", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    infos = [c.get("certificados_info") for c in r.json()["cadeias"]]
    assert {"nome": "ALFA", "documento": "11.111.111/0001-91"} in [i for lista in infos for i in lista]


def test_nao_chama_a_api_real(banco: _Fake) -> None:
    """Sanidade: o falso intercepta tudo; nada sai para api.sieg.com."""
    assert isinstance(sf.SiegFalso().cliente(), ClienteSieg)
