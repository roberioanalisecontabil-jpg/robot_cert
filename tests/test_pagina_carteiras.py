"""
Revisão da página Carteiras (01/10/2026) — decisões C1 a C5 e defeitos.

Registro em docs/revisao-paginas-2026-10.md. Em resumo:

  C1  Verbos pelo glossário: Atribuir/Retirar (Operador), Devolver/Retirar (Gestor).
  C2  "Cliente" fica na tela para o titular; Documento é a chave.
  C3  O Gestor vê as instalações dos Operadores dos departamentos que lidera,
      por uma rota da própria tela de Carteiras.
  C4  Atribuir um só não confirma; em lote e retirar confirmam.
  C5  O Dashboard conta "sem carteira" com o critério de Carteiras.

Defeitos: universo recortado pelo alcance do gestor; atribuição e exceção
validam inventário; planilha recusa conta inativa; administrador não tem
carteira (nem por link direto); exceção fora do inventário aparece no painel.

Escritos antes da implementação; falhavam em 4847248.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as m
from tests.test_seguranca_lote1 import _Fake, _usuario
from tests.test_seguranca_lote4 import ADMIN, DOC_A, DOC_B, DOC_C, DOC_L, FISCAL, FISCAL_OP, GESTOR, _h  # noqa: F401
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401

RAIZ = Path(__file__).resolve().parents[1]
TODOS = {DOC_A, DOC_B, DOC_C, DOC_L}
DOC_FORA = "99999999000199"
CONTABIL = "dep-contabil"


@pytest.fixture
def banco(banco_base: _Fake) -> _Fake:
    banco_base.tabelas["departamento"] = [{"id": FISCAL, "nome": "Fiscal"}, {"id": CONTABIL, "nome": "Contábil"}]
    banco_base.tabelas["users"].append(_usuario("u-con", "con@x.com", "user", departamento_id=CONTABIL))
    banco_base.tabelas["users"].append(_usuario("u-off", "off@x.com", "user", departamento_id=FISCAL, ativo=False))
    banco_base.tabelas["carteira_excecao"] = []
    return banco_base


def _docs_do_universo(client: TestClient, quem) -> set:
    r = client.get("/api/carteira/documentos?limite=2000", headers=_h(*quem))
    assert r.status_code == 200, r.text
    return {d["documento"] for d in r.json()["documentos"]}


# ── Universo recortado pelo alcance ───────────────────────────────────────

def test_universo_do_gestor_e_o_alcance_dele(client: TestClient, banco: _Fake) -> None:
    assert _docs_do_universo(client, GESTOR) == TODOS
    client.delete(f"/api/carteira/u-lf/{DOC_B}", headers=_h(*ADMIN))
    assert _docs_do_universo(client, GESTOR) == TODOS - {DOC_B}, "o gestor não vê o que não pode atribuir"
    assert _docs_do_universo(client, ADMIN) == TODOS


# ── Inventário ────────────────────────────────────────────────────────────

def test_atribuir_e_excecao_so_sobre_documento_do_inventario(client: TestClient, banco: _Fake) -> None:
    r = client.post("/api/carteira", json={"user_id": "u-fis", "documentos": [DOC_FORA]}, headers=_h(*ADMIN))
    assert r.status_code == 422 and DOC_FORA in r.json()["detail"], r.text
    r = client.delete(f"/api/carteira/u-lf/{DOC_FORA}", headers=_h(*ADMIN))
    assert r.status_code == 422, r.text
    assert banco.tabelas["carteira_excecao"] == []
    # Retirar atribuição de documento que saiu do inventário continua livre.
    banco.tabelas["carteira"].append({"user_id": "u-fis", "documento": DOC_FORA, "atribuido_por_email": "x"})
    assert client.delete(f"/api/carteira/u-fis/{DOC_FORA}", headers=_h(*ADMIN)).status_code == 200


# ── Administrador não tem carteira ────────────────────────────────────────

def test_administrador_nao_tem_carteira_nem_por_link_direto(client: TestClient, banco: _Fake) -> None:
    assert client.get("/api/carteira/u-adm", headers=_h(*ADMIN)).status_code == 422
    assert client.post("/api/carteira", json={"user_id": "u-adm", "documentos": [DOC_A]}, headers=_h(*ADMIN)).status_code == 422
    assert all(r["user_id"] != "u-adm" for r in banco.tabelas["carteira"])


# ── Planilha recusa conta inativa ─────────────────────────────────────────

def test_planilha_recusa_conta_desativada(client: TestClient, banco: _Fake) -> None:
    csv = f"email;cnpj\noff@x.com;{DOC_A}\nfis@x.com;{DOC_C}\n"
    r = client.post("/api/carteira/importar", headers=_h(*ADMIN),
                    files={"file": ("c.csv", io.BytesIO(csv.encode("utf-8")), "text/csv")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["atribuidos"] == 1
    assert any("desativad" in e["motivo"] for e in d["erros"])
    assert not any(r_["user_id"] == "u-off" for r_ in banco.tabelas["carteira"])


# ── C3: instalações da pessoa com o alcance da carteira ──────────────────

def test_gestor_ve_instalacoes_dos_seus_operadores(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas = []

    def _cadeias(limite, desde, user_email, apenas_com_falha=False):
        chamadas.append(user_email)
        return [{"token_id": "t", "user_email": user_email, "inicio": desde, "certificados": 1,
                 "target_machine": "pc", "desfecho": "Concluída", "client_ip": "10.0.0.5"}]

    monkeypatch.setattr(m.cert_installer, "cadeias_de_instalacao", _cadeias)
    monkeypatch.setattr(m.cert_installer, "resumo_das_cadeias", lambda c: {"total": len(c), "concluidas": len(c), "falhadas": 0})

    r = client.get("/api/carteira/u-fis/instalacoes", headers=_h(*GESTOR))
    assert r.status_code == 200, r.text
    assert chamadas == ["fis@x.com"], "a consulta é pelo e-mail da pessoa, não por parâmetro livre"
    assert "client_ip" not in r.json()["cadeias"][0], "IP só para o administrador"
    assert r.json()["resumo"]["total"] == 1
    # Fora do alcance: operador de outro departamento, e o próprio gestor.
    assert client.get("/api/carteira/u-con/instalacoes", headers=_h(*GESTOR)).status_code == 403
    assert client.get("/api/carteira/u-lf/instalacoes", headers=_h(*GESTOR)).status_code == 403
    # Administrador alcança todos e recebe o IP.
    r = client.get("/api/carteira/u-con/instalacoes", headers=_h(*ADMIN))
    assert r.status_code == 200 and "client_ip" in r.json()["cadeias"][0]
    # Operador não entra na tela.
    assert client.get("/api/carteira/u-fis/instalacoes", headers=_h(*FISCAL_OP)).status_code == 403


# ── C5: Dashboard com o critério de Carteiras ─────────────────────────────

def test_dashboard_conta_sem_carteira_como_carteiras(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import dashboard as dash

    # `dashboard` importa `_banco` por nome; a fixture troca o de settings_state.
    monkeypatch.setattr(dash, "_banco", lambda: banco)

    # Linha de carteira de uma conta INATIVA e de um GESTOR não podem contar
    # como "operador com carteira".
    banco.tabelas["carteira"].append({"user_id": "u-off", "documento": DOC_A})
    a = dash.painel_acesso()
    # Operadores ativos: u-fis (DOC_A), u-sol (DOC_B), u-con (nada).
    assert a["operadores"] == 3
    assert a["operadores_com_carteira"] == 2
    assert [p["email"] for p in a["operadores_sem_carteira"]] == ["con@x.com"]
    r = client.get("/api/carteira/operadores", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    ops = {o["id"]: o for o in r.json()["operadores"]}
    assert sum(1 for o in ops.values() if o["sem_carteira"]) == 1, "o mesmo número da tela de Carteiras"


# ── Vocabulário e tela ────────────────────────────────────────────────────

def test_tela_de_carteiras_revisada() -> None:
    html = (RAIZ / "templates" / "carteiras.html").read_text(encoding="utf-8")
    baixo = html.lower()
    assert "liberar" not in baixo and "liberado" not in baixo and "libere" not in baixo, "C1: atribuir, não liberar"
    assert ">Atribuir<" in html and ">Retirar<" in html and '"Devolver"' in html
    assert "atribuído por" in baixo
    assert "Disponível para administradores" not in html, "C3: o gestor vê as instalações dos seus operadores"
    assert "/instalacoes" in html
    assert "souAdmin" not in html
    assert "fora_do_inventario" in html, "exceção fora do inventário aparece no painel"
    assert "atualizarAviso()" in html
    assert "_resumo.texto" in html or "_resumo && _resumo.texto" in html
    assert "Só para operadores dos departamentos que você lidera" in html, "texto do gestor fica no init"


def test_mensagens_do_servidor_dizem_atribuir() -> None:
    from app import papeis
    assert "liberar" not in m.ERRO_SEM_ALCANCE and "atribuir" in m.ERRO_SEM_ALCANCE
    assert "liberar" not in papeis.DEPARTAMENTO_OBRIGATORIO


# ── Leva C (06/10/2026): painel do operador no Águia ──────────────────────

def test_universo_traz_documento_formatado(client: TestClient, banco: _Fake) -> None:
    r = client.get("/api/carteira/documentos?limite=2000", headers=_h(*ADMIN))
    for d in r.json()["documentos"]:
        digitos = d["documento"]
        if len(digitos) == 14:
            assert d["documento_formatado"] == f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"
        elif len(digitos) == 11:
            assert d["documento_formatado"] == f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"
        else:
            assert d["documento_formatado"] == digitos


def test_painel_do_operador_usa_as_celulas_do_ds() -> None:
    html = (RAIZ / "templates" / "carteiras.html").read_text(encoding="utf-8")
    assert "ainda sem spec" not in html
    assert "documento_formatado" in html and "nomeDeQuem(" in html
    assert 'class="ag-cell-main"' in html and "ag-cell-sub--mono" in html
