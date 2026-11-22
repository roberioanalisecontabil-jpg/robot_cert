"""Achados baixos da revisão de 21/11/2026 (lote 4, parte D): telas de
Usuários e Configuração, e a leitura de /api/settings pelo agente."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parents[1]
USUARIOS = (RAIZ / "templates" / "usuarios.html").read_text(encoding="utf-8")
CONFIG = (RAIZ / "templates" / "configuracao.html").read_text(encoding="utf-8")


def _trecho(html: str, inicio: str, fim: str) -> str:
    return html.split(inicio, 1)[1].split(fim, 1)[0]


# ── Usuários ────────────────────────────────────────────────────────────────

def test_p7_2_novo_departamento_guarda_o_id_para_a_nova_tentativa() -> None:
    """Depois do POST, um novo Salvar (gestores falharam) tem de fazer PUT,
    e não POST de novo, que daria 409 de nome duplicado."""
    salvar = _trecho(USUARIOS, "document.getElementById('form-dep').addEventListener('submit'", "async function apagarDep")
    assert "depEditandoId = id" in salvar


def test_p7_3_importar_csv_reabilita_o_botao_mesmo_com_erro_de_rede() -> None:
    imp = _trecho(USUARIOS, "document.getElementById('import-users-form').addEventListener('submit'", "document.getElementById('form-filtros')")
    assert "} finally {" in imp
    assert imp.index("} finally {") > imp.index("await fetch('/api/users/import'")
    assert "Erro de conexão com o servidor" in imp


def test_p7_3_acoes_da_lista_mostram_erro_de_rede() -> None:
    for inicio, fim in (
        ("async function apagarDep(id)", "\n        }\n"),
        ("async function desativarUsuario(id)", "\n        async function desligarMicrosoft"),
        ("async function desligarMicrosoft(id)", "\n        async function reativarUsuario"),
        ("async function reativarUsuario(id)", "\n        /**"),
    ):
        corpo = _trecho(USUARIOS, inicio, fim)
        assert "catch" in corpo and "Erro de conexão com o servidor" in corpo, inicio


def test_p7_4_remover_app_autenticador_pede_confirmacao() -> None:
    corpo = _trecho(USUARIOS, "async function removerAppAutenticador(id, btn)", "function redefinirSenha")
    assert "confirmarAcao(" in corpo
    assert corpo.index("confirmarAcao(") < corpo.index("await fetch(")


# ── Configuração ────────────────────────────────────────────────────────────

def test_p8_4_salvar_alertas_repinta_os_textos_em_uso() -> None:
    h = _trecho(CONFIG, 'document.getElementById("btn-save-smtp").addEventListener("click"', "function resultadoTeste")
    assert "preencherAlertas(s)" in h and "preencherModeloEmail(s)" in h


def test_p8_5_guardado_aparece_depois_de_recarregar_o_formulario() -> None:
    h = _trecho(CONFIG, 'document.getElementById("btn-save-cfg").addEventListener("click"', "// ── Salvar remoção")
    assert h.index('"Guardado (') > h.index("await loadSettingsToForm()")


def test_p8_7_falha_nos_departamentos_nao_desenha_tudo_sem_par() -> None:
    f = _trecho(CONFIG, "async function carregarAcessoriasCfg()", "async function salvarAcessorias")
    # Sem a lista do portal, nenhum par é desenhado (todos sairiam "sem par").
    assert "rd.ok ? await rd.json() : []" not in f
    catch = f.split("catch (e)", 1)[1]
    for tbody in ("acess-deps", "acess-sem-par", "acess-decidir"):
        assert tbody in catch, tbody


# ── /api/settings lido pelo agente ─────────────────────────────────────────

def test_p8_6_agente_le_so_as_pastas(client_com_chave: TestClient, api_key: str) -> None:
    j = client_com_chave.get("/api/settings", headers={"X-API-Key": api_key}).json()
    for k in ("source_folder", "expired_folder", "machine_id", "effective_source",
              "effective_expired", "pasta_entrada", "pasta_pj", "pasta_pf"):
        assert k in j, k
    for k in ("smtp_host", "smtp_user", "graph_client_id", "graph_tenant_id",
              "graph_remetente", "alertas_destinatarios", "alerta_email"):
        assert k not in j, k


def test_p8_6_admin_continua_lendo_tudo(client_com_chave: TestClient, api_key: str) -> None:
    from app import auth

    h = {"Authorization": "Bearer " + auth.create_access_token({"sub": "adm@x.com", "role": "admin"})}
    j = client_com_chave.get("/api/settings", headers=h).json()
    assert "smtp_user" in j and "alertas_destinatarios" in j
