"""
Lote 4 das correções do SECURITY_AUDIT.md — leitura restrita à carteira.

O portal impedia INSTALAR fora da carteira (`assegurar_carteira`) mas não
impedia LER a base inteira de clientes: `/api/certificados` (e histórico,
vencidos, opções do Acompanhamento, cofre disponível) devolvia todo o acervo a
qualquer autenticado — num portal de certificados A1 de empresas, o dado
comercial e pessoal mais sensível depois do PFX (achados #5, #32). A trilha e
os logs de instalação expunham e-mail e IP de todos os operadores (#31). O
export do histórico ignorava a busca e as datas dos vencidos não eram
validadas (#54).

Cada teste foi escrito antes da correção e falhava em `a36556c` (fim do lote 3).
Um ponto só de recorte, `_recortar_pela_carteira`, aplicado em todas as
leituras; o alcance de cada papel:

  * admin: tudo
  * gestor (líder): a própria carteira + as carteiras de quem está nos
    departamentos que lidera
  * user: a própria carteira
  * carteira indisponível: 503, nunca lista vazia
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Set

import pytest
from fastapi.testclient import TestClient

import app.cert_installer as ci
import app.main as m
from app import auth, config, permissoes
from tests.test_seguranca_lote1 import _Fake, _usuario

FISCAL = "dep-fiscal"
DOC_A, DOC_B, DOC_C, DOC_L = "11111111000191", "22222222000192", "33333333000193", "44444444000194"
ADMIN, GESTOR, FISCAL_OP, SOLTO = ("admin@x.com", "admin"), ("lider@x.com", "gestor"), ("fis@x.com", "user"), ("solto@x.com", "user")
AGORA = datetime.now(timezone.utc)


def _h(email: str, papel: str) -> dict:
    return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": papel})}


def _item(doc: str | None, fp: str, status: str = "ok", venc: datetime | None = None, nome: str = "") -> dict:
    v = venc or (AGORA + timedelta(days=200))
    return {"nome_publico": f"{nome or 'EMPRESA'}_{doc or 'X'}", "pasta": "F:/C", "nome": nome or f"EMPRESA {doc}",
            "documento_numero": doc, "documento_formatado": doc, "status": status,
            "fingerprint_sha256": fp, "not_after": v.isoformat(), "not_before": (v - timedelta(days=365)).isoformat()}


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake({
        "users": [
            _usuario("u-adm", "admin@x.com", "admin"),
            _usuario("u-lf", "lider@x.com", "gestor", departamento_id=FISCAL),
            _usuario("u-fis", "fis@x.com", "user", departamento_id=FISCAL),
            _usuario("u-sol", "solto@x.com", "user"),
        ],
        "user_activity": [],
        "departamento_lider": [{"departamento_id": FISCAL, "user_id": "u-lf"}],
        "carteira": [{"user_id": "u-fis", "documento": DOC_A}, {"user_id": "u-sol", "documento": DOC_B},
                     {"user_id": "u-lf", "documento": DOC_L}],
        "cert_snapshots": [{
            "id": "s1", "machine_id": "srv", "scanned_at": AGORA.isoformat(), "source_folder": "F:/C", "expired_folder": "F:/V",
            "items": [
                _item(DOC_A, "a" * 64, nome="ALFA"),
                _item(DOC_B, "b" * 64, nome="BETA"),
                _item(DOC_C, "c" * 64, nome="GAMA"),
                _item(DOC_L, "d" * 64, status="expirado", venc=AGORA - timedelta(days=30), nome="LIDER SA"),
                {"nome_publico": "ILEGIVEL", "pasta": "F:/C", "nome": "ILEGIVEL", "status": "erro",
                 "documento_numero": None, "fingerprint_sha256": None, "not_after": None},
            ],
        }],
        "cert_history": [],
        "cert_pfx_store": [
            {"id": "pfx-a", "fingerprint": "a" * 64, "machine_id": "srv", "documento": DOC_A, "nome_titular": "ALFA",
             "uploaded_at": AGORA.isoformat()},
            {"id": "pfx-b", "fingerprint": "b" * 64, "machine_id": "srv", "documento": DOC_B, "nome_titular": "BETA",
             "uploaded_at": AGORA.isoformat()},
        ],
        "install_log": [
            {"id": 1, "token_id": "t-fis", "user_id": "u-fis", "user_email": "fis@x.com", "event": "SOLICITADO",
             "target_machine": "pc-fis", "client_ip": "10.0.0.5", "created_at": AGORA.isoformat(), "status": None,
             "detail": None, "certificate_id": "pfx-a"},
            {"id": 2, "token_id": "t-sol", "user_id": "u-sol", "user_email": "solto@x.com", "event": "SOLICITADO",
             "target_machine": "pc-sol", "client_ip": "10.0.0.9", "created_at": AGORA.isoformat(), "status": None,
             "detail": None, "certificate_id": "pfx-b"},
        ],
        "agent_devices": [],
    })
    monkeypatch.setattr("app.settings_state._banco", lambda: fake)
    monkeypatch.setattr(ci, "_banco", lambda: fake)
    monkeypatch.setattr(m, "trigger_all_alerts", lambda: None)
    # A agregação do histórico tem cache em RAM com TTL: sem limpar, o
    # agregado de outro teste (outro fake) responde por este.
    from app import historico_agg_cache

    historico_agg_cache.invalidate_all()
    yield fake
    historico_agg_cache.invalidate_all()


@pytest.fixture
def user_le_instalador(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tela de permissões pode dar `instalador: ler` a operador e gestor."""
    matriz = {p: {mod: permissoes.NIVEL_NENHUM for mod in permissoes.MODULOS} for p in ("gestor", "user")}
    for p in matriz:
        matriz[p]["instalador"] = permissoes.NIVEL_LER
        matriz[p]["historico"] = permissoes.NIVEL_LER
        matriz[p]["vencidos"] = permissoes.NIVEL_LER
        matriz[p]["acompanhamento"] = permissoes.NIVEL_LER
    monkeypatch.setattr(permissoes, "_matriz", lambda: matriz)


def _docs(itens: List[dict]) -> Set[str]:
    return {ci.so_digitos(i.get("documento_numero") or i.get("documento")) for i in itens}


# ──────────────────────────────────────────────────────────────────────────
# #5 — /api/certificados
# ──────────────────────────────────────────────────────────────────────────

def test_operador_so_ve_a_propria_carteira(client: TestClient, banco: _Fake) -> None:
    r = client.get("/api/certificados?fonte=remoto&todas_filtradas=true", headers=_h(*FISCAL_OP))
    assert r.status_code == 200, r.text
    assert _docs(r.json()["itens"]) == {DOC_A}


def test_operador_sem_setor_so_ve_a_propria_carteira(client: TestClient, banco: _Fake) -> None:
    r = client.get("/api/certificados?fonte=remoto&todas_filtradas=true", headers=_h(*SOLTO))
    assert _docs(r.json()["itens"]) == {DOC_B}


def test_lider_ve_a_propria_carteira_e_as_do_seu_setor(client: TestClient, banco: _Fake) -> None:
    """O gestor não tem alcance total desde 18/08; sem isto veria nada (a
    carteira dele) ou tudo. O alcance é o do setor que lidera."""
    r = client.get("/api/certificados?fonte=remoto&todas_filtradas=true", headers=_h(*GESTOR))
    assert _docs(r.json()["itens"]) == {DOC_A, DOC_L}


def test_admin_continua_vendo_tudo(client: TestClient, banco: _Fake) -> None:
    r = client.get("/api/certificados?fonte=remoto&todas_filtradas=true", headers=_h(*ADMIN))
    itens = r.json()["itens"]
    assert _docs(itens) == {DOC_A, DOC_B, DOC_C, DOC_L, ""}
    assert len(itens) == 5


def test_paginacao_conta_so_o_que_a_pessoa_alcanca(client: TestClient, banco: _Fake) -> None:
    r = client.get("/api/certificados?fonte=remoto&pagina=1&por_pagina=10", headers=_h(*FISCAL_OP))
    j = r.json()
    assert _docs(j["itens"]) == {DOC_A}
    assert j["paginacao"]["total_itens"] == 1
    assert j["paginacao"]["total_paginas"] == 1


def test_carteira_indisponivel_e_503_e_nao_lista_vazia(client: TestClient, banco: _Fake) -> None:
    banco.quebrado["carteira"] = True
    r = client.get("/api/certificados?fonte=remoto&todas_filtradas=true", headers=_h(*FISCAL_OP))
    assert r.status_code == 503, r.text
    # admin não depende da carteira
    assert client.get("/api/certificados?fonte=remoto&todas_filtradas=true", headers=_h(*ADMIN)).status_code == 200


# ──────────────────────────────────────────────────────────────────────────
# histórico, vencidos, opções, cofre disponível — o MESMO recorte
# ──────────────────────────────────────────────────────────────────────────

def test_historico_recortado(client: TestClient, banco: _Fake, user_le_instalador: None) -> None:
    r = client.get("/api/certificados/historico?pagina=1&por_pagina=20", headers=_h(*FISCAL_OP))
    assert r.status_code == 200, r.text
    j = r.json()
    assert _docs(j["itens"]) == {DOC_A}
    assert j["total"] == 1
    export = client.get("/api/certificados/historico?todas_filtradas=true", headers=_h(*GESTOR)).json()
    assert _docs(export["itens"]) == {DOC_A, DOC_L}


def test_vencidos_recortado(client: TestClient, banco: _Fake, user_le_instalador: None) -> None:
    gestor = client.get("/api/certificados/vencidos", headers=_h(*GESTOR)).json()
    assert _docs(gestor["itens"]) == {DOC_L}
    op = client.get("/api/certificados/vencidos", headers=_h(*FISCAL_OP)).json()
    assert op["itens"] == [] and op["total"] == 0


def test_opcoes_do_acompanhamento_recortadas(client: TestClient, banco: _Fake, user_le_instalador: None) -> None:
    r = client.get("/api/colaborador/certificados/opcoes", headers=_h(*FISCAL_OP))
    assert r.status_code == 200, r.text
    assert {ci.so_digitos(i.get("documento")) for i in r.json()["itens"]} == {DOC_A}


def test_cofre_disponivel_recortado(client: TestClient, banco: _Fake, user_le_instalador: None) -> None:
    r = client.get("/api/cert-installer/available", headers=_h(*FISCAL_OP))
    assert r.status_code == 200, r.text
    assert {c["documento"] for c in r.json()["certificates"]} == {DOC_A}
    assert {c["documento"] for c in client.get("/api/cert-installer/available", headers=_h(*ADMIN)).json()["certificates"]} == {DOC_A, DOC_B}


def test_recorte_exclui_item_sem_documento_para_quem_nao_tem_alcance_total() -> None:
    itens = [{"documento_numero": DOC_A}, {"documento_numero": None}, {"documento": "22.222.222/0001-92"}]
    assert m._recortar_pela_carteira(itens, {DOC_A}) == [{"documento_numero": DOC_A}]
    assert m._recortar_pela_carteira(itens, None) == itens


# ──────────────────────────────────────────────────────────────────────────
# #31 — trilha e logs escopados; client_ip só para admin
# ──────────────────────────────────────────────────────────────────────────

def test_logs_so_os_proprios_e_sem_ip(client: TestClient, banco: _Fake, user_le_instalador: None) -> None:
    r = client.get("/api/cert-installer/logs", headers=_h(*FISCAL_OP))
    assert r.status_code == 200, r.text
    logs = r.json()["logs"]
    assert {l["user_email"] for l in logs} == {"fis@x.com"}
    assert all("client_ip" not in l for l in logs)
    adm = client.get("/api/cert-installer/logs", headers=_h(*ADMIN)).json()["logs"]
    assert {l["user_email"] for l in adm} == {"fis@x.com", "solto@x.com"}
    assert all(l.get("client_ip") for l in adm)


def test_trilha_ignora_user_email_alheio_e_esconde_ip(client: TestClient, banco: _Fake, user_le_instalador: None) -> None:
    r = client.get("/api/cert-installer/trilha?user_email=solto@x.com", headers=_h(*FISCAL_OP))
    assert r.status_code == 200, r.text
    cadeias = r.json()["cadeias"]
    assert {c["user_email"] for c in cadeias} == {"fis@x.com"}
    assert all("client_ip" not in c for c in cadeias)
    adm = client.get("/api/cert-installer/trilha?user_email=solto@x.com", headers=_h(*ADMIN)).json()["cadeias"]
    assert {c["user_email"] for c in adm} == {"solto@x.com"}
    assert all(c.get("client_ip") for c in adm)


# ──────────────────────────────────────────────────────────────────────────
# #54 — busca no export do histórico; datas validadas
# ──────────────────────────────────────────────────────────────────────────

def test_export_do_historico_aplica_a_busca(client: TestClient, banco: _Fake) -> None:
    """`_cert_history_fetch_all` lia a tabela inteira e a busca era ignorada
    justamente no caminho que gera o arquivo exportado."""
    banco.tabelas["cert_history"] += [
        {"arquivo_chave": "1" * 64, "nome_publico": "ALFA_" + DOC_A, "nome": "ALFA", "documento": DOC_A,
         "status_ultimo": "ok", "vencimento_certificado": None, "ultima_data_registrada": AGORA.isoformat()},
        {"arquivo_chave": "2" * 64, "nome_publico": "BETA_" + DOC_B, "nome": "BETA", "documento": DOC_B,
         "status_ultimo": "ok", "vencimento_certificado": None, "ultima_data_registrada": AGORA.isoformat()},
    ]
    r = client.get("/api/certificados/historico?todas_filtradas=true&busca=ALFA", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert [i["nome"] for i in r.json()["itens"]] == ["ALFA"]


@pytest.mark.parametrize("param", ["data_inicio=abc", "data_fim=2026-13-99", "data_inicio=2026-01-01T00:00:00"])
def test_data_invalida_nos_vencidos_e_422(client: TestClient, banco: _Fake, param: str) -> None:
    r = client.get(f"/api/certificados/vencidos?{param}", headers=_h(*ADMIN))
    assert r.status_code == 422, r.text


def test_data_valida_nos_vencidos_continua_filtrando(client: TestClient, banco: _Fake) -> None:
    ini = (AGORA - timedelta(days=60)).date().isoformat()
    fim = (AGORA - timedelta(days=1)).date().isoformat()
    r = client.get(f"/api/certificados/vencidos?data_inicio={ini}&data_fim={fim}", headers=_h(*ADMIN))
    assert r.status_code == 200 and _docs(r.json()["itens"]) == {DOC_L}


# ──────────────────────────────────────────────────────────────────────────
# #61 — universo de documentos para atribuir: contrato mínimo
# ──────────────────────────────────────────────────────────────────────────

def test_universo_de_documentos_so_nome_e_documento_e_so_para_lider(client: TestClient, banco: _Fake,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """Risco aceito e documentado: o líder precisa poder atribuir qualquer
    cliente. O que se garante é o mínimo: só quem lidera chega, e só saem
    nome e documento."""
    matriz = {p: {mod: permissoes.NIVEL_NENHUM for mod in permissoes.MODULOS} for p in ("gestor", "user")}
    matriz["gestor"]["carteiras"] = permissoes.NIVEL_EDITAR
    matriz["user"]["carteiras"] = permissoes.NIVEL_EDITAR
    monkeypatch.setattr(permissoes, "_matriz", lambda: matriz)
    assert client.get("/api/carteira/documentos", headers=_h(*FISCAL_OP)).status_code == 403
    r = client.get("/api/carteira/documentos", headers=_h(*GESTOR))
    assert r.status_code == 200, r.text
    for d in r.json()["documentos"]:
        assert set(d.keys()) <= {"nome", "documento", "documento_tipo"}, d
