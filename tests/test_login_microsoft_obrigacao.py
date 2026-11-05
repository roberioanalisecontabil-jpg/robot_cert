"""Domínios da Microsoft só entram por ela; a reserva é senha + app, só de admin.
Cada teste guarda uma regra cuja quebra reabriria a senha sozinha (ou o e-mail)
para conta de domínio, ou revelaria se a senha estava certa."""
from datetime import timedelta
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from app import auth, login_codigo, totp
from app.rotas.usuarios import ENTRE_PELA_MICROSOFT
from tests.test_recuperacao_de_senha import _Fake

DOM = "analisegroup.cnt.br"
SENHA = "senha-boa-123"
OP, ADM, ADM_SEM_APP, ADM_SEM_OID, GMAIL, SEM_LIGACAO = (
    f"op@{DOM}", f"adm@{DOM}", f"adm2@{DOM}", f"adm3@{DOM}", "ana@gmail.com", f"novo@{DOM}",
)
MSG_BANDEJA = "Entre uma vez no site pela Microsoft para liberar a bandeja."


def _u(id_: str, email: str, role: str = "user", **extra: Any) -> Dict[str, Any]:
    return {"id": id_, "email": email, "full_name": id_, "role": role, "ativo": True, "sessao_versao": 0,
            "password_hash": auth.get_password_hash(SENHA), **extra}


@pytest.fixture
def ligado(monkeypatch: pytest.MonkeyPatch) -> None:
    for nome, valor in (
        ("MICROSOFT_TENANT_ID", "t-1"), ("MICROSOFT_CLIENT_ID", "c-1"),
        ("MICROSOFT_CLIENT_SECRET", "s-1"), ("MICROSOFT_DOMINIOS", frozenset({DOM})),
        ("PORTAL_BASE_URL", "https://certificado.analisegroup.cnt.br"),
    ):
        monkeypatch.setattr(f"app.config.{nome}", valor, raising=False)


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    monkeypatch.setattr("app.config.LOGIN_EXIGE_CODIGO", True, raising=False)
    from app.smtp_service import encrypt_password

    segredo = totp.novo_segredo()
    app_ok = {"totp_cifrado": encrypt_password(segredo), "totp_ativado_em": "2026-10-10T00:00:00+00:00"}
    fake = _Fake({
        "users": [
            _u("u-op", OP, microsoft_oid="oid-op"),
            _u("u-adm", ADM, "admin", microsoft_oid="oid-adm", **app_ok),
            _u("u-adm2", ADM_SEM_APP, "admin", microsoft_oid="oid-adm2"),
            _u("u-adm3", ADM_SEM_OID, "admin", **app_ok),
            _u("u-gmail", GMAIL),
            _u("u-novo", SEM_LIGACAO),
        ],
        "user_activity": [],
    })
    fake.segredo = segredo
    monkeypatch.setattr("app.settings_state._banco", lambda: fake)
    import app.rotas.usuarios as m

    monkeypatch.setattr(m, "_enviar_codigo_de_login",
                        lambda conta, codigo: fake.enviados.append({"para": conta["email"], "codigo": codigo}))
    return fake


def _login(client: TestClient, email: str, senha: str = SENHA):
    return client.post("/api/login", json={"email": email, "password": senha})


def _eventos(banco: _Fake, evento: str):
    return [e for e in banco.tabelas["user_activity"] if e["evento"] == evento]


def test_dominio_operador_senha_certa_403(client: TestClient, banco: _Fake, ligado: None) -> None:
    r = _login(client, OP)
    assert r.status_code == 403 and r.json()["detail"] == ENTRE_PELA_MICROSOFT
    assert not banco.enviados and not client.cookies.get("cg_sessao")


def test_dominio_senha_errada_403_igual(client: TestClient, banco: _Fake, ligado: None) -> None:
    certa = _login(client, OP)
    errada = _login(client, OP, "errada")
    inexistente = _login(client, f"ninguem@{DOM}")
    assert errada.status_code == inexistente.status_code == certa.status_code == 403
    assert errada.json() == inexistente.json() == certa.json() == {"detail": ENTRE_PELA_MICROSOFT}
    # A contabilidade de falhas segue: conta existente com senha errada audita.
    assert _eventos(banco, "login_negado")


def test_dominio_sem_configuracao_entra_como_hoje(client: TestClient, banco: _Fake) -> None:
    r = _login(client, OP)
    assert r.status_code == 200 and r.json()["etapa"] == "codigo"
    assert banco.enviados


def test_admin_reserva_pede_so_app_sem_email(client: TestClient, banco: _Fake, ligado: None) -> None:
    r = _login(client, ADM)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["etapa"] == "codigo" and corpo["app_autenticador"] is True and corpo["email"] is None
    assert not banco.enviados


def test_admin_reserva_metodo_email_recusado(client: TestClient, banco: _Fake, ligado: None) -> None:
    desafio = _login(client, ADM).json()["desafio"]
    r = client.post("/api/login/codigo", json={"desafio": desafio, "codigo": "123456", "metodo": "email"})
    assert r.status_code == 400 and r.json()["detail"] == "Código inválido ou expirado."
    assert not client.cookies.get("cg_sessao")


def test_admin_reserva_ignora_navegador_lembrado(client: TestClient, banco: _Fake, ligado: None) -> None:
    client.cookies.set(login_codigo.COOKIE_CONFIA,
                       auth.criar_token_de(auth.AUD_NAVEGADOR_CONFIAVEL, "u-adm", timedelta(days=7)))
    r = _login(client, ADM)
    assert r.status_code == 200 and r.json().get("etapa") == "codigo" and r.json()["app_autenticador"] is True


@pytest.mark.parametrize("email", [ADM_SEM_APP, ADM_SEM_OID])
def test_admin_sem_app_ou_sem_oid_403(client: TestClient, banco: _Fake, ligado: None, email: str) -> None:
    r = _login(client, email)
    assert r.status_code == 403 and r.json()["detail"] == ENTRE_PELA_MICROSOFT


def test_admin_reserva_audita_senha_e_app(client: TestClient, banco: _Fake, ligado: None) -> None:
    desafio = _login(client, ADM).json()["desafio"]
    codigo = totp.codigo(banco.segredo, totp.passo_atual())
    r = client.post("/api/login/codigo",
                    json={"desafio": desafio, "codigo": codigo, "metodo": "app", "lembrar": True})
    assert r.status_code == 200, r.text
    assert _eventos(banco, "login")[-1]["contexto"]["metodo"] == "senha_e_app"
    assert not client.cookies.get(login_codigo.COOKIE_CONFIA), "lembrar é ignorado na reserva"


def test_gmail_continua_com_codigo_por_email(client: TestClient, banco: _Fake, ligado: None) -> None:
    r = _login(client, GMAIL)
    assert r.status_code == 200 and r.json()["etapa"] == "codigo"
    assert banco.enviados[-1]["para"] == GMAIL


# ── Bandeja ──────────────────────────────────────────────────────────────

@pytest.fixture
def entrar_falso(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.rotas.agente.computadores.entrar", lambda *a, **k: ("seg-1", {"autorizacao": "pendente"}))


def _registrar(client: TestClient, email: str):
    return client.post("/api/agent/dispositivos/registrar",
                       json={"email": email, "password": SENHA, "machine_id": "aa:aa:aa:aa:aa:01"})


def test_bandeja_registrar_com_senha_de_dominio_ligada_continua(
    client: TestClient, banco: _Fake, ligado: None, entrar_falso: None,
) -> None:
    r = _registrar(client, OP)
    assert r.status_code == 200 and r.json()["segredo"] == "seg-1"


def test_bandeja_registrar_dominio_nunca_ligado_recusa(
    client: TestClient, banco: _Fake, ligado: None, entrar_falso: None,
) -> None:
    r = _registrar(client, SEM_LIGACAO)
    assert r.status_code == 403 and r.json()["detail"] == MSG_BANDEJA
    ev = _eventos(banco, "login_negado")
    assert ev and ev[-1]["contexto"]["motivo"] == "microsoft_nao_ligada"


def test_bandeja_gmail_continua(client: TestClient, banco: _Fake, ligado: None, entrar_falso: None) -> None:
    assert _registrar(client, GMAIL).status_code == 200


def test_bandeja_sem_configuracao_como_hoje(client: TestClient, banco: _Fake, entrar_falso: None) -> None:
    assert _registrar(client, SEM_LIGACAO).status_code == 200
