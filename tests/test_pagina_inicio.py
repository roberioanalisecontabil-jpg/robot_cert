"""
Revisão da página Início (01/10/2026) — decisões I1 a I5 e defeitos.

Registro em docs/revisao-paginas-2026-10.md. Em resumo:

  I1  Vencidos saem do Início (`ocultar_vencidos`), com a contagem "N vencidos
      não listados" e link para a página Vencidos.
  I2  Uma estação por pessoa: a atual, com agente vivo, é a padrão.
  I3  A seção "Meus computadores" sai; estações são do Hardlyze.
  I4  O sino mantém a seleção de Acompanhamento para expirando/vencidos.
  I5  O sino não depende do módulo Acompanhamento: `require_auth`.

Defeitos: a instalabilidade passa a receber a estação da pessoa (`estacao`)
separada do servidor da varredura (`machine_id`); operador sem Atribuição vê
"carteira vazia", não "o agente não enviou dados".

Escritos antes da implementação; falhavam em f978947.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app import permissoes
from tests.test_seguranca_lote1 import _Fake
from tests.test_seguranca_lote4 import ADMIN, DOC_A, DOC_B, DOC_C, DOC_L, FISCAL_OP, GESTOR, SOLTO, _docs, _h  # noqa: F401
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401

RAIZ = Path(__file__).resolve().parents[1]
CERTS = "/api/certificados?fonte=remoto&todas_filtradas=true"


@pytest.fixture
def banco(banco_base: _Fake) -> _Fake:
    banco_base.tabelas["carteira_excecao"] = []
    return banco_base


# ── I1: vencidos fora do Início ───────────────────────────────────────────

def test_ocultar_vencidos_tira_da_lista_e_conta(client: TestClient, banco: _Fake) -> None:
    """DOC_L está expirado no cenário do lote 4."""
    r = client.get(CERTS + "&ocultar_vencidos=true", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    d = r.json()
    assert DOC_L not in _docs(d["itens"])
    assert d["vencidos_ocultos"] == 1
    assert d["resumo"]["vencidos"] == 0, "o resumo é da lista que a tela mostra"
    # Sem o parâmetro, nada muda.
    d2 = client.get(CERTS, headers=_h(*ADMIN)).json()
    assert DOC_L in _docs(d2["itens"]) and d2["vencidos_ocultos"] == 0


# ── Carteira vazia é diferente de "sem inventário" ────────────────────────

def test_operador_sem_atribuicao_recebe_alcance_vazio(client: TestClient, banco: _Fake) -> None:
    banco.tabelas["carteira"] = [r for r in banco.tabelas["carteira"] if r["user_id"] != "u-fis"]
    d = client.get(CERTS, headers=_h(*FISCAL_OP)).json()
    assert d["alcance_vazio"] is True
    assert d["itens"] and not any(i["instalavel"] for i in d["itens"]), "vê tudo, não instala nada (08/10/2026)"
    assert client.get(CERTS, headers=_h(*SOLTO)).json()["alcance_vazio"] is False, "quem tem atribuição não está vazio"
    assert client.get(CERTS, headers=_h(*ADMIN)).json()["alcance_vazio"] is False
    assert client.get(CERTS, headers=_h(*GESTOR)).json()["alcance_vazio"] is False


# ── Instalabilidade: servidor da varredura x estação da pessoa ────────────

def test_instalabilidade_confere_o_vinculo_pela_estacao(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    """`machine_id` é o servidor que varreu (snapshot "srv"); `estacao` é a
    máquina da pessoa. O vínculo é da estação. Até 30/09 era conferido contra
    o servidor, e operador/gestor recebiam 403 sempre."""
    from app import computadores

    monkeypatch.setattr(m, "_computador_autorizado_da_pessoa",
                        lambda uid: {"machine_id": "pc-fis", "nome": "PC DA FIS", "autorizacao": computadores.AUTORIZADO})
    r = client.get("/api/cert-installer/instalabilidade?machine_id=srv&estacao=pc-fis", headers=_h(*FISCAL_OP))
    assert r.status_code == 200, r.text
    assert r.json()["estacao"] == "pc-fis" and r.json()["machine_id"] == "srv"
    assert "a" * 64 in r.json()["itens"], "o inventário é o do servidor da varredura"
    # Estação de outra pessoa: 403.
    r = client.get("/api/cert-installer/instalabilidade?machine_id=srv&estacao=pc-de-outro", headers=_h(*FISCAL_OP))
    assert r.status_code == 403
    # Com computador autorizado e sem `estacao`, o vínculo é conferido contra
    # `machine_id`, como antes (achado #30).
    assert client.get("/api/cert-installer/instalabilidade?machine_id=srv", headers=_h(*FISCAL_OP)).status_code == 403
    # Sem computador nenhum: só o inventário do servidor da varredura,
    # recortado pela carteira (08/10/2026; antes perguntava ao Hardlyze).
    monkeypatch.setattr(m, "_computador_autorizado_da_pessoa", lambda uid: None)
    assert client.get("/api/cert-installer/instalabilidade?machine_id=srv", headers=_h(*FISCAL_OP)).status_code == 200
    # Administrador não tem vínculo a conferir.
    assert client.get("/api/cert-installer/instalabilidade?machine_id=srv", headers=_h(*ADMIN)).status_code == 200


# ── I5: sino sem depender do módulo Acompanhamento ────────────────────────

def test_sino_funciona_mesmo_sem_o_modulo_acompanhamento(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    matriz = {p: {mod: permissoes.NIVEL_NENHUM for mod in permissoes.MODULOS} for p in ("gestor", "user")}
    monkeypatch.setattr(permissoes, "_matriz", lambda: matriz)
    assert client.get("/api/colaborador/notificacoes", headers=_h(*FISCAL_OP)).status_code == 200
    assert client.post("/api/colaborador/notificacoes/lidas", headers=_h(*FISCAL_OP)).status_code == 200
    # A PÁGINA Acompanhamento continua governada pela matriz.
    assert client.get("/api/colaborador/certificados/painel", headers=_h(*FISCAL_OP)).status_code == 403


# ── Tela ──────────────────────────────────────────────────────────────────

def test_tela_do_inicio_revisada() -> None:
    html = (RAIZ / "templates" / "index.html").read_text(encoding="utf-8")
    assert "Meus computadores" not in html and "carregarDispositivos" not in html, "I3"
    assert "nesta máquina" not in html, "I2: a estação da pessoa tem nome"
    assert "&estacao=" in html, "a instalabilidade vai com a estação da pessoa"
    assert 'ocultar_vencidos: "true"' in html and "ver Vencidos" in html, "I1"
    assert "Sua carteira está vazia" in html
    assert "Planilha (CSV)" in html and "Planilha (Excel)" not in html
    assert "Nao foi possivel" not in html and "instalacao\"" not in html
    assert "MOTIVO_SEM_ESTACAO" in html and "nao_configurado" in html
    assert '"desconhecido"' in html
    assert "das suas empresas" not in html


def test_vocabulario_dos_modulos_do_inicio() -> None:
    for arq in ("app/cert_installer.py", "app/novos_certificados.py", "app/notification_service.py"):
        texto = (RAIZ / arq).read_text(encoding="utf-8")
        assert "líder" not in texto and "setores" not in texto.lower(), arq
