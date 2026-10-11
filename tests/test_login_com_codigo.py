"""
Login em dois passos (decisão do usuário, 10/10/2026 — pré-requisito para abrir
o portal na internet): senha, depois um código por e-mail (15 minutos, 3 erros
e queima) ou do app autenticador; o navegador fica lembrado por 7 dias.

Cada teste guarda uma regra cuja quebra não daria sintoma: o portal
continuaria "funcionando", só que voltando a abrir com a senha sozinha.
"""

from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from app import auth, login_codigo, totp
from tests.test_recuperacao_de_senha import EMAIL, TABELA, _Fake

SENHA = "antiga-123"


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    monkeypatch.setattr("app.config.LOGIN_EXIGE_CODIGO", True, raising=False)
    fake = _Fake({
        "users": [
            {"id": "u-ana", "email": EMAIL, "full_name": "Ana", "role": "user", "ativo": True,
             "sessao_versao": 0, "password_hash": auth.get_password_hash(SENHA)},
        ],
        TABELA: [],
        "user_activity": [],
    })
    monkeypatch.setattr("app.settings_state._banco", lambda: fake)
    import app.rotas.usuarios as m

    def _fake_envio(conta: Dict[str, Any], codigo: str) -> None:
        fake.enviados.append({"para": conta["email"], "codigo": codigo})

    monkeypatch.setattr(m, "_enviar_codigo_de_login", _fake_envio)
    return fake


def _senha(client: TestClient, senha: str = SENHA):
    return client.post("/api/login", json={"email": EMAIL, "password": senha})


def _codigo(client: TestClient, desafio: str, codigo: str, **extra):
    return client.post("/api/login/codigo", json={"desafio": desafio, "codigo": codigo, **extra})


def _ana(banco: _Fake) -> Dict[str, Any]:
    return banco.tabelas["users"][0]


def _ativar_app(banco: _Fake) -> str:
    from app.smtp_service import encrypt_password

    segredo = totp.novo_segredo()
    _ana(banco).update({"totp_cifrado": encrypt_password(segredo), "totp_ativado_em": "2026-10-10T00:00:00+00:00"})
    return segredo


# ── 1. A senha sozinha não abre ──────────────────────────────────────────

def test_senha_certa_so_pede_o_codigo(client: TestClient, banco: _Fake) -> None:
    r = _senha(client)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["etapa"] == "codigo" and corpo["desafio"]
    assert "role" not in corpo
    assert "cg_sessao" not in r.cookies and not client.cookies.get("cg_sessao")
    assert banco.enviados and banco.enviados[-1]["para"] == EMAIL
    assert corpo["email"] != EMAIL and corpo["email"].endswith("@x.com")
    assert client.get("/api/users/me/app-autenticador").status_code == 401


def test_senha_errada_nao_manda_codigo(client: TestClient, banco: _Fake) -> None:
    assert _senha(client, "errada").status_code == 401
    assert not banco.enviados and not banco.tabelas[TABELA]


def test_codigo_do_email_abre_a_sessao(client: TestClient, banco: _Fake) -> None:
    desafio = _senha(client).json()["desafio"]
    r = _codigo(client, desafio, banco.enviados[-1]["codigo"])
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "user"
    assert client.get("/api/users/me/app-autenticador").status_code == 200


def test_codigo_vale_uma_vez(client: TestClient, banco: _Fake) -> None:
    desafio = _senha(client).json()["desafio"]
    codigo = banco.enviados[-1]["codigo"]
    assert _codigo(client, desafio, codigo).status_code == 200
    client.cookies.clear()
    assert _codigo(client, desafio, codigo).status_code == 400


def test_tres_erros_queimam_o_codigo(client: TestClient, banco: _Fake) -> None:
    desafio = _senha(client).json()["desafio"]
    certo = banco.enviados[-1]["codigo"]
    errado = "000000" if certo != "000000" else "111111"
    for _ in range(3):
        assert _codigo(client, desafio, errado).status_code == 400
    assert _codigo(client, desafio, certo).status_code == 400, "o 4º palpite, mesmo certo, não pode entrar"


def test_desafio_de_outra_conta_ou_forjado_nao_serve(client: TestClient, banco: _Fake) -> None:
    _senha(client)
    codigo = banco.enviados[-1]["codigo"]
    assert _codigo(client, "nao-e-um-token", codigo).status_code == 400
    # Token de sessão no lugar do desafio: o `aud` distinto barra.
    sessao = auth.create_access_token({"sub": "u-ana", "role": "user", "sv": 0})
    assert _codigo(client, sessao, codigo).status_code == 400


def test_sair_invalida_o_desafio_pendente(client: TestClient, banco: _Fake) -> None:
    desafio = _senha(client).json()["desafio"]
    _ana(banco)["sessao_versao"] = 1  # "Sair" em outro navegador
    assert _codigo(client, desafio, banco.enviados[-1]["codigo"]).status_code == 400


def test_codigo_de_login_nao_redefine_senha(client: TestClient, banco: _Fake) -> None:
    _senha(client)
    codigo = banco.enviados[-1]["codigo"]
    r = client.post("/api/senha/redefinir", json={"email": EMAIL, "codigo": codigo, "password": "outra-senha-99"})
    assert r.status_code == 400
    assert auth.verify_password(SENHA, _ana(banco)["password_hash"])


# ── 2. Navegador lembrado ────────────────────────────────────────────────

def test_lembrar_dispensa_o_codigo_na_proxima(client: TestClient, banco: _Fake) -> None:
    desafio = _senha(client).json()["desafio"]
    assert _codigo(client, desafio, banco.enviados[-1]["codigo"], lembrar=True).status_code == 200
    assert client.cookies.get(login_codigo.COOKIE_CONFIA)
    enviados = len(banco.enviados)
    r = _senha(client)
    assert r.status_code == 200 and r.json().get("role") == "user", r.text
    assert len(banco.enviados) == enviados


def test_sem_lembrar_pede_de_novo(client: TestClient, banco: _Fake) -> None:
    desafio = _senha(client).json()["desafio"]
    _codigo(client, desafio, banco.enviados[-1]["codigo"])
    assert not client.cookies.get(login_codigo.COOKIE_CONFIA)
    assert _senha(client).json()["etapa"] == "codigo"


def test_confianca_cai_com_troca_de_senha(client: TestClient, banco: _Fake) -> None:
    desafio = _senha(client).json()["desafio"]
    _codigo(client, desafio, banco.enviados[-1]["codigo"], lembrar=True)
    _ana(banco)["senha_alterada_em"] = "2999-01-01T00:00:00+00:00"
    assert _senha(client).json()["etapa"] == "codigo"


def test_confianca_sobrevive_ao_sair(client: TestClient, banco: _Fake) -> None:
    """11/10/2026: o lembrete morria com o Sair (que sobe a versão da sessão
    e apagava o cookie) — e todo caminho de volta ao login passa pelo Sair."""
    desafio = _senha(client).json()["desafio"]
    _codigo(client, desafio, banco.enviados[-1]["codigo"], lembrar=True)
    r = client.post("/api/logout", headers={"X-CSRF-Token": client.cookies.get("cg_csrf") or ""})
    assert r.status_code in (200, 204), r.text
    assert _ana(banco)["sessao_versao"] == 1
    assert client.cookies.get(login_codigo.COOKIE_CONFIA)
    r = _senha(client)
    assert r.json().get("role") == "user", r.text


def test_confianca_e_da_conta_nao_do_navegador(client: TestClient, banco: _Fake) -> None:
    banco.tabelas["users"].append({"id": "u-bia", "email": "bia@x.com", "full_name": "Bia", "role": "user",
                                   "ativo": True, "sessao_versao": 0,
                                   "password_hash": auth.get_password_hash(SENHA)})
    desafio = _senha(client).json()["desafio"]
    _codigo(client, desafio, banco.enviados[-1]["codigo"], lembrar=True)
    r = client.post("/api/login", json={"email": "bia@x.com", "password": SENHA})
    assert r.json()["etapa"] == "codigo"


def test_chave_de_emergencia_desliga_o_codigo(client: TestClient, banco: _Fake,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.config.LOGIN_EXIGE_CODIGO", False, raising=False)
    assert _senha(client).json().get("role") == "user"


# ── 3. App autenticador ──────────────────────────────────────────────────

def test_codigo_do_app_abre_e_nao_repete(client: TestClient, banco: _Fake) -> None:
    segredo = _ativar_app(banco)
    corpo = _senha(client).json()
    assert corpo["app_autenticador"] is True
    agora = totp.codigo(segredo, totp.passo_atual())
    assert _codigo(client, corpo["desafio"], agora, metodo="app").status_code == 200
    client.cookies.clear()
    desafio = _senha(client).json()["desafio"]
    assert _codigo(client, desafio, agora, metodo="app").status_code == 400, "replay do mesmo código"


def test_app_inativo_nao_serve(client: TestClient, banco: _Fake) -> None:
    segredo = _ativar_app(banco)
    _ana(banco)["totp_ativado_em"] = None
    desafio = _senha(client).json()["desafio"]
    assert _codigo(client, desafio, totp.codigo(segredo, totp.passo_atual()), metodo="app").status_code == 400


def test_teto_por_conta_no_codigo(client: TestClient, banco: _Fake) -> None:
    _ativar_app(banco)
    desafio = _senha(client).json()["desafio"]
    for i in range(10):
        r = client.post("/api/login/codigo", json={"desafio": desafio, "codigo": "000000", "metodo": "app"},
                        headers={"X-Forwarded-For": f"10.0.0.{i}"})
        assert r.status_code == 400
    r = client.post("/api/login/codigo", json={"desafio": desafio, "codigo": "000000", "metodo": "app"},
                    headers={"X-Forwarded-For": "10.0.1.1"})
    assert r.status_code == 429


def test_email_esgotado_ainda_entra_pelo_app(client: TestClient, banco: _Fake,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    segredo = _ativar_app(banco)
    import app.senha_reset as sr

    def _esgotado(*_a, **_k):
        raise sr.LimiteDePedidos("u-ana")

    monkeypatch.setattr(sr, "criar_codigo", _esgotado)
    corpo = _senha(client).json()
    assert corpo["etapa"] == "codigo" and corpo["email"] is None
    assert _codigo(client, corpo["desafio"], totp.codigo(segredo, totp.passo_atual()), metodo="app").status_code == 200


def test_email_esgotado_sem_app_responde_429(client: TestClient, banco: _Fake,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    import app.senha_reset as sr

    def _esgotado(*_a, **_k):
        raise sr.LimiteDePedidos("u-ana")

    monkeypatch.setattr(sr, "criar_codigo", _esgotado)
    assert _senha(client).status_code == 429


# ── 4. Cadastro do app ───────────────────────────────────────────────────

def _bearer() -> Dict[str, str]:
    return {"Authorization": "Bearer " + auth.create_access_token({"sub": EMAIL, "role": "user", "sv": 0})}


def test_cadastro_do_app_pede_senha_e_confirmacao(client: TestClient, banco: _Fake) -> None:
    h = _bearer()
    assert client.post("/api/users/me/app-autenticador/iniciar", json={"senha_atual": "errada"},
                       headers=h).status_code == 400
    r = client.post("/api/users/me/app-autenticador/iniciar", json={"senha_atual": SENHA}, headers=h)
    assert r.status_code == 200, r.text
    segredo = r.json()["segredo"].replace(" ", "")
    assert r.json()["uri"].startswith("otpauth://totp/")
    # QR (11/10/2026): imagem do próprio servidor, do mesmo link otpauth.
    assert r.json()["qr"] == totp.qr_data_uri(r.json()["uri"])
    assert r.json()["qr"].startswith("data:image/svg+xml")
    assert _ana(banco)["totp_cifrado"] and segredo not in _ana(banco)["totp_cifrado"]
    assert not _ana(banco).get("totp_ativado_em"), "inativo até confirmar"

    vizinhos = {totp.codigo(segredo, totp.passo_atual() + d) for d in (-1, 0, 1)}
    errado = next(c for c in ("000000", "111111", "222222", "333333") if c not in vizinhos)
    assert client.post("/api/users/me/app-autenticador/confirmar", json={"codigo": errado},
                       headers=h).status_code == 400
    assert not _ana(banco).get("totp_ativado_em")
    ok = client.post("/api/users/me/app-autenticador/confirmar",
                     json={"codigo": totp.codigo(segredo, totp.passo_atual())}, headers=h)
    assert ok.status_code == 200, ok.text
    assert _ana(banco)["totp_ativado_em"]
    assert client.get("/api/users/me/app-autenticador", headers=h).json()["ativo"] is True

    # Ativo: outro cadastro por cima exigiria remover antes.
    assert client.post("/api/users/me/app-autenticador/iniciar", json={"senha_atual": SENHA},
                       headers=h).status_code == 409
    assert client.post("/api/users/me/app-autenticador/remover", json={"senha_atual": "errada"},
                       headers=h).status_code == 400
    assert client.post("/api/users/me/app-autenticador/remover", json={"senha_atual": SENHA},
                       headers=h).status_code == 200
    assert not _ana(banco).get("totp_cifrado") and not _ana(banco).get("totp_ativado_em")


def test_so_admin_remove_o_app_de_outra_pessoa(client: TestClient, banco: _Fake) -> None:
    _ativar_app(banco)
    r = client.post("/api/users/u-ana/app-autenticador/remover", headers=_bearer())
    assert r.status_code == 403
    assert _ana(banco).get("totp_ativado_em")


def test_envio_do_codigo_de_login_monta_o_email(monkeypatch: pytest.MonkeyPatch) -> None:
    """O envio de verdade (os outros testes trocam por um duplo): sem isto, um
    argumento errado para o SMTP só apareceria em produção, com ninguém
    conseguindo entrar."""
    import app.rotas.usuarios as m
    from app import correio

    chamadas = []
    monkeypatch.setattr(correio, "configurado", lambda _s: True)
    monkeypatch.setattr(correio, "send_smtp_email", lambda **kw: chamadas.append(kw))
    m._enviar_codigo_de_login({"email": EMAIL, "full_name": "<Ana>"}, "123456")
    assert chamadas and chamadas[0]["to_email"] == EMAIL
    assert "123456" in chamadas[0]["html_content"] and "&lt;Ana&gt;" in chamadas[0]["html_content"]
