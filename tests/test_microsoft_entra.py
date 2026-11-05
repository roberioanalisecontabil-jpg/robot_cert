"""Cliente OIDC da Microsoft (app/microsoft_entra.py): sem rede, com chaves
RSA de teste e o login.microsoftonline.com falso de `httpx.MockTransport`."""
import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk, jwt

from app import microsoft_entra as me

LOCATARIO = "11111111-2222-3333-4444-555555555555"
CLIENTE = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
NONCE = "nonce-da-sessao"


def _par_rsa():
    privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = privada.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    publica = privada.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return pem, publica


CHAVE, CHAVE_PUB = _par_rsa()
OUTRA, _ = _par_rsa()


def _jwks(kid="k1"):
    d = jwk.construct(CHAVE_PUB, "RS256").to_dict()
    d.update(kid=kid, use="sig")
    return {"keys": [d]}


def _claims(**muda):
    agora = int(time.time())
    c = {
        "aud": CLIENTE,
        "iss": f"https://login.microsoftonline.com/{LOCATARIO}/v2.0",
        "tid": LOCATARIO,
        "oid": "oid-da-pessoa",
        "nonce": NONCE,
        "iat": agora,
        "nbf": agora,
        "exp": agora + 3600,
        "preferred_username": "bruno@analisegroup.cnt.br",
        "email": "bruno@analisegroup.cnt.br",
        "name": "Bruno",
    }
    c.update(muda)
    return c


def _id_token(claims=None, chave=CHAVE, kid="k1", alg="RS256"):
    return jwt.encode(claims or _claims(), chave, algorithm=alg, headers={"kid": kid})


class Falso:
    """login.microsoftonline.com: conta as buscas ao JWKS e responde o token."""

    def __init__(self, id_token=None, jwks=None, token=None):
        self.id_token = id_token or _id_token()
        self.jwks = jwks or _jwks()
        self.token = token  # (status, corpo) ou exceção
        self.buscas_jwks = 0
        self.pedidos = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if req.url.path == f"/{LOCATARIO}/discovery/v2.0/keys":
            self.buscas_jwks += 1
            return httpx.Response(200, json=self.jwks)
        assert req.url.path == f"/{LOCATARIO}/oauth2/v2.0/token"
        self.pedidos.append(parse_qs(req.content.decode()))
        if isinstance(self.token, Exception):
            raise self.token
        if self.token:
            return httpx.Response(self.token[0], json=self.token[1])
        return httpx.Response(200, json={
            "id_token": self.id_token, "access_token": "at", "refresh_token": "rt-1",
        })

    def cliente(self):
        return httpx.Client(transport=httpx.MockTransport(self))


@pytest.fixture(autouse=True)
def configurado(monkeypatch):
    monkeypatch.setattr("app.config.MICROSOFT_TENANT_ID", LOCATARIO)
    monkeypatch.setattr("app.config.MICROSOFT_CLIENT_ID", CLIENTE)
    monkeypatch.setattr("app.config.MICROSOFT_CLIENT_SECRET", "segredo")
    monkeypatch.setattr(
        "app.config.MICROSOFT_DOMINIOS", frozenset({"analisegroup.cnt.br", "analisecontabil.cnt.br"})
    )
    monkeypatch.setattr("app.config.PORTAL_BASE_URL", "https://certificado.analisegroup.cnt.br")
    me.esquecer_chaves()
    yield
    me.esquecer_chaves()


@pytest.mark.parametrize(
    "variavel",
    ["MICROSOFT_TENANT_ID", "MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET", "MICROSOFT_DOMINIOS", "PORTAL_BASE_URL"],
)
def test_desligado_sem_qualquer_variavel(monkeypatch, variavel):
    assert me.configurado() is True
    monkeypatch.setattr(f"app.config.{variavel}", frozenset() if variavel == "MICROSOFT_DOMINIOS" else "")
    assert me.configurado() is False


def test_dominio_liberado():
    assert me.dominio_liberado("Bruno@AnaliseGroup.cnt.br ") is True
    assert me.dominio_liberado("x@varejoconectado.com.br") is False
    assert me.dominio_liberado("x@gmail.com") is False
    assert me.dominio_liberado("x@sub.analisegroup.cnt.br") is False
    assert me.dominio_liberado("") is False


def test_url_tem_pkce_state_nonce_e_retorno_fixo():
    url = me.url_de_autorizacao("st", "nn", "verificador-pkce")
    partes = urlsplit(url)
    assert f"{partes.scheme}://{partes.netloc}{partes.path}" == (
        f"https://login.microsoftonline.com/{LOCATARIO}/oauth2/v2.0/authorize"
    )
    q = {k: v[0] for k, v in parse_qs(partes.query).items()}
    assert q["code_challenge_method"] == "S256"
    esperado = base64.urlsafe_b64encode(hashlib.sha256(b"verificador-pkce").digest()).rstrip(b"=").decode()
    assert q["code_challenge"] == esperado
    assert q["state"] == "st" and q["nonce"] == "nn"
    assert q["redirect_uri"] == "https://certificado.analisegroup.cnt.br/entrar/microsoft/retorno"
    assert "offline_access" in q["scope"].split()
    assert q["response_mode"] == "query" and q["prompt"] == "select_account"
    assert q["client_id"] == CLIENTE and q["response_type"] == "code"


def test_trocar_codigo_devolve_identidade_e_refresh():
    falso = Falso()
    ident, refresh = me.trocar_codigo("cod", "verif", NONCE, cliente=falso.cliente())
    assert ident == me.Identidade(
        oid="oid-da-pessoa", tid=LOCATARIO, upn="bruno@analisegroup.cnt.br",
        email="bruno@analisegroup.cnt.br", nome="Bruno", convidado=False,
    )
    assert refresh == "rt-1"
    p = falso.pedidos[0]
    assert p["grant_type"] == ["authorization_code"] and p["code_verifier"] == ["verif"]
    assert p["redirect_uri"] == ["https://certificado.analisegroup.cnt.br/entrar/microsoft/retorno"]


@pytest.mark.parametrize(
    "muda",
    [
        {"aud": "outro-cliente"},
        {"tid": "99999999-2222-3333-4444-555555555555"},
        {"iss": "https://login.microsoftonline.com/99999999-2222-3333-4444-555555555555/v2.0"},
        {"nonce": "outro-nonce"},
        {"exp": int(time.time()) - 600},
        {"oid": ""},
    ],
)
def test_trocar_codigo_confere_claims(muda):
    falso = Falso(id_token=_id_token(_claims(**muda)))
    with pytest.raises(me.FalhaMicrosoft):
        me.trocar_codigo("cod", "verif", NONCE, cliente=falso.cliente())


def test_trocar_codigo_erro_do_token_vira_falha():
    for token in [(400, {"error": "invalid_grant"}), (200, {"access_token": "x"}), httpx.ConnectError("x")]:
        with pytest.raises(me.FalhaMicrosoft):
            me.trocar_codigo("cod", "verif", NONCE, cliente=Falso(token=token).cliente())


def test_assinatura_conferida(monkeypatch):
    agora = [1000.0]
    monkeypatch.setattr(me, "_relogio", lambda: agora[0])
    me.trocar_codigo("cod", "verif", NONCE, cliente=Falso().cliente())

    for tok in [_id_token(chave=OUTRA), _id_token(alg="HS256", chave="segredo-simetrico")]:
        with pytest.raises(me.FalhaMicrosoft):
            me.trocar_codigo("cod", "verif", NONCE, cliente=Falso(id_token=tok).cliente())

    # kid fora do JWKS: rebaixa uma vez (cache com mais de 5 min) e ainda recusa.
    agora[0] += 301
    falso = Falso(id_token=_id_token(kid="desconhecido"))
    with pytest.raises(me.FalhaMicrosoft):
        me.trocar_codigo("cod", "verif", NONCE, cliente=falso.cliente())
    assert falso.buscas_jwks == 1


def test_jwks_fora_do_ar_nunca_aceita():
    class Fora(Falso):
        def __call__(self, req):
            if req.url.path.endswith("/keys"):
                return httpx.Response(503)
            return super().__call__(req)

    with pytest.raises(me.FalhaMicrosoft):
        me.trocar_codigo("cod", "verif", NONCE, cliente=Fora().cliente())


def test_jwks_em_cache_24h(monkeypatch):
    agora = [1000.0]
    monkeypatch.setattr(me, "_relogio", lambda: agora[0])
    falso = Falso()
    me.trocar_codigo("cod", "verif", NONCE, cliente=falso.cliente())
    me.trocar_codigo("cod", "verif", NONCE, cliente=falso.cliente())
    assert falso.buscas_jwks == 1

    # kid novo dentro de 5 min da última busca: não rebaixa.
    falso.id_token = _id_token(kid="k2")
    with pytest.raises(me.FalhaMicrosoft):
        me.trocar_codigo("cod", "verif", NONCE, cliente=falso.cliente())
    assert falso.buscas_jwks == 1

    # Passados 5 min, o kid novo força a busca, e a chave rodada passa a valer.
    agora[0] += 301
    falso.jwks = _jwks(kid="k2")
    me.trocar_codigo("cod", "verif", NONCE, cliente=falso.cliente())
    assert falso.buscas_jwks == 2

    # Passadas 24 h, busca de novo mesmo com o kid conhecido.
    agora[0] += 24 * 3600 + 1
    me.trocar_codigo("cod", "verif", NONCE, cliente=falso.cliente())
    assert falso.buscas_jwks == 3


def test_jwks_vencido_e_fora_do_ar_mantem_a_chave_conhecida(monkeypatch, caplog):
    agora = [1000.0]
    monkeypatch.setattr(me, "_relogio", lambda: agora[0])
    falso = Falso()
    me.trocar_codigo("cod", "verif", NONCE, cliente=falso.cliente())

    class Fora(Falso):
        def __call__(self, req):
            if req.url.path.endswith("/keys"):
                self.buscas_jwks += 1
                return httpx.Response(503)
            return super().__call__(req)

    # Passadas 24 h com a Microsoft fora do ar: a chave já conhecida continua
    # valendo; só kid desconhecido é recusado.
    agora[0] += 24 * 3600 + 1
    fora = Fora()
    with caplog.at_level("WARNING", logger="app.microsoft_entra"):
        ident, _ = me.trocar_codigo("cod", "verif", NONCE, cliente=fora.cliente())
    assert ident.oid == "oid-da-pessoa" and fora.buscas_jwks == 1
    assert any(r.levelname == "WARNING" for r in caplog.records)
    with pytest.raises(me.FalhaMicrosoft):
        me.trocar_codigo("cod", "verif", NONCE, cliente=Fora(id_token=_id_token(kid="k9")).cliente())


@pytest.mark.parametrize("adiante, aceito", [(60, True), (300, False)])
def test_relogio_do_servidor_atrasado_tolera_dois_minutos(adiante, aceito):
    agora = int(time.time())
    tok = _id_token(_claims(nbf=agora + adiante, iat=agora + adiante))
    if aceito:
        me.trocar_codigo("cod", "verif", NONCE, cliente=Falso(id_token=tok).cliente())
    else:
        with pytest.raises(me.FalhaMicrosoft):
            me.trocar_codigo("cod", "verif", NONCE, cliente=Falso(id_token=tok).cliente())


def test_convidado_detectado():
    tok = _id_token(_claims(preferred_username="bruno_gmail.com#EXT#@analisegroup.onmicrosoft.com"))
    ident, _ = me.trocar_codigo("cod", "verif", NONCE, cliente=Falso(id_token=tok).cliente())
    assert ident.convidado is True


@pytest.mark.parametrize("acct, convidado", [(1, True), (0, False)])
def test_convidado_pela_claim_acct(acct, convidado):
    ident, _ = me.trocar_codigo("cod", "verif", NONCE, cliente=Falso(id_token=_id_token(_claims(acct=acct))).cliente())
    assert ident.convidado is convidado


def test_tenant_id_da_variavel_vira_minusculo_sem_espacos():
    import os
    import subprocess
    import sys
    from pathlib import Path

    env = {**os.environ, "MICROSOFT_TENANT_ID": "  AAAA-BBBB  "}
    r = subprocess.run(
        [sys.executable, "-c", "from app import config; print(repr(config.MICROSOFT_TENANT_ID))"],
        env=env, capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1], check=True,
    )
    assert r.stdout.strip() == "'aaaa-bbbb'"


def _erro(codigo, error="invalid_grant", status=400):
    return (status, {"error": error, "error_description": f"{codigo}: texto da Microsoft.", "error_codes": []})


@pytest.mark.parametrize(
    "token, resultado, codigo",
    [
        (_erro("AADSTS50057"), "bloqueada", "AADSTS50057"),
        (_erro("AADSTS50034"), "bloqueada", "AADSTS50034"),
        (_erro("AADSTS50173"), "sem_conferencia", "AADSTS50173"),
        (_erro("AADSTS70043"), "sem_conferencia", "AADSTS70043"),
        (_erro("AADSTS700082"), "sem_conferencia", "AADSTS700082"),
        (_erro("AADSTS99999"), "sem_conferencia", "AADSTS99999"),
        (_erro("AADSTS7000215", error="invalid_client", status=401), "falha", "AADSTS7000215"),
        (_erro("AADSTS7000222", error="invalid_client", status=401), "falha", "AADSTS7000222"),
        (_erro("AADSTS700016", error="unauthorized_client"), "falha", "AADSTS700016"),
        ((429, {}), "falha", None),
        ((503, {}), "falha", None),
        (httpx.ReadTimeout("lento"), "falha", None),
    ],
)
def test_renovar_classifica(token, resultado, codigo):
    r = me.renovar("rt-velho", cliente=Falso(token=token).cliente())
    assert (r.resultado, r.codigo_aadsts, r.refresh_novo) == (resultado, codigo, None)


def test_renovar_ok_devolve_refresh_novo():
    falso = Falso(token=(200, {"access_token": "at", "refresh_token": "rt-novo"}))
    r = me.renovar("rt-velho", cliente=falso.cliente())
    assert r == me.Renovacao(resultado="ok", refresh_novo="rt-novo", codigo_aadsts=None)
    assert falso.pedidos[0]["grant_type"] == ["refresh_token"]
    assert falso.pedidos[0]["refresh_token"] == ["rt-velho"]
