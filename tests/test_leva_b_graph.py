"""
Leva B de "feche o que falta" (03/10/2026): envio de e-mail pelo Microsoft 365
(Graph), ao lado do SMTP.

  app/graph_mail.py   client credentials + POST /users/{caixa}/sendMail,
                      erros por classe, token cacheado, Reply-To.
  app/correio.py      um ponto de saída: a assinatura de `send_smtp_email` fica
                      (seis chamadores e seus dublês), a forma vem da config.
  Configuração        campos do Graph no PUT/GET; o segredo nunca volta.
  Sino                o administrador é avisado 30 dias antes de o segredo
                      vencer (tipo "sistema", com destino).

Escritos antes da implementação.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.rotas import usuarios
from app import correio, graph_mail, notification_service as ns, smtp_service
from app.settings_state import PortalSettings
from app.smtp_service import encrypt_password
from tests.test_seguranca_lote1 import _Fake
from tests.test_seguranca_lote4 import ADMIN, FISCAL_OP, _h  # noqa: F401
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401

RAIZ = Path(__file__).resolve().parents[1]
TENANT = "11111111-2222-3333-4444-555555555555"
APP = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


@pytest.fixture
def banco(banco_base: _Fake) -> _Fake:
    banco_base.tabelas["carteira_excecao"] = []
    return banco_base


@pytest.fixture(autouse=True)
def _sem_cache_de_token():
    graph_mail.esquecer_tokens()
    yield
    graph_mail.esquecer_tokens()


@pytest.fixture(autouse=True)
def _sem_arquivo_local(monkeypatch: pytest.MonkeyPatch):
    """`save_settings` também grava data/portal_settings.json, e `load_settings`
    cai nele quando o banco falso não tem linha: um teste vazaria no outro (e
    no ambiente de quem roda a suíte)."""
    import app.settings_state as ss
    monkeypatch.setattr(ss, "_save_file", lambda _s: None)
    monkeypatch.setattr(ss, "_load_file", lambda: None)


def _settings_graph(**extra: Any) -> PortalSettings:
    base = dict(
        source_folder="", expired_folder="", machine_id="default",
        email_transporte="graph", graph_tenant_id=TENANT, graph_client_id=APP,
        graph_client_secret_encrypted=encrypt_password("segredo-do-app"),
        graph_remetente="noreply@empresa.com.br", graph_reply_to="certificados@empresa.com.br",
        graph_secret_validade="", smtp_alerts_enabled=True,
    )
    base.update(extra)
    return PortalSettings(**base)


class _Microsoft:
    """login.microsoftonline.com + graph.microsoft.com de mentira."""

    def __init__(self, token_status: int = 200, send_status: int = 202, cai: bool = False) -> None:
        self.token_status, self.send_status, self.cai = token_status, send_status, cai
        self.pedidos: List[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.pedidos.append(req)
        if self.cai:
            raise httpx.ConnectError("sem rede", request=req)
        if req.url.host == "login.microsoftonline.com":
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_client", "error_description": "AADSTS7000215"})
            return httpx.Response(200, json={"access_token": "tok-123", "expires_in": 3599})
        if self.send_status == 202:
            return httpx.Response(202)
        return httpx.Response(self.send_status, json={"error": {"code": "ErrorAccessDenied", "message": "Access is denied"}})

    def cliente(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


# ──────────────────────────────────────────────────────────────────────────
# 1. graph_mail
# ──────────────────────────────────────────────────────────────────────────

def test_envia_pela_caixa_com_reply_to_e_token_de_aplicativo() -> None:
    ms = _Microsoft()
    with ms.cliente() as c:
        graph_mail.enviar(
            tenant_id=TENANT, client_id=APP, segredo_enc=encrypt_password("segredo-do-app"),
            remetente="noreply@empresa.com.br", reply_to="certificados@empresa.com.br",
            to_email="ana@x.com", subject="Teste", html_content="<p>oi</p>", cliente=c,
        )
    assert len(ms.pedidos) == 2
    token_req, send_req = ms.pedidos
    assert token_req.url.path == f"/{TENANT}/oauth2/v2.0/token"
    corpo = dict(x.split("=") for x in token_req.content.decode().split("&"))
    assert corpo["grant_type"] == "client_credentials" and corpo["client_id"] == APP
    assert "segredo-do-app" in httpx.QueryParams(token_req.content.decode()).get("client_secret")
    assert send_req.url.path == "/v1.0/users/noreply@empresa.com.br/sendMail"
    assert send_req.headers["Authorization"] == "Bearer tok-123"
    msg = json.loads(send_req.content)
    assert msg["saveToSentItems"] is False
    assert msg["message"]["toRecipients"][0]["emailAddress"]["address"] == "ana@x.com"
    assert msg["message"]["replyTo"][0]["emailAddress"]["address"] == "certificados@empresa.com.br"
    assert msg["message"]["body"]["contentType"] == "HTML"


def test_token_e_reaproveitado_entre_envios() -> None:
    ms = _Microsoft()
    with ms.cliente() as c:
        for _ in range(2):
            graph_mail.enviar(tenant_id=TENANT, client_id=APP, segredo_enc=encrypt_password("s"),
                              remetente="noreply@empresa.com.br", reply_to="", to_email="a@x.com",
                              subject="t", html_content="<p/>", cliente=c)
    assert [p.url.host for p in ms.pedidos] == ["login.microsoftonline.com", "graph.microsoft.com", "graph.microsoft.com"]


def test_credencial_recusada_e_erro_de_autenticacao() -> None:
    ms = _Microsoft(token_status=401)
    with ms.cliente() as c, pytest.raises(graph_mail.ErroAutenticacaoGraph):
        graph_mail.enviar(tenant_id=TENANT, client_id=APP, segredo_enc=encrypt_password("s"),
                          remetente="noreply@empresa.com.br", reply_to="", to_email="a@x.com",
                          subject="t", html_content="<p/>", cliente=c)


def test_sem_permissao_e_erro_de_permissao() -> None:
    ms = _Microsoft(send_status=403)
    with ms.cliente() as c, pytest.raises(graph_mail.ErroPermissaoGraph):
        graph_mail.enviar(tenant_id=TENANT, client_id=APP, segredo_enc=encrypt_password("s"),
                          remetente="noreply@empresa.com.br", reply_to="", to_email="a@x.com",
                          subject="t", html_content="<p/>", cliente=c)


def test_sem_rede_e_erro_de_conexao() -> None:
    ms = _Microsoft(cai=True)
    with ms.cliente() as c, pytest.raises(graph_mail.ErroConexaoGraph):
        graph_mail.enviar(tenant_id=TENANT, client_id=APP, segredo_enc=encrypt_password("s"),
                          remetente="noreply@empresa.com.br", reply_to="", to_email="a@x.com",
                          subject="t", html_content="<p/>", cliente=c)


def test_sem_segredo_nao_tenta() -> None:
    ms = _Microsoft()
    with ms.cliente() as c, pytest.raises(graph_mail.ErroAutenticacaoGraph):
        graph_mail.enviar(tenant_id=TENANT, client_id=APP, segredo_enc="", remetente="noreply@empresa.com.br",
                          reply_to="", to_email="a@x.com", subject="t", html_content="<p/>", cliente=c)
    assert ms.pedidos == []


def test_validacao_dos_campos() -> None:
    graph_mail.validar_config(TENANT, APP, "noreply@empresa.com.br", "")
    graph_mail.validar_config("empresa.onmicrosoft.com", APP, "noreply@empresa.com.br", "x@empresa.com.br")
    with pytest.raises(ValueError, match="tenant"):
        graph_mail.validar_config("nao-e-guid", APP, "noreply@empresa.com.br")
    with pytest.raises(ValueError, match="aplicativo"):
        graph_mail.validar_config(TENANT, "123", "noreply@empresa.com.br")
    with pytest.raises(ValueError, match="Caixa"):
        graph_mail.validar_config(TENANT, APP, "sem-arroba")
    with pytest.raises(ValueError, match="Responder"):
        graph_mail.validar_config(TENANT, APP, "noreply@empresa.com.br", "sem-arroba")


def test_dias_para_vencer_segredo() -> None:
    hoje = date(2026, 10, 3)
    assert graph_mail.dias_para_vencer_segredo("2026-11-02", hoje) == 30
    assert graph_mail.dias_para_vencer_segredo("2026-10-01", hoje) == -2
    assert graph_mail.dias_para_vencer_segredo("", hoje) is None
    assert graph_mail.dias_para_vencer_segredo("03/10/2026", hoje) is None


# ──────────────────────────────────────────────────────────────────────────
# 2. correio: a forma vem da configuração; a assinatura fica
# ──────────────────────────────────────────────────────────────────────────

def test_sem_configurar_nada_continua_smtp() -> None:
    s = PortalSettings(source_folder="", expired_folder="", machine_id="default", smtp_host="smtp.x")
    assert correio.transporte(s) == "smtp" and correio.configurado(s) is True
    assert correio.configurado(PortalSettings(source_folder="", expired_folder="", machine_id="d")) is False


def test_graph_configurado_exige_os_quatro_campos() -> None:
    assert correio.configurado(_settings_graph()) is True
    assert correio.configurado(_settings_graph(graph_client_secret_encrypted="")) is False
    assert correio.configurado(_settings_graph(graph_remetente="")) is False
    assert correio.remetente_efetivo(_settings_graph()) == "noreply@empresa.com.br"


def test_despachante_manda_pelo_smtp_quando_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas: List[Dict[str, Any]] = []
    monkeypatch.setattr(smtp_service, "send_smtp_email", lambda **kw: chamadas.append(kw))
    monkeypatch.setattr(graph_mail, "enviar", lambda **kw: (_ for _ in ()).throw(AssertionError("não era para usar o Graph")))
    s = PortalSettings(source_folder="", expired_folder="", machine_id="d", smtp_host="smtp.x", smtp_user="u")
    correio.send_smtp_email(host="smtp.x", port=587, user="u", password_enc="", use_tls=True, use_ssl=False,
                            from_email="", to_email="a@x.com", subject="t", html_content="<p/>", settings=s)
    assert chamadas and chamadas[0]["to_email"] == "a@x.com" and "settings" not in chamadas[0]


def test_despachante_manda_pelo_graph_quando_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas: List[Dict[str, Any]] = []
    monkeypatch.setattr(graph_mail, "enviar", lambda **kw: chamadas.append(kw))
    monkeypatch.setattr(smtp_service, "send_smtp_email", lambda **kw: (_ for _ in ()).throw(AssertionError("não era para usar SMTP")))
    correio.send_smtp_email(host="", port=587, user="", password_enc="", use_tls=True, use_ssl=False,
                            from_email="", to_email="a@x.com", subject="t", html_content="<p/>", settings=_settings_graph())
    assert chamadas[0]["remetente"] == "noreply@empresa.com.br"
    assert chamadas[0]["reply_to"] == "certificados@empresa.com.br"
    assert chamadas[0]["to_email"] == "a@x.com"


def test_os_chamadores_passam_pelo_despachante() -> None:
    """Nenhum módulo importa `send_smtp_email` direto do smtp_service, senão o
    Graph não vale para aquele e-mail."""
    for nome in ("alert_state", "novos_certificados", "entrada"):
        fonte = (RAIZ / "app" / f"{nome}.py").read_text(encoding="utf-8")
        assert "from app.correio import send_smtp_email" in fonte, nome
        assert "from app.smtp_service import send_smtp_email" not in fonte, nome
        assert "settings.smtp_host" not in fonte.replace("host=settings.smtp_host", ""), nome
    from tests import fonte_do_portal

    assert "smtp_service.send_smtp_email(" not in fonte_do_portal.texto()


# ──────────────────────────────────────────────────────────────────────────
# 3. Configuração: PUT/GET
# ──────────────────────────────────────────────────────────────────────────

def _corpo(**extra: Any) -> dict:
    return {**m.SettingsBody().model_dump(), **extra}


def test_put_graph_grava_cifrado_e_get_nunca_devolve_o_segredo(client: TestClient, banco: _Fake) -> None:
    r = client.put("/api/settings", json=_corpo(
        email_transporte="graph", graph_tenant_id=TENANT, graph_client_id=APP, graph_client_secret="segredo-do-app",
        graph_remetente="noreply@empresa.com.br", graph_reply_to="certificados@empresa.com.br", graph_secret_validade="2028-10-01",
    ), headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["email_transporte"] == "graph" and d["graph_client_secret_set"] is True and d["envio_configurado"] is True
    assert "segredo-do-app" not in r.text
    linha = banco.tabelas["portal_settings"][0]
    assert linha["graph_client_secret_encrypted"] and linha["graph_client_secret_encrypted"] != "segredo-do-app"
    assert smtp_service.decrypt_password(linha["graph_client_secret_encrypted"]) == "segredo-do-app"
    assert d["graph_secret_dias_restantes"] > 300

    # Segredo ausente (None) preserva; vazio também preserva, como a senha SMTP.
    r = client.put("/api/settings", json=_corpo(email_transporte="graph", graph_tenant_id=TENANT, graph_client_id=APP,
                                               graph_remetente="noreply@empresa.com.br"), headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert smtp_service.decrypt_password(banco.tabelas["portal_settings"][0]["graph_client_secret_encrypted"]) == "segredo-do-app"
    g = client.get("/api/settings", headers=_h(*ADMIN)).json()
    assert g["graph_client_secret_set"] is True and "graph_client_secret_encrypted" not in g


def test_put_graph_sem_campos_e_422(client: TestClient, banco: _Fake) -> None:
    r = client.put("/api/settings", json=_corpo(email_transporte="graph"), headers=_h(*ADMIN))
    assert r.status_code == 422 and "tenant" in r.json()["detail"].lower()
    r = client.put("/api/settings", json=_corpo(email_transporte="graph", graph_tenant_id=TENANT, graph_client_id=APP,
                                               graph_remetente="noreply@empresa.com.br"), headers=_h(*ADMIN))
    assert r.status_code == 422 and "segredo" in r.json()["detail"].lower()
    r = client.put("/api/settings", json=_corpo(email_transporte="fax"), headers=_h(*ADMIN))
    assert r.status_code == 422
    r = client.put("/api/settings", json=_corpo(graph_secret_validade="03/10/2028"), headers=_h(*ADMIN))
    assert r.status_code == 422 and "AAAA-MM-DD" in r.json()["detail"]


def test_put_smtp_nao_exige_graph(client: TestClient, banco: _Fake) -> None:
    r = client.put("/api/settings", json=_corpo(smtp_host="smtp.x"), headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert r.json()["email_transporte"] == "smtp"


# ──────────────────────────────────────────────────────────────────────────
# 4. Teste de envio e código de senha pela forma configurada
# ──────────────────────────────────────────────────────────────────────────

def test_rota_de_teste_usa_o_graph(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas: List[Dict[str, Any]] = []
    monkeypatch.setattr(graph_mail, "enviar", lambda **kw: chamadas.append(kw))
    with patch("app.main.load_settings", _settings_graph):
        r = client.post("/api/settings/smtp/test", json={"target_email": "destino@x.com"}, headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert chamadas[0]["to_email"] == "destino@x.com" and "Microsoft 365" in chamadas[0]["html_content"]


def test_rota_de_teste_traduz_os_erros_do_graph(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def _nega(**kw):
        raise graph_mail.ErroPermissaoGraph("403")
    monkeypatch.setattr(graph_mail, "enviar", _nega)
    with patch("app.main.load_settings", _settings_graph):
        r = client.post("/api/settings/smtp/test", json={"target_email": "destino@x.com"}, headers=_h(*ADMIN))
    assert r.status_code == 400 and "permissão" in r.json()["detail"]

    with patch("app.main.load_settings", lambda: _settings_graph(graph_remetente="")):
        r = client.post("/api/settings/smtp/test", json={"target_email": "destino@x.com"}, headers=_h(*ADMIN))
    assert r.status_code == 400 and "Microsoft 365 não configurado" in r.json()["detail"]


def test_codigo_de_senha_sai_pelo_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas: List[Dict[str, Any]] = []
    monkeypatch.setattr(graph_mail, "enviar", lambda **kw: chamadas.append(kw))
    monkeypatch.setattr(usuarios, "load_settings", _settings_graph)
    usuarios._enviar_codigo_por_email({"email": "ana@x.com", "full_name": "Ana"}, "123456")
    assert chamadas[0]["to_email"] == "ana@x.com" and "123456" in chamadas[0]["html_content"]


# ──────────────────────────────────────────────────────────────────────────
# 5. Sino: o segredo vencendo
# ──────────────────────────────────────────────────────────────────────────

def test_sino_avisa_o_administrador_30_dias_antes() -> None:
    agora = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
    em_20 = (agora.date() + timedelta(days=20)).isoformat()
    avisos = ns.avisos_do_portal(_settings_graph(graph_secret_validade=em_20), agora)
    assert len(avisos) == 1
    a = avisos[0]
    assert a["tipo"] == "sistema" and a["dias_restantes"] == 20 and a["acionavel"] is True
    assert a["href"] == "/configuracao?aba=alertas" and "20 dia" in a["mensagem"]
    assert a["chave"] == f"sistema|graph-secret|{em_20}"


def test_sino_cala_longe_do_vencimento_ou_sem_graph() -> None:
    agora = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
    em_90 = (agora.date() + timedelta(days=90)).isoformat()
    assert ns.avisos_do_portal(_settings_graph(graph_secret_validade=em_90), agora) == []
    assert ns.avisos_do_portal(_settings_graph(graph_secret_validade=""), agora) == []
    em_5 = (agora.date() + timedelta(days=5)).isoformat()
    assert ns.avisos_do_portal(_settings_graph(email_transporte="smtp", graph_secret_validade=em_5), agora) == []


def test_sino_segue_avisando_depois_de_vencer() -> None:
    agora = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
    ha_3 = (agora.date() - timedelta(days=3)).isoformat()
    a = ns.avisos_do_portal(_settings_graph(graph_secret_validade=ha_3), agora)[0]
    assert a["dias_restantes"] == -3 and "venceu" in a["mensagem"]


def test_aviso_do_portal_entra_na_lista_do_admin_e_nao_na_do_operador(monkeypatch: pytest.MonkeyPatch) -> None:
    em_10 = (datetime.now(timezone.utc).date() + timedelta(days=10)).isoformat()
    monkeypatch.setattr(ns, "load_settings", lambda: _settings_graph(graph_secret_validade=em_10))
    monkeypatch.setattr(ns, "get_latest_snapshot", lambda: {"items": []})
    monkeypatch.setattr(ns, "chaves_registradas_recentemente", lambda _d: {})
    monkeypatch.setattr(m, "_list_certificados_payload", lambda *_a, **_k: {"itens": []})
    monkeypatch.setattr(ns, "load_colaborador_selecao", lambda *_a, **_k: [])
    monkeypatch.setattr(ns, "documentos_ao_alcance", lambda *_a, **_k: set())
    admin = ns.get_active_alerts("admin@x.com", "admin", "u-adm")
    assert [a["tipo"] for a in admin] == ["sistema"]
    assert ns.get_active_alerts("fis@x.com", "user", "u-fis") == []


def test_sino_na_tela_tem_secao_portal_e_respeita_o_destino() -> None:
    ui = (RAIZ / "static" / "ui-common.js").read_text(encoding="utf-8")
    assert "if (it.href) return String(it.href);" in ui
    assert '_criarSecaoNotificacoes("Portal"' in ui
    assert 'sistema: "notif-expiring"' in ui


def test_configuracao_tem_a_forma_de_envio_e_o_bloco_do_graph() -> None:
    html = (RAIZ / "templates" / "configuracao.html").read_text(encoding="utf-8")
    assert 'id="sel-email-transporte"' in html and 'value="graph"' in html
    for campo in ("inp-graph-tenant", "inp-graph-client", "inp-graph-secret", "inp-graph-validade", "inp-graph-remetente", "inp-graph-reply-to"):
        assert f'id="{campo}"' in html, campo
    assert html.count("...corpoGraph(),") == 3, "os três PUT da tela mandam o bloco do Graph"
    assert "docs/envio-microsoft-365.md" in html
    assert (RAIZ / "docs" / "envio-microsoft-365.md").is_file()
    assert (RAIZ / "supabase" / "migrations" / "20261003120000_envio_microsoft_graph.sql").is_file()
