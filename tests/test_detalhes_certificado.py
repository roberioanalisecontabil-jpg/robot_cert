"""
Modal de detalhes do certificado no Início (06/10/2026, grill "modal + SIEG").

Q7(b): responsável, CPF, nascimento e e-mail só para quem pode instalar o
certificado. No portal "ver e instalar são um direito só" (alcance da
carteira), então a rota de detalhes usa o mesmo `_documentos_ao_alcance` da
lista, e fora do alcance o certificado nem existe (404).

O teste de vazamento chama TODAS as rotas GET da API sem parâmetro de
caminho com um inventário que traz o CPF do responsável: o valor não pode
sair por nenhuma delas. Rota nova que devolva o item cru reprova aqui.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from tests.test_seguranca_lote1 import _Fake
from tests.test_seguranca_lote4 import ADMIN, DOC_A, DOC_B, FISCAL_OP, GESTOR, _h  # noqa: F401
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401

CPF_SECRETO = "05375987406"
EMAIL_SECRETO = "responsavel.secreto@exemplo.com.br"
PESSOAIS = {
    "tipo_icp": "e-CNPJ",
    "organizacao": "ICP-Brasil",
    "emissor": "AC SAFEWEB RFB v5",
    "responsavel_nome": "ANTONIO GALDINO LIMA",
    "responsavel_cpf": CPF_SECRETO,
    "responsavel_nascimento": "1984-08-14",
    "email": EMAIL_SECRETO,
    "serial_number": "66ffeef438c45637",
}


@pytest.fixture
def banco(banco_base: _Fake):
    import app.main as m

    for it in banco_base.tabelas["cert_snapshots"][0]["items"]:
        if it.get("documento_numero") in (DOC_A, DOC_B):
            it.update(PESSOAIS)
    # O teste de vazamento passa por /duplicidades, que memoiza por data da
    # varredura: sem limpar, o resultado daqui responde pelo próximo teste.
    m._dup_cache.clear()
    yield banco_base
    m._dup_cache.clear()


def _det(client: TestClient, fp: str, quem) -> "object":
    return client.get(f"/api/certificados/{fp}/detalhes", headers=_h(*quem))


def test_detalhes_trazem_os_campos_do_modal(client: TestClient, banco: _Fake) -> None:
    r = _det(client, "a" * 64, FISCAL_OP)  # DOC_A está na carteira de u-fis
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["responsavel_cpf"] == CPF_SECRETO and d["email"] == EMAIL_SECRETO
    assert d["responsavel_nome"] == "ANTONIO GALDINO LIMA" and d["responsavel_nascimento"] == "1984-08-14"
    assert d["emissor"] == "AC SAFEWEB RFB v5" and d["organizacao"] == "ICP-Brasil" and d["tipo_icp"] == "e-CNPJ"
    assert d["serial_number"] == "66ffeef438c45637" and d["no_cofre"] is True
    assert "pasta" not in d, "arquivo e pasta só para o administrador"


def test_fora_da_carteira_abre_sem_dado_pessoal(client: TestClient, banco: _Fake) -> None:
    """08/10/2026: todos veem todos; fora da carteira o modal abre, mas sem os
    dados pessoais do responsável e marcado como não instalável."""
    r = _det(client, "b" * 64, FISCAL_OP)  # DOC_B é de outro operador
    assert r.status_code == 200, r.text
    assert CPF_SECRETO not in r.text and EMAIL_SECRETO not in r.text
    assert r.json()["instalavel"] is False and "pasta" not in r.json()
    assert _det(client, "a" * 64, FISCAL_OP).json()["instalavel"] is True
    sieg = client.get("/api/sieg/certificado/" + "b" * 64, headers=_h(*FISCAL_OP))
    assert sieg.status_code == 200 and sieg.json()["na_carteira"] is False
    assert client.post("/api/sieg/certificado/" + "b" * 64 + "/incluir", headers=_h(*FISCAL_OP)).status_code == 404,         "ligar o SIEG segue a carteira"
    assert _det(client, "f" * 64, ADMIN).status_code == 404
    assert _det(client, "nao-hex", ADMIN).status_code in (404, 422)


def test_administrador_ve_o_arquivo(client: TestClient, banco: _Fake) -> None:
    d = _det(client, "b" * 64, ADMIN).json()
    assert d["pasta"] == "F:/C" and d["nome_publico"]
    assert d["no_cofre"] is True
    assert _det(client, "c" * 64, ADMIN).json()["no_cofre"] is False


def test_nenhuma_rota_de_lista_vaza_dado_pessoal(client: TestClient, banco: _Fake) -> None:
    from app.main import app

    vazou = []
    for rota in app.routes:
        caminho = getattr(rota, "path", "")
        if "GET" not in getattr(rota, "methods", set()) or not caminho.startswith("/api/") or "{" in caminho:
            continue
        r = client.get(caminho, headers=_h(*ADMIN))
        if r.status_code != 200:
            continue
        corpo = r.text
        if CPF_SECRETO in corpo or EMAIL_SECRETO in corpo:
            vazou.append(caminho)
    assert not vazou, f"dado pessoal saiu por: {vazou}"


def test_lista_do_inicio_continua_com_os_campos_publicos(client: TestClient, banco: _Fake) -> None:
    r = client.get("/api/certificados?pagina=1&por_pagina=50", headers=_h(*ADMIN))
    itens = {i["fingerprint_sha256"]: i for i in r.json()["itens"]}
    a = itens["a" * 64]
    assert a["emissor"] == "AC SAFEWEB RFB v5" and a["serial_number"] == "66ffeef438c45637"
    for campo in ("responsavel_nome", "responsavel_cpf", "responsavel_nascimento", "email"):
        assert campo not in a, campo
    assert json.dumps(r.json()).count(CPF_SECRETO) == 0


def test_inventario_de_agente_antigo_tira_emissor_e_cadeia_do_texto(client: TestClient, banco: _Fake) -> None:
    for it in banco.tabelas["cert_snapshots"][0]["items"]:
        if it.get("documento_numero") == DOC_A:
            for campo in list(PESSOAIS):
                it.pop(campo, None)
            it["issuer"] = "CN=AC SAFEWEB RFB v5,OU=Secretaria da Receita Federal do Brasil - RFB,O=ICP-Brasil,C=BR"
            it["subject"] = "CN=ALFA:11111111000191,OU=x,O=ICP-Brasil,C=BR"
    d = _det(client, "a" * 64, FISCAL_OP).json()
    assert d["emissor"] == "AC SAFEWEB RFB v5" and d["organizacao"] == "ICP-Brasil"
    assert "responsavel_cpf" not in d, "ausente = a tela diz que falta o agente novo"


def test_atributo_de_dn_com_escape() -> None:
    from app.main import _atributo_rfc4514 as f
    assert f(r"CN=EMPRESA\, LTDA:1,O=ICP-Brasil", "CN") == "EMPRESA, LTDA:1"
    assert f("OU=CN teste,CN=X", "CN") == "X"
    assert f(None, "CN") is None and f("C=BR", "O") is None
