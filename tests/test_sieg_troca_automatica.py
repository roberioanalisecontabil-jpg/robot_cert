"""SIEG: o portal confere QUAL certificado está lá e troca pelo mais novo (22/11/2026).

Em produção, 12 certificados apareciam "No SIEG" com o SIEG ainda no antigo:
a sincronização e a conferência do administrador olhavam só se o CNPJ estava
ativo, nunca a validade (DataExpira da listagem). E a troca na renovação só
acontecia se alguém ligasse o interruptor do certificado novo.
"""

from __future__ import annotations

import base64
from datetime import timedelta

from fastapi.testclient import TestClient

from app import sieg
from tests import sieg_falso as sf
from tests.test_seguranca_lote1 import _Fake
from tests.test_seguranca_lote4 import ADMIN, AGORA, DOC_A, DOC_C, _h, _item
from tests.test_sieg_portal import FP_A, FP_C, _configurar, _incluir, banco, siegf  # noqa: F401
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401
from tests.test_sieg_portal import _sem_arquivo_local  # noqa: F401

FP_E = "e" * 64
VELHO = (AGORA - timedelta(days=5)).isoformat()


def _pfx(fp: str) -> str:
    # O falso do cofre devolve b"PFX-" + fingerprint (tests/test_sieg_portal.py).
    return base64.b64encode(b"PFX-" + fp.encode()).decode()


def _validade(banco: _Fake, fp: str) -> str:
    return next(i for i in banco.tabelas["cert_snapshots"][0]["items"] if i["fingerprint_sha256"] == fp)["not_after"]


def _ensinar(siegf: sf.SiegFalso, banco: _Fake, *fps: str) -> None:
    for fp in fps:
        siegf.validades[_pfx(fp)] = _validade(banco, fp)


def _ciclo(banco: _Fake) -> dict:
    from app.settings_state import load_settings

    return sieg.conferir_e_trocar(banco.tabelas["cert_snapshots"][0]["items"], load_settings())


def _novo_de_a(banco: _Fake) -> None:
    banco.tabelas["cert_snapshots"][0]["items"].append(_item(DOC_A, FP_E, nome="ALFA", venc=AGORA + timedelta(days=700)))
    banco.tabelas["cert_pfx_store"].append({**banco.tabelas["cert_pfx_store"][0], "id": "pfx-e", "fingerprint": FP_E})


def test_inclusao_confere_a_validade_no_sieg(client: TestClient, banco: _Fake, siegf: sf.SiegFalso) -> None:
    _configurar(client)
    _ensinar(siegf, banco, FP_A)
    siegf.cadastro(DOC_A, "ALFA", expira=VELHO)
    siegf.editar_ignora = True
    assert _incluir(client, FP_A).status_code == 202
    e = sieg.estado(FP_A)
    assert e["estado"] == "erro" and "continua com o certificado" in e["mensagem"]
    siegf.editar_ignora = False
    assert _incluir(client, FP_A).status_code == 202
    assert sieg.estado(FP_A)["estado"] == "no_sieg"


def test_reconciliar_com_outro_certificado_no_sieg(client: TestClient, banco: _Fake, siegf: sf.SiegFalso) -> None:
    _configurar(client)
    _ensinar(siegf, banco, FP_A)
    assert _incluir(client, FP_A).status_code == 202
    siegf.cadastros[0]["DataExpira"] = VELHO  # alguém pôs outro certificado no painel do SIEG
    r = client.post(f"/api/sieg/certificado/{FP_A}/reconciliar", headers=_h(*ADMIN))
    e = r.json()["estado"]
    assert e["estado"] == "removido" and "outro certificado" in e["mensagem"]


def test_sincronizar_marca_o_certificado_que_esta_la(client: TestClient, banco: _Fake, siegf: sf.SiegFalso) -> None:
    _configurar(client)
    _novo_de_a(banco)
    siegf.cadastro(DOC_A, "ALFA", expira=_validade(banco, FP_A))  # o SIEG tem o antigo, não o mais novo
    assert client.post("/api/sieg/sincronizar", headers=_h(*ADMIN)).json()["marcados"] == 1
    assert sieg.estado(FP_A)["estado"] == "no_sieg" and sieg.estado(FP_E) is None


def test_troca_automatica_pelo_mais_novo(client: TestClient, banco: _Fake, siegf: sf.SiegFalso) -> None:
    _configurar(client)
    _ensinar(siegf, banco, FP_A)
    siegf.cadastro(DOC_A, "ALFA", expira=VELHO)
    r = _ciclo(banco)
    assert r["trocados"] == 1 and r["falhas"] == 0
    e = sieg.estado(FP_A)
    assert e["estado"] == "no_sieg" and e["solicitado_por"] == sieg.POR_AUTOMATICO
    assert siegf.cadastros[0]["DataExpira"] == _validade(banco, FP_A)
    assert siegf.payloads[-1]["CertificadoId"] == f"20929-{DOC_A}"
    assert _ciclo(banco)["trocados"] == 0, "já está com o mais novo: não troca de novo"


def test_troca_automatica_corrige_o_no_sieg_errado(client: TestClient, banco: _Fake, siegf: sf.SiegFalso) -> None:
    _configurar(client)
    _ensinar(siegf, banco, FP_A)
    siegf.cadastro(DOC_A, "ALFA", expira=VELHO)
    banco.tabelas["sieg_inclusao"].append({  # o que a sincronização de 07/10 gravou
        "fingerprint": FP_A, "documento": DOC_A, "nome": "ALFA", "estado": "no_sieg", "sieg_id": "",
        "solicitado_por": "admin@x.com", "solicitado_em": VELHO, "atualizado_em": VELHO,
        "substituido_por": "", "mensagem": "Já estava no SIEG (sincronização).",
    })
    r = _ciclo(banco)
    assert r["divergentes"] == 1 and r["trocados"] == 1
    assert sieg.estado(FP_A)["estado"] == "no_sieg"
    assert siegf.cadastros[0]["DataExpira"] == _validade(banco, FP_A)
    eventos = [t["evento"] for t in sieg.trilha(FP_A)]
    assert "conferido_divergente" in eventos and eventos[0] == "incluido"


def test_renovacao_troca_e_marca_o_antigo_substituido(client: TestClient, banco: _Fake, siegf: sf.SiegFalso) -> None:
    _configurar(client)
    _novo_de_a(banco)
    _ensinar(siegf, banco, FP_A, FP_E)
    assert _incluir(client, FP_A).status_code == 202
    r = _ciclo(banco)
    assert r["trocados"] == 1
    assert sieg.estado(FP_E)["estado"] == "no_sieg"
    assert sieg.estado(FP_A)["estado"] == "substituido"
    assert siegf.cadastros[0]["DataExpira"] == _validade(banco, FP_E)


def test_sem_cofre_nao_troca(client: TestClient, banco: _Fake, siegf: sf.SiegFalso) -> None:
    _configurar(client)
    siegf.cadastro(DOC_C, "GAMA", expira=VELHO)  # FP_C não está no cofre
    assert _ciclo(banco)["trocados"] == 0
    assert sieg.estado(FP_C) is None and "/api/v1/editar" not in siegf.chamadas


def test_erro_recente_nao_repete_a_cada_ciclo(client: TestClient, banco: _Fake, siegf: sf.SiegFalso) -> None:
    _configurar(client)
    _ensinar(siegf, banco, FP_A)
    siegf.cadastro(DOC_A, "ALFA", expira=VELHO)
    siegf.editar_ignora = True
    assert _ciclo(banco)["falhas"] == 1
    editados = siegf.chamadas.count("/api/v1/editar")
    assert _ciclo(banco)["trocados"] == 0
    assert siegf.chamadas.count("/api/v1/editar") == editados


def test_portal_roda_o_ciclo_do_sieg(monkeypatch) -> None:
    """O laço do lifespan chama ciclo_sieg, que passa o snapshot e a configuração."""
    import inspect

    import app.main as m
    from app import settings_state

    chamadas = []
    monkeypatch.setattr(sieg, "configurado", lambda s: True)
    monkeypatch.setattr(sieg, "conferir_e_trocar", lambda itens, s: chamadas.append(itens))
    monkeypatch.setattr(settings_state, "get_latest_snapshot", lambda: {"items": [{"x": 1}]})
    m.ciclo_sieg()
    assert chamadas == [[{"x": 1}]]
    assert "run_in_executor(None, ciclo_sieg)" in inspect.getsource(m.lifespan)


def test_cliente_excluido_no_sieg_vira_fora_do_sieg(client: TestClient, banco: _Fake, siegf: sf.SiegFalso) -> None:
    _configurar(client)
    _ensinar(siegf, banco, FP_A)
    for i in range(5):  # outros clientes seguem no SIEG: não é listagem quebrada
        siegf.cadastro(f"9999999900{i:04d}", f"OUTRO {i}")
        banco.tabelas["sieg_inclusao"].append({"fingerprint": f"{i}" * 64, "documento": f"9999999900{i:04d}",
                                               "nome": "", "estado": "no_sieg", "atualizado_em": VELHO})
    assert _incluir(client, FP_A).status_code == 202
    siegf.cadastros[-1]["Deletado"] = True  # alguém excluiu ALFA no painel do SIEG
    r = _ciclo(banco)
    assert r["fora"] == 1
    e = sieg.estado(FP_A)
    assert e["estado"] == "removido" and "Não existe no SIEG" in e["mensagem"]


def test_listagem_suspeita_nao_tira_ninguem(client: TestClient, banco: _Fake, siegf: sf.SiegFalso) -> None:
    _configurar(client)
    _ensinar(siegf, banco, FP_A)
    assert _incluir(client, FP_A).status_code == 202
    siegf.cadastros.clear()  # listagem voltou vazia
    assert _ciclo(banco)["fora"] == 0
    assert sieg.estado(FP_A)["estado"] == "no_sieg"
