"""Aba Uso em Carteiras e a rota que a alimenta (Frente C, Task 6)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_seguranca_lote4 import ADMIN, FISCAL, GESTOR, SOLTO, FISCAL_OP, DOC_A, DOC_B, _h
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401

RAIZ = Path(__file__).resolve().parents[1]
JS = RAIZ / "static" / "carteiras-uso.js"
HORA = datetime(2026, 11, 15, 15, 0, tzinfo=timezone.utc).isoformat()
EVENTO = datetime(2026, 11, 15, 15, 7, tzinfo=timezone.utc).isoformat()


def _uso(uid, doc, maquina="m1", fp="a" * 64, **extra) -> dict:
    return {"machine_id": maquina, "sid": "S-1", "usuario_windows": "win", "conteiner": "c", "hora": HORA,
            "primeiro_em": HORA, "ultimo_em": HORA, "quantidade": 2, "ultimo_record": 1,
            "fingerprint": fp, "documento": doc, "user_id": uid, **extra}


@pytest.fixture
def banco(banco_base):  # noqa: F811
    banco_base.tabelas["uso_certificado"] = [
        _uso("u-fis", DOC_A),
        _uso("u-sol", DOC_B),          # fora do departamento do gestor
        _uso(None, DOC_A, usuario_windows="perfil"),  # sem login
        _uso("u-fis", DOC_A, fp=None, documento=None),  # pendente
    ]
    banco_base.tabelas["uso_coleta"] = [{"machine_id": "m1", "ultima_em": HORA, "auditoria": "desligada"}]
    banco_base.tabelas["agent_devices"] = [{"machine_id": "m1", "nome": "PC-FISCAL", "visto_em": HORA}]
    return banco_base


def _get(client, quem, qs=""):
    return client.get("/api/carteira/uso?desde=2026-11-01" + qs, headers=_h(*quem))


def test_admin_ve_tudo_inclusive_sem_login(client: TestClient, banco) -> None:
    j = _get(client, ADMIN).json()
    assert len(j["linhas"]) == 3
    sem = [l for l in j["linhas"] if l["sem_login"]]
    assert len(sem) == 1 and sem[0]["usuario_windows"] == "perfil"
    por_pessoa = [l for l in j["linhas"] if not l["sem_login"] and l["email"] == "fis@x.com"]
    assert por_pessoa[0]["nome_maquina"] == "PC-FISCAL" and por_pessoa[0]["titular"] == "ALFA"
    assert j["coletas"]["m1"]["auditoria"] == "desligada"


def test_gestor_so_ve_os_departamentos_dele(client: TestClient, banco) -> None:
    j = _get(client, GESTOR).json()
    assert [l["email"] for l in j["linhas"]] == ["fis@x.com"]
    assert not any(l["sem_login"] for l in j["linhas"])


def test_gestor_com_user_id_de_fora_recebe_vazio(client: TestClient, banco) -> None:
    r = _get(client, GESTOR, "&user_id=u-sol")
    assert r.status_code == 200 and r.json()["linhas"] == []


def test_operador_recebe_403(client: TestClient, banco) -> None:
    assert _get(client, FISCAL_OP).status_code == 403
    assert _get(client, SOLTO).status_code == 403


def test_pendente_nao_aparece(client: TestClient, banco) -> None:
    assert all(l["documento"] for l in _get(client, ADMIN).json()["linhas"])


def test_filtros_e_paginacao(client: TestClient, banco) -> None:
    assert len(_get(client, ADMIN, "&documento=" + DOC_B).json()["linhas"]) == 1
    assert _get(client, ADMIN, "&desde=2026-11-16").json()["linhas"] == []
    banco.tabelas["uso_certificado"] += [_uso("u-fis", DOC_A) for _ in range(60)]
    j = _get(client, ADMIN).json()
    assert len(j["linhas"]) == 50 and j["tem_mais"] is True
    assert _get(client, ADMIN, "&pagina=2").json()["tem_mais"] is False


def test_paginacao_traz_total_como_no_inicio(client: TestClient, banco) -> None:
    # Barra numerada igual à do Início: precisa do total, não só de "tem mais".
    banco.tabelas["uso_certificado"] += [_uso("u-fis", DOC_A) for _ in range(60)]
    j = _get(client, ADMIN, "&por_pagina=25&pagina=3").json()
    assert (j["total_itens"], j["total_paginas"], j["pagina"]) == (63, 3, 3)
    assert len(j["linhas"]) == 13 and j["tem_mais"] is False
    assert _get(client, ADMIN, "&por_pagina=500").status_code == 422


def test_aba_uso_existe_e_abre_pelo_link(client: TestClient) -> None:
    html = client.get("/carteiras?aba=uso").text
    assert 'id="sec-uso"' in html and "/static/carteiras-uso.js" in html
    assert re.search(r'data-aba="uso" aria-selected="true"', html)
    assert re.search(r'data-aba="pessoas" aria-selected="false"', html)


def test_js_nunca_monta_html_com_dado_da_estacao() -> None:
    assert "innerHTML" not in JS.read_text(encoding="utf-8")






def test_cache_buster_do_js_subiu() -> None:
    html = (RAIZ / "templates" / "carteiras.html").read_text(encoding="utf-8")
    assert "carteiras-uso.js?v=sem-rolagem-2026-11-21" in html




def test_modal_importar_manteve_o_espaco_do_atributo() -> None:
    html = (RAIZ / "templates" / "carteiras.html").read_text(encoding="utf-8")
    assert 'id="modalImportar" aria-labelledby=' in html




def _janela(uso_id, record_id, ordem, programa, titulo) -> dict:
    return {"uso_id": uso_id, "machine_id": "m1", "record_id": record_id, "ordem": ordem,
            "quando": HORA, "evento_em": EVENTO, "programa": programa, "titulo": titulo}


@pytest.fixture
def com_janelas(banco):
    banco.tabelas["uso_certificado"] = [_uso("u-fis", DOC_A, id=1), _uso("u-fis", DOC_A, id=2),
                                        _uso("u-fis", DOC_A, id=3)]
    banco.tabelas["uso_janela"] = [
        _janela(1, 10, 0, "chrome.exe", "Portal A"),
        _janela(1, 12, 0, "outlook.exe", "Caixa"),   # maior record_id: dá o `sistema`
        _janela(1, 12, 1, "chrome.exe", "Antes"),    # ordem 1 não conta
        _janela(1, 11, 0, "chrome.exe", "Portal A"), # par repetido não soma
        _janela(2, 20, 0, "chrome.exe", "Portal B"),
    ]
    return banco


def test_admin_ve_uma_linha_por_pagina(client: TestClient, com_janelas) -> None:
    """21/11/2026: cada página distinta (janela da frente, ordem 0) dentro de
    um uso vira uma linha; a mesma página em vários eventos conta uma vez, e
    o uso sem janela conta uma vez. Sem coluna de sistema nem de quantidade."""
    j = _get(client, ADMIN).json()
    assert j["total_itens"] == 4 and len(j["linhas"]) == 4  # uso 1: Portal A e Caixa; 2: Portal B; 3: sem janela
    assert not ({"sistema", "outras", "quantidade"} & set(j["linhas"][0])) and j["mostra_pagina"] is True
    assert sorted(l["id"] for l in j["linhas"]) == [1, 1, 2, 3]  # o id do uso abre o modal de janelas
    assert sorted((l["quando"], l["pagina_acessada"]) for l in j["linhas"]) == sorted(
        [(EVENTO, "chrome.exe · Portal A"), (EVENTO, "outlook.exe · Caixa"), (EVENTO, "chrome.exe · Portal B"), (HORA, "")])


def test_pagina_vale_na_primeira_vez_que_aparece(client: TestClient, com_janelas) -> None:
    com_janelas.tabelas["uso_certificado"] = [_uso("u-fis", DOC_A, id=1)]
    cedo = datetime(2026, 11, 15, 15, 2, tzinfo=timezone.utc).isoformat()
    com_janelas.tabelas["uso_janela"] = [{**_janela(1, 10, 0, "chrome.exe", "Portal A"), "evento_em": EVENTO},
                                         {**_janela(1, 9, 0, "chrome.exe", "Portal A"), "evento_em": cedo}]
    assert [l["quando"] for l in _get(client, ADMIN).json()["linhas"]] == [cedo]


def test_gestor_ve_uma_linha_por_uso_sem_pagina(client: TestClient, com_janelas) -> None:
    j = _get(client, GESTOR).json()
    assert j["total_itens"] == 3 and len(j["linhas"]) == 3
    assert all(not ({"id", "sistema", "outras", "pagina", "pagina_acessada"} & set(l)) for l in j["linhas"])
    assert j["mostra_pagina"] is False


def test_detalhe_so_admin(client: TestClient, com_janelas) -> None:
    assert client.get("/api/carteira/uso/1/janelas", headers=_h(*GESTOR)).status_code == 403
    assert client.get("/api/carteira/uso/1/janelas", headers=_h(*FISCAL_OP)).status_code == 403
    r = client.get("/api/carteira/uso/1/janelas", headers=_h(*ADMIN))
    assert r.status_code == 200
    usos = r.json()["usos"]
    assert [u["record_id"] for u in usos] == [10, 11, 12]
    assert [(w["ordem"], w["programa"], w["titulo"]) for w in usos[2]["janelas"]] == [
        (0, "outlook.exe", "Caixa"), (1, "chrome.exe", "Antes")]
    assert usos[0]["janelas"][0]["quando"] == HORA
    # O título do bloco é a hora do uso, não a da janela que ganhou o foco.
    assert all(u["evento_em"] == EVENTO for u in usos)


def test_detalhe_inexistente_404(client: TestClient, com_janelas) -> None:
    assert client.get("/api/carteira/uso/999/janelas", headers=_h(*ADMIN)).status_code == 404


def test_detalhe_com_banco_fora_503(client: TestClient, com_janelas, monkeypatch) -> None:
    original = com_janelas.table

    def _quebra(nome, *a, **k):
        if nome == "uso_janela":  # a sessão usa o mesmo banco; só a leitura das janelas cai
            raise RuntimeError("fora")
        return original(nome, *a, **k)
    monkeypatch.setattr(com_janelas, "table", _quebra)
    r = client.get("/api/carteira/uso/1/janelas", headers=_h(*ADMIN))
    assert r.status_code == 503 and "uso" in r.json()["detail"].lower()


def test_paginas_com_a_mesma_hora_nao_repetem_nem_perdem_linhas(client: TestClient, banco) -> None:
    # hora é balde de uma hora: empate é a regra, e o desempate pelo id mantém as páginas disjuntas.
    banco.tabelas["uso_certificado"] = [_uso(None, DOC_A, id=i, usuario_windows=str(i)) for i in range(1, 76)]
    ids = []
    for p in (1, 2):
        j = _get(client, ADMIN, f"&pagina={p}").json()
        ids += [int(l["usuario_windows"]) for l in j["linhas"]]
    assert sorted(ids) == list(range(1, 76))  # sem repetir nem perder
    assert ids[:3] == [75, 74, 73]


def test_visao_por_certificado_com_historico_paginado() -> None:
    """Proposta B (21/11/2026): lista de certificados e detalhe pela rota de
    resumo; o Histórico abre com 10 por página e vai a 20, 50 ou 100."""
    html = (RAIZ / "templates" / "carteiras.html").read_text(encoding="utf-8")
    opcoes = re.findall(r'<option value="(\d+)"( selected)?>\d+ por página</option>',
                        html.split('id="uso-por-pagina"')[1].split("</select>")[0])
    assert opcoes == [("10", " selected"), ("20", ""), ("50", ""), ("100", "")]
    for id_ in ("uso-certs", "uso-detalhe", "uso-colunas", "uso-quem", "uso-busca", "uso-linhas", "uso-coletas"):
        assert f'id="{id_}"' in html
    js = JS.read_text(encoding="utf-8")
    assert "/api/carteira/uso/resumo?" in js and 'q.set("documento", docSel)' in js
    # O "por página" fica na barra: ela não pode sumir com uma página só.
    assert "hideWhenSingle: false" in js


def test_historico_sem_coluna_de_sistema_nem_de_usos() -> None:
    """21/11/2026: cada linha já é um uso (uma página, para o admin); a coluna
    Usos confundia (contava assinaturas da chave). Sistema/Página fica só para
    o admin, e o nome abre o modal com as janelas do uso."""
    html = (RAIZ / "templates" / "carteiras.html").read_text(encoding="utf-8")
    cab = html.split('aria-label="Histórico de uso do certificado"')[1].split("</thead>")[0]
    assert re.findall(r">([^<>]+)</th>", cab) == ["Quando", "Pessoa", "Máquina", "Sistema/Página"]
    assert 'id="uso-th-pagina" hidden' in cab
    assert 'id="modalUsoJanelas"' in html and "É a janela que estava na tela no momento do uso." in html
    js = JS.read_text(encoding="utf-8")
    assert "/janelas" in js and "abrirJanelas(l.id)" in js and "quantidade" not in js and "innerHTML" not in js
    # Clique antigo não sobrescreve o modal de um clique novo; rótulo contém o texto visível.
    assert "const meu = ++seqJanelas;" in js and js.count("if (meu !== seqJanelas) return;") >= 3
    assert '"Ver janelas do uso: " + b.textContent' in js


def test_js_da_aba_uso_e_javascript_valido() -> None:
    """21/11/2026: um corte errado deixou o arquivo sem fechar uma função e os
    testes de texto acima passaram assim mesmo."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node não instalado")
    r = subprocess.run([node, "--check", str(JS)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_coleta_traz_o_nome_da_maquina_mesmo_fora_da_pagina(client: TestClient, banco) -> None:
    """21/11/2026: o quadro de coletas mostrava o MAC da máquina sem linha na página."""
    banco.tabelas["uso_coleta"].append({"machine_id": "m2", "ultima_em": HORA, "auditoria": "ligada"})
    banco.tabelas["agent_devices"].append({"machine_id": "m2", "nome": "PC-SEM-USO", "visto_em": HORA})
    c = _get(client, ADMIN).json()["coletas"]
    assert c["m2"]["nome"] == "PC-SEM-USO" and c["m1"]["nome"] == "PC-FISCAL"


def test_coleta_por_maquina_recolhe() -> None:
    """21/11/2026: o quadro abre recolhido; o resumo (com selo se houver
    problema) fica no título clicável."""
    html = (RAIZ / "templates" / "carteiras.html").read_text(encoding="utf-8")
    quadro = html.split('id="uso-coletas-quadro"')[0].rsplit("<", 1)[1] + html.split('id="uso-coletas-quadro"')[1].split("</details>")[0]
    assert quadro.startswith("details") and " open" not in quadro.split(">")[0]
    assert "<summary" in quadro and 'id="uso-coletas-resumo"' in quadro.split("</summary>")[0]


def test_css_de_carteiras_sem_caractere_de_controle() -> None:
    """21/11/2026: um escape "\25B8" virou o caractere 0x15 ao gravar e a seta
    do quadro de coletas saiu como um quadrado."""
    css = (RAIZ / "static" / "aguia-carteiras.css").read_text(encoding="utf-8")
    assert not [c for c in css if ord(c) < 32 and c not in "\n\r\t"]
