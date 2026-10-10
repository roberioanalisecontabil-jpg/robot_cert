"""
Leva A de "feche o que falta" (03/10/2026). Decisões fechadas por grill:

  Histórico ganha filtro por status pela URL (?status=ilegivel), e o cartão
  Acervo ilegível do Dashboard aponta para ele.
  Aba "Avisos enviados" no Acompanhamento: Administrador vê tudo, Gestor e
  Operador só o que foi para o próprio e-mail. O cartão Alertas aponta para lá.
  Usuários: "Enviar código de redefinição" reutiliza o código de 6 dígitos do
  "esqueci minha senha"; sem link novo.
  Expurgo de `cert_snapshots` com 180 dias, preservando a última varredura de
  cada máquina — e o expurgo diário passa a rodar no laço do servidor, não só
  na rota de cron que ninguém chama fora da Vercel.
  Trilha do Instalador: retenção indeterminada por decisão; o aviso vira
  informação.

Escritos antes da implementação.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.rotas import usuarios
from app import snapshots
from tests.test_seguranca_lote1 import _Fake
from tests.test_seguranca_lote4 import ADMIN, DOC_A, DOC_B, FISCAL_OP, GESTOR, _h  # noqa: F401
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401

RAIZ = Path(__file__).resolve().parents[1]
AGORA = datetime.now(timezone.utc)


@pytest.fixture
def banco(banco_base: _Fake) -> _Fake:
    banco_base.tabelas["carteira_excecao"] = []
    banco_base.tabelas["sent_alerts"] = []
    banco_base.tabelas["password_reset_codigo"] = []
    return banco_base


def _hist(chave: str, nome: str, doc: str, status: str) -> dict:
    return {"arquivo_chave": chave * 64, "nome_publico": f"{nome}_{doc}", "nome": nome, "documento": doc,
            "status_ultimo": status, "vencimento_certificado": None, "ultima_data_registrada": AGORA.isoformat()}


# ──────────────────────────────────────────────────────────────────────────
# 1. Histórico com filtro por status
# ──────────────────────────────────────────────────────────────────────────

def test_historico_filtra_ilegiveis_erro_e_fora_do_padrao(client: TestClient, banco: _Fake) -> None:
    banco.tabelas["cert_history"] += [
        _hist("1", "ALFA", DOC_A, "ok"), _hist("2", "BETA", DOC_B, "erro"), _hist("3", "GAMA", "333", "fora_do_padrao"),
    ]
    r = client.get("/api/certificados/historico?pagina=1&por_pagina=20&status=ilegivel", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert sorted(i["nome"] for i in r.json()["itens"]) == ["BETA", "GAMA"]
    assert r.json()["total"] == 2

    r = client.get("/api/certificados/historico?pagina=1&por_pagina=20&status=erro", headers=_h(*ADMIN))
    assert [i["nome"] for i in r.json()["itens"]] == ["BETA"]

    # A exportação respeita o mesmo filtro.
    r = client.get("/api/certificados/historico?todas_filtradas=true&status=fora_do_padrao", headers=_h(*ADMIN))
    assert [i["nome"] for i in r.json()["itens"]] == ["GAMA"]


def test_historico_filtro_de_status_respeita_o_alcance(client: TestClient, banco: _Fake) -> None:
    """Operador só vê a própria carteira, com ou sem filtro."""
    banco.tabelas["cert_history"] += [_hist("1", "ALFA", DOC_A, "erro"), _hist("2", "BETA", DOC_B, "erro")]
    r = client.get("/api/certificados/historico?status=ilegivel", headers=_h(*FISCAL_OP))
    assert r.status_code == 200, r.text
    assert [i["nome"] for i in r.json()["itens"]] == ["ALFA"]


def test_historico_status_desconhecido_e_422(client: TestClient, banco: _Fake) -> None:
    r = client.get("/api/certificados/historico?status=qualquer", headers=_h(*ADMIN))
    assert r.status_code == 422


def test_historico_tem_o_seletor_de_status_na_tela() -> None:
    html = (RAIZ / "templates" / "historico.html").read_text(encoding="utf-8")
    assert 'id="filtro-status-hist"' in html
    assert 'value="ilegivel"' in html
    assert 'searchParams.set("status"' in html, "o filtro vive na URL"


# ──────────────────────────────────────────────────────────────────────────
# 2. Avisos enviados
# ──────────────────────────────────────────────────────────────────────────

def _enviado(fp: str, tipo: str, para: str, ha_dias: int = 1) -> dict:
    return {"fingerprint_sha256": fp, "tipo_alerta": tipo, "destinatario": para,
            "data_validade": (AGORA + timedelta(days=20)).isoformat(),
            "sent_at": (AGORA - timedelta(days=ha_dias)).isoformat()}


def test_administrador_ve_todos_os_avisos_com_nome_do_certificado(client: TestClient, banco: _Fake) -> None:
    banco.tabelas["sent_alerts"] += [
        _enviado("a" * 64, "expiring:30", "fis@x.com"),
        _enviado("b" * 64, "expired", "solto@x.com"),
        _enviado("__resumo_admin__", f"digest:{AGORA.date().isoformat()}", "admin@x.com"),
        _enviado("a" * 64, "novo", "fis@x.com", ha_dias=40),  # fora dos 30 dias
    ]
    r = client.get("/api/colaborador/alertas/enviados", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ve_tudo"] is True and d["total"] == 3
    por_tipo = {i["tipo"]: i for i in d["itens"]}
    assert por_tipo["expiring:30"]["nome"] == "ALFA" and por_tipo["expiring:30"]["documento"] == DOC_A
    assert por_tipo["expiring:30"]["rotulo"] == "Aviso de vencimento em 30 dias"
    assert por_tipo["expired"]["destinatario"] == "solto@x.com"
    resumo = next(i for t, i in por_tipo.items() if t.startswith("digest:"))
    assert resumo["nome"] is None and resumo["data_validade"] is None and resumo["rotulo"] == "Resumo diário"
    # Mais recente primeiro.
    assert d["itens"][0]["enviado_em"] >= d["itens"][-1]["enviado_em"]


def test_certificado_fora_do_cofre_ganha_nome_pelo_inventario(client: TestClient, banco: _Fake) -> None:
    """GAMA ("c"*64) está no snapshot mas não em cert_pfx_store."""
    banco.tabelas["sent_alerts"] += [_enviado("c" * 64, "expiring:15", "admin@x.com")]
    d = client.get("/api/colaborador/alertas/enviados", headers=_h(*ADMIN)).json()
    assert d["itens"][0]["nome"] == "GAMA" and d["itens"][0]["documento"] == "33333333000193"


def test_operador_so_ve_os_avisos_que_foram_para_ele(client: TestClient, banco: _Fake) -> None:
    banco.tabelas["sent_alerts"] += [
        _enviado("a" * 64, "expiring:7", "fis@x.com"),
        _enviado("b" * 64, "expiring:7", "solto@x.com"),
        _enviado("a" * 64, "novo", "fis@x.com"),
    ]
    r = client.get("/api/colaborador/alertas/enviados?dias=90", headers=_h(*FISCAL_OP))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ve_tudo"] is False
    assert {i["destinatario"] for i in d["itens"]} == {"fis@x.com"}
    assert {i["rotulo"] for i in d["itens"]} == {"Aviso de vencimento em 7 dias", "Certificado novo"}


def test_gestor_tambem_so_ve_os_proprios(client: TestClient, banco: _Fake) -> None:
    banco.tabelas["sent_alerts"] += [_enviado("a" * 64, "expired", "fis@x.com"), _enviado("a" * 64, "expired", "lider@x.com")]
    d = client.get("/api/colaborador/alertas/enviados", headers=_h(*GESTOR)).json()
    assert [i["destinatario"] for i in d["itens"]] == ["lider@x.com"]


def test_sem_sessao_nao_ha_avisos(client_com_chave: TestClient, banco: _Fake) -> None:
    # `client` roda sem API_KEY, que é o modo dev aberto; aqui a chave existe
    # e, sem sessão nem chave, a rota tem de recusar.
    assert client_com_chave.get("/api/colaborador/alertas/enviados").status_code == 401


def test_pagina_acompanhamento_abre_na_aba_enviados(client: TestClient, banco: _Fake) -> None:
    html = client.get("/acompanhamento?aba=enviados").text
    assert 'id="tab-enviados"' in html and 'href="?aba=enviados"' in html
    assert 'id="sec-enviados" role="tabpanel" aria-labelledby="tab-enviados" >' in html.replace("\n", " ") or \
        '<section id="sec-enviados" role="tabpanel" aria-labelledby="tab-enviados" >' in html
    assert 'aria-selected="true"' in html.split('id="tab-enviados"')[1].split(">")[0]


def test_dashboard_aponta_para_os_avisos_enviados() -> None:
    dash = (RAIZ / "templates" / "dashboard.html").read_text(encoding="utf-8")
    assert 'href="/acompanhamento?aba=enviados"' in dash
    assert 'href="/historico?status=ilegivel"' in dash


# ──────────────────────────────────────────────────────────────────────────
# 3. Enviar código de redefinição pelo administrador
# ──────────────────────────────────────────────────────────────────────────

def test_admin_envia_codigo_e_a_pessoa_recebe_pelo_fluxo_existente(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    enviados = []
    monkeypatch.setattr(usuarios, "_enviar_codigo_por_email", lambda conta, codigo: enviados.append((conta["email"], codigo)))
    r = client.post("/api/users/u-fis/enviar-codigo", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert "fis@x.com" in r.json()["message"]
    assert enviados and enviados[0][0] == "fis@x.com" and len(enviados[0][1]) == 6
    # O código mora na mesma tabela do "esqueci minha senha": é o mesmo fluxo.
    assert any(c.get("user_id") == "u-fis" for c in banco.tabelas["password_reset_codigo"])


def test_so_administrador_envia_codigo(client: TestClient, banco: _Fake) -> None:
    assert client.post("/api/users/u-fis/enviar-codigo", headers=_h(*GESTOR)).status_code == 403
    assert client.post("/api/users/u-fis/enviar-codigo", headers=_h(*FISCAL_OP)).status_code == 403


def test_conta_desativada_nao_recebe_codigo(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    next(u for u in banco.tabelas["users"] if u["id"] == "u-fis")["ativo"] = False
    enviados = []
    monkeypatch.setattr(usuarios, "_enviar_codigo_por_email", lambda conta, codigo: enviados.append(1))
    r = client.post("/api/users/u-fis/enviar-codigo", headers=_h(*ADMIN))
    assert r.status_code == 400 and not enviados


def test_conta_inexistente_e_404(client: TestClient, banco: _Fake) -> None:
    assert client.post("/api/users/nao-existe/enviar-codigo", headers=_h(*ADMIN)).status_code == 404


def test_usuarios_tem_o_botao_de_enviar_codigo() -> None:
    html = (RAIZ / "templates" / "usuarios.html").read_text(encoding="utf-8")
    assert 'data-action="codigo"' in html
    assert "Enviar código de redefinição" in html
    assert "/enviar-codigo" in html


# ──────────────────────────────────────────────────────────────────────────
# 4. Expurgo de cert_snapshots
# ──────────────────────────────────────────────────────────────────────────

def _snap(id_: str, maq: str, ha_dias: int) -> dict:
    return {"id": id_, "machine_id": maq, "scanned_at": (AGORA - timedelta(days=ha_dias)).isoformat(), "items": []}


def test_expurgo_apaga_os_antigos_e_preserva_o_ultimo_de_cada_maquina(banco: _Fake) -> None:
    banco.tabelas["cert_snapshots"] = [
        _snap("srv-novo", "srv", 1), _snap("srv-velho", "srv", 200), _snap("srv-velho2", "srv", 400),
        # Máquina parada há um ano: o último inventário conhecido FICA.
        _snap("par-ultimo", "parada", 300), _snap("par-anterior", "parada", 365),
    ]
    out = snapshots.expurgar(180)
    assert out["executado"] is True and out["apagados"] == 3 and out["preservados"] == 2
    assert {s["id"] for s in banco.tabelas["cert_snapshots"]} == {"srv-novo", "par-ultimo"}


def test_expurgo_desligado_com_zero(banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    banco.tabelas["cert_snapshots"] = [_snap("a", "srv", 400), _snap("b", "srv", 1)]
    monkeypatch.setenv("SNAPSHOTS_RETENCAO_DIAS", "0")
    out = snapshots.expurgar()
    assert out["executado"] is False and len(banco.tabelas["cert_snapshots"]) == 2


def test_retencao_padrao_e_180_dias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SNAPSHOTS_RETENCAO_DIAS", raising=False)
    assert snapshots.retencao_dias() == 180
    monkeypatch.setenv("SNAPSHOTS_RETENCAO_DIAS", "abc")
    assert snapshots.retencao_dias() == 180


def test_expurgo_diario_inclui_snapshots_e_nao_derruba_os_outros(banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    def quebra():
        raise RuntimeError("cofre fora")
    monkeypatch.setattr(m.cert_installer, "expurgar_cofre", quebra)
    banco.tabelas["cert_snapshots"] = [_snap("a", "srv", 400), _snap("b", "srv", 1)]
    out = m._expurgo_diario()
    assert out["cofre"]["executado"] is False
    assert out["cert_snapshots"]["executado"] is True and out["cert_snapshots"]["apagados"] == 1
    assert set(out) == {"install_log", "user_activity", "cofre", "cert_snapshots"}


def test_laco_diario_do_servidor_chama_o_expurgo() -> None:
    """Fora da Vercel ninguém chama /api/cron/alerts; se o laço do lifespan
    não expurgar, nada expurga. Inspeção estática do laço."""
    arvore = ast.parse((RAIZ / "app" / "main.py").read_text(encoding="utf-8"))
    laco = next(n for n in ast.walk(arvore) if isinstance(n, ast.AsyncFunctionDef) and n.name == "daily_alerts_job_loop")
    nomes = {n.id for n in ast.walk(laco) if isinstance(n, ast.Name)}
    assert "_expurgo_diario" in nomes


# ──────────────────────────────────────────────────────────────────────────
# 5. Trilha: retenção indeterminada é decisão, não descuido
# ──────────────────────────────────────────────────────────────────────────

def test_instalador_nao_trata_retencao_indeterminada_como_aviso() -> None:
    html = (RAIZ / "templates" / "instalador.html").read_text(encoding="utf-8")
    assert "sem prazo de exclusão" not in html
    assert "Retenção indeterminada, por decisão de 03/10/2026" in html
    assert 'id="cfgRetencaoAviso"' in html and 'ag-alert--info" id="cfgRetencaoAviso"' in html
