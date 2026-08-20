"""Configuração do módulo instalador: nome do arquivo, validade e retenção.

Leva 3b da etapa 3 (`docs/PLANO_reorganizacao_portal.md` §4, pontos 2, 5 e 7).
Os três valores estavam fixos no código, e cada um tem um trade-off que só quem
administra o portal resolve.

O que estes testes protegem, em ordem de gravidade:

1. **O `{token}` no nome do arquivo.** Não é decoração — o instalador avulso lê
   o token do próprio `argv[0]`, porque o binário é idêntico em todo download
   (é o que permite assiná-lo uma vez e acumular reputação no SmartScreen). Um
   template sem `{token}` produz um `.exe` que abre e não instala nada, e o
   sintoma aparece na máquina do usuário final.
2. **A rota parcial não pode apagar o SMTP.** `PUT /api/settings` monta um
   `PortalSettings` inteiro a partir do corpo; uma tela que mandasse só os três
   campos do instalador zeraria host, usuário e senha — sem erro, e ninguém
   notaria até o próximo alerta não sair.
3. **Zero significa "padrão", não "desligado".** Uma configuração nunca tocada
   tem de se comportar exatamente como antes de existir.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import auth, config
import app.cert_installer as ci
import app.main as m
from app.settings_state import PortalSettings


def _admin() -> dict:
    return {"Authorization": f"Bearer {auth.create_access_token({'sub': 'admin@x.com', 'role': 'admin'})}"}


@pytest.fixture
def settings_em_memoria(monkeypatch: pytest.MonkeyPatch) -> PortalSettings:
    """Configuração viva na memória, com SMTP preenchido para servir de canário."""
    estado = PortalSettings(
        source_folder="F:/certs",
        expired_folder="F:/vencidos",
        machine_id="ANALISESRV",
        smtp_host="smtp.exemplo.com",
        smtp_user="alertas@exemplo.com",
        smtp_password_encrypted="cifrada",
        smtp_from_email="alertas@exemplo.com",
        smtp_alerts_enabled=True,
    )

    def _load():
        return estado

    def _save(s, **_kwargs):
        # `**_kwargs` absorve o `exigir_supabase` que as rotas de tela passam.
        # Aqui não há Supabase para falhar: gravou na memória, gravou de fato.
        for campo in vars(s):
            setattr(estado, campo, getattr(s, campo))
        return True

    monkeypatch.setattr(m, "load_settings", _load)
    monkeypatch.setattr(m, "save_settings", _save)
    monkeypatch.setattr("app.settings_state.load_settings", _load)
    return estado


# ──────────────────────────────────────────────────────────────────────────
# 1. O {token} é funcional
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("template,porque", [
    ("Instalar {nome}.exe", "sem {token} o instalador não acha o token"),
    ("Instalar {token}", "sem .exe o Windows não executa"),
    ("C:/pasta/{token}.exe", "separador de caminho escapa do nome"),
    ("Instalar {cliente} {token}.exe", "marcador que ninguém substitui vira texto literal"),
    ("x" * 130 + "{token}.exe", "nome longo demais"),
])
def test_template_invalido_e_recusado(template: str, porque: str) -> None:
    with pytest.raises(ValueError):
        ci.validar_template_nome(template)


@pytest.mark.parametrize("template", [
    "Instalar {nome} -{token}.exe",
    "Certificado {nome} [{token}].exe",
    "{token}.exe",
])
def test_template_valido_passa(template: str) -> None:
    assert ci.validar_template_nome(template) == template


def test_vazio_significa_padrao_e_nao_erro() -> None:
    assert ci.validar_template_nome("") == ""
    assert ci.validar_template_nome("   ") == ""


def test_nome_e_sanitizado_mas_o_token_nunca() -> None:
    """
    Sanitizar o token o corromperia — ele precisa chegar íntegro ao instalador.
    O nome do titular, esse vem do certificado e pode conter qualquer coisa.
    """
    token = "aB3-_xYz"
    saida = ci.montar_nome_do_arquivo("", 'ACME/LTDA: "Filial" <SP>', token)
    assert token in saida
    for proibido in '/\\:*?"<>|':
        assert proibido not in saida


def test_template_gravado_invalido_cai_no_padrao_em_vez_de_quebrar() -> None:
    """
    Se um template inválido escapar da validação por algum caminho, entregar o
    nome padrão dá um instalador que funciona. O erro fica no log, não na mão
    do usuário.
    """
    saida = ci.montar_nome_do_arquivo("sem marcador nenhum.exe", "ACME", "tok123")
    assert "tok123" in saida


def test_download_usa_o_template_configurado(
    settings_em_memoria: PortalSettings, monkeypatch, tmp_path
) -> None:
    """Fecha o circuito: configuração → nome do arquivo realmente servido."""
    settings_em_memoria.instalador_nome_template = "Cert {nome} [{token}].exe"

    # Um arquivo de verdade em vez de remendar Path.is_file: o patch global
    # afetaria toda leitura de arquivo do processo durante o teste.
    exe = tmp_path / "Instalar_Certificado.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(m, "INSTALADOR_AVULSO_EXE", exe)
    monkeypatch.setattr(m, "FileResponse", lambda **kw: {"filename": kw["filename"]})

    r = m.baixar_instalador(token="A" * 30, nome="ACME LTDA")
    assert r["filename"] == "Cert ACME LTDA [AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA].exe"


# ──────────────────────────────────────────────────────────────────────────
# 2. A rota parcial não pode apagar o resto
# ──────────────────────────────────────────────────────────────────────────

def test_salvar_config_do_instalador_preserva_o_smtp(
    client: TestClient, settings_em_memoria: PortalSettings
) -> None:
    """
    O motivo de existir uma rota própria.

    `PUT /api/settings` monta um PortalSettings inteiro a partir do corpo:
    mandar só os três campos do instalador zeraria o SMTP — sem erro nenhum, e
    ninguém notaria até o próximo alerta não sair.
    """
    r = client.put(
        "/api/cert-installer/configuracao",
        json={"instalador_nome_template": "{nome}-{token}.exe",
              "install_token_ttl_min": 15, "trilha_retencao_dias": 90},
        headers=_admin(),
    )
    assert r.status_code == 200, r.text

    assert settings_em_memoria.smtp_host == "smtp.exemplo.com"
    assert settings_em_memoria.smtp_password_encrypted == "cifrada"
    assert settings_em_memoria.smtp_alerts_enabled is True
    assert settings_em_memoria.source_folder == "F:/certs"
    assert settings_em_memoria.instalador_nome_template == "{nome}-{token}.exe"


def test_salvar_a_configuracao_geral_preserva_o_instalador(
    client: TestClient, settings_em_memoria: PortalSettings
) -> None:
    """O espelho do teste acima — a metade que faltava.

    O ponto 2 do cabeçalho deste arquivo previu a rota do INSTALADOR apagando o
    SMTP, e resolveu criando uma rota própria que lê antes de gravar. Ninguém
    olhou a direção contrária: os dois formulários de /configuracao mandam 11
    campos ao `PUT /api/settings` e nenhum deles manda os três do instalador.

    Enquanto ausente significava "apague", salvar as PASTAS devolvia o template
    de nome, o TTL do token e a retenção ao padrão. Sem erro, e o sintoma
    aparecia longe: o instalador voltava a gerar o nome padrão, e nada na tela
    de Configuração sugeria que tinha sido ela.
    """
    settings_em_memoria.instalador_nome_template = "{nome}-{token}.exe"
    settings_em_memoria.install_token_ttl_min = 15
    settings_em_memoria.trilha_retencao_dias = 90
    settings_em_memoria.alertas_marcos = "30,15,5"
    settings_em_memoria.alertas_destinatarios = "chefe@x.com"

    # Exatamente o corpo que o formulário de pastas envia hoje: sem uma linha
    # sequer sobre instalador ou alertas.
    r = client.put(
        "/api/settings",
        json={
            "source_folder": "F:/outra",
            "expired_folder": "F:/vencidos",
            "machine_id": "ANALISESRV",
            "smtp_host": "smtp.exemplo.com",
            "smtp_port": 587,
            "smtp_user": "alertas@exemplo.com",
            "smtp_password": None,
            "smtp_use_tls": True,
            "smtp_use_ssl": False,
            "smtp_from_email": "alertas@exemplo.com",
            "smtp_alerts_enabled": True,
        },
        headers=_admin(),
    )
    assert r.status_code == 200, r.text

    assert settings_em_memoria.source_folder == "F:/outra", "o que a tela mandou grava"
    assert settings_em_memoria.instalador_nome_template == "{nome}-{token}.exe"
    assert settings_em_memoria.install_token_ttl_min == 15
    assert settings_em_memoria.trilha_retencao_dias == 90
    assert settings_em_memoria.alertas_marcos == "30,15,5"
    assert settings_em_memoria.alertas_destinatarios == "chefe@x.com"


def test_campo_enviado_vazio_continua_limpando(
    client: TestClient, settings_em_memoria: PortalSettings
) -> None:
    """Ausente e vazio precisam continuar sendo coisas diferentes.

    Se preservar o omitido virasse "preservar o que for falsy", não haveria
    como voltar ao padrão pela tela — e "limpar o campo e salvar" é o gesto
    óbvio para isso.
    """
    settings_em_memoria.alertas_marcos = "30,15,5"

    r = client.put(
        "/api/settings",
        json={
            "source_folder": "F:/certs",
            "expired_folder": "F:/vencidos",
            "machine_id": "ANALISESRV",
            "smtp_host": "smtp.exemplo.com",
            "smtp_port": 587,
            "smtp_user": "alertas@exemplo.com",
            "smtp_password": None,
            "smtp_use_tls": True,
            "smtp_use_ssl": False,
            "smtp_from_email": "alertas@exemplo.com",
            "smtp_alerts_enabled": True,
            "alertas_marcos": "",
        },
        headers=_admin(),
    )
    assert r.status_code == 200, r.text
    assert settings_em_memoria.alertas_marcos == ""
    # E vazio volta a significar o padrão, não silêncio.
    assert r.json()["alertas_marcos_efetivos"] == [30, 15, 7, 1]


def test_rota_recusa_template_sem_token(
    client: TestClient, settings_em_memoria: PortalSettings
) -> None:
    r = client.put(
        "/api/cert-installer/configuracao",
        json={"instalador_nome_template": "Instalar {nome}.exe"},
        headers=_admin(),
    )
    assert r.status_code == 422, r.text
    assert "{token}" in r.json()["detail"]
    assert settings_em_memoria.instalador_nome_template == "", "nada pode ter sido gravado"


@pytest.mark.parametrize("ttl", [-5, 2000, 1441])
def test_rota_recusa_ttl_fora_dos_limites(
    client: TestClient, settings_em_memoria: PortalSettings, ttl: int
) -> None:
    r = client.put(
        "/api/cert-installer/configuracao",
        json={"install_token_ttl_min": ttl},
        headers=_admin(),
    )
    assert r.status_code == 422, r.text


def test_config_do_instalador_e_de_admin(
    client: TestClient, settings_em_memoria: PortalSettings
) -> None:
    for papel in ("user", "gestor"):
        h = {"Authorization": f"Bearer {auth.create_access_token({'sub': 'x@x.com', 'role': papel})}"}
        r = client.put("/api/cert-installer/configuracao", json={}, headers=h)
        assert r.status_code == 403


# ──────────────────────────────────────────────────────────────────────────
# 3. Zero = padrão, não desligado
# ──────────────────────────────────────────────────────────────────────────

def test_ttl_zero_cai_no_ambiente(settings_em_memoria: PortalSettings) -> None:
    settings_em_memoria.install_token_ttl_min = 0
    assert ci.ttl_do_token() == config.CERT_INSTALL_TOKEN_TTL_MIN


def test_ttl_configurado_vence_o_ambiente(settings_em_memoria: PortalSettings) -> None:
    settings_em_memoria.install_token_ttl_min = 42
    assert ci.ttl_do_token() == 42


def test_ttl_e_limitado_mesmo_vindo_do_banco(settings_em_memoria: PortalSettings) -> None:
    """
    Valor absurdo gravado por outro caminho (SQL direto, migration) não pode
    virar um token válido por um ano.
    """
    settings_em_memoria.install_token_ttl_min = 999999
    assert ci.ttl_do_token() == ci.TTL_TOKEN_MAX


def test_ttl_ilegivel_nao_impede_instalacao(monkeypatch: pytest.MonkeyPatch) -> None:
    """Um token com validade padrão é melhor que uma instalação recusada."""
    def _explode():
        raise RuntimeError("banco fora do ar")

    monkeypatch.setattr("app.settings_state.load_settings", _explode)
    assert ci.ttl_do_token() == config.CERT_INSTALL_TOKEN_TTL_MIN


# ──────────────────────────────────────────────────────────────────────────
# 4. Retenção do log (LGPD)
# ──────────────────────────────────────────────────────────────────────────

class _FakeDelete:
    def __init__(self, banco: "_FakeLog") -> None:
        self._b = banco
        self._corte: Optional[str] = None

    def lt(self, coluna: str, valor: str) -> "_FakeDelete":
        assert coluna == "created_at"
        self._corte = valor
        return self

    def execute(self):
        apagados = [r for r in self._b.linhas if r["created_at"] < self._corte]
        self._b.linhas = [r for r in self._b.linhas if r["created_at"] >= self._corte]
        return type("R", (), {"data": apagados})()


class _FakeLog:
    def __init__(self, linhas: List[Dict[str, Any]]) -> None:
        self.linhas = linhas

    def table(self, nome: str) -> "_FakeLog":
        assert nome == "install_log"
        return self

    def delete(self) -> _FakeDelete:
        return _FakeDelete(self)


@pytest.fixture
def log_com_historico(monkeypatch: pytest.MonkeyPatch) -> _FakeLog:
    agora = datetime.now(timezone.utc)
    fake = _FakeLog([
        {"id": "recente", "created_at": (agora - timedelta(days=5)).isoformat()},
        {"id": "medio", "created_at": (agora - timedelta(days=100)).isoformat()},
        {"id": "antigo", "created_at": (agora - timedelta(days=400)).isoformat()},
    ])
    monkeypatch.setattr(ci, "_supabase", lambda: fake)
    return fake


def test_retencao_zero_nao_apaga_nada(log_com_historico: _FakeLog) -> None:
    """
    Zero mantém o comportamento anterior de propósito: ligar o expurgo é decisão
    de quem responde pelos dados, não default de migration.
    """
    r = ci.expurgar_install_log(dias=0)
    assert r["executado"] is False
    assert len(log_com_historico.linhas) == 3


def test_expurgo_apaga_so_o_que_passou_do_prazo(log_com_historico: _FakeLog) -> None:
    r = ci.expurgar_install_log(dias=90)
    assert r["executado"] is True
    assert r["apagados"] == 2
    assert [x["id"] for x in log_com_historico.linhas] == ["recente"]


def test_expurgo_relata_falha_em_vez_de_levantar(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Roda pendurado no cron de alertas: levantar aqui derrubaria o envio, que é o
    motivo de a rota existir.
    """
    class _Quebrado:
        def table(self, _n):
            raise RuntimeError("banco fora do ar")

    monkeypatch.setattr(ci, "_supabase", lambda: _Quebrado())
    r = ci.expurgar_install_log(dias=30)
    assert r["executado"] is False
    assert "fora do ar" in r["motivo"]


def test_cron_reporta_o_expurgo_e_sobrevive_a_falha_dele(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    O expurgo é acessório; os alertas são o motivo da rota. Se o expurgo
    explodir, o cron ainda tem de enviar — e dizer que o expurgo falhou, em vez
    de o erro sumir.
    """
    monkeypatch.setenv("CRON_SECRET", "segredo-de-teste")
    monkeypatch.setattr(m, "trigger_all_alerts", lambda: {"enviados": 3})

    def _explode():
        raise RuntimeError("expurgo quebrado")

    monkeypatch.setattr(ci, "expurgar_install_log", _explode)

    r = client.get("/api/cron/alerts", headers={"Authorization": "Bearer segredo-de-teste"})
    assert r.status_code == 200, r.text
    assert r.json()["stats"] == {"enviados": 3}, "os alertas não podem ser afetados"
    assert r.json()["expurgo"]["executado"] is False


def test_gravacao_que_nao_chegou_ao_banco_nao_responde_salvo(
    client: TestClient, settings_em_memoria: PortalSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tela não pode dizer "salvo" sobre um valor que ela vai recarregar diferente.

    `save_settings` sempre escreveu o arquivo local e só REGISTRAVA a falha do
    Supabase. Mas `load_settings` prefere o Supabase: o valor ia para um arquivo
    que ninguém lê, e a rota devolvia 200.

    Encontrado ao aplicar esta própria funcionalidade — o Supabase recusou com
    `PGRST204` porque a migration ainda não tinha rodado, a tela anunciou
    "Configurações SMTP salvas com sucesso!" e a releitura devolveu vazio.
    """
    from app.settings_state import GravacaoNaoPersistida

    def _save_que_falha(s, **kwargs):
        if kwargs.get("exigir_supabase"):
            raise GravacaoNaoPersistida("PGRST204: coluna inexistente")
        return False

    monkeypatch.setattr(m, "save_settings", _save_que_falha)

    r = client.put(
        "/api/settings",
        json={
            "source_folder": "F:/nova",
            "expired_folder": "F:/vencidos",
            "machine_id": "ANALISESRV",
            "smtp_host": "smtp.exemplo.com",
            "smtp_port": 587,
            "smtp_user": "alertas@exemplo.com",
            "smtp_password": None,
            "smtp_use_tls": True,
            "smtp_use_ssl": False,
            "smtp_from_email": "alertas@exemplo.com",
            "smtp_alerts_enabled": True,
        },
        headers=_admin(),
    )

    assert r.status_code == 503, r.text
    assert "PGRST204" in r.text, "o motivo real precisa chegar a quem vai consertar"


def test_o_ingest_do_agente_nao_e_derrubado_por_falha_de_gravacao(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """O padrão continua sendo registrar e seguir — de propósito.

    Quem chama `save_settings` no meio de uma varredura de centenas de
    certificados não pode ter a varredura interrompida por causa da
    configuração. Só quem responde a uma tela pede `exigir_supabase`.
    """
    import app.settings_state as ss

    class _ClientQueFalha:
        def table(self, _nome):
            raise RuntimeError("banco fora do ar")

    monkeypatch.setattr(ss, "_supabase", lambda: _ClientQueFalha())
    monkeypatch.setattr(ss, "_save_file", lambda _s: None)

    s = PortalSettings(source_folder="F:/a", expired_folder="F:/b")
    assert ss.save_settings(s) is False, "relata, mas não levanta"

    with pytest.raises(ss.GravacaoNaoPersistida):
        ss.save_settings(s, exigir_supabase=True)
