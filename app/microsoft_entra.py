"""Entrar com a Microsoft: cliente OIDC (authorization code + PKCE) de um
locatário só do Entra ID. Sem banco: troca o código, confere o id_token e
renova a chave de renovação (refresh token) para a conferência periódica.

A assinatura do id_token é conferida contra as chaves públicas do locatário
(JWKS), guardadas por 24 h no processo. `kid` desconhecido força uma busca
nova — a Microsoft roda as chaves —, mas no máximo uma a cada 5 min, para um
token forjado não virar martelo no login.microsoftonline.com. Sem as chaves,
nada entra: nunca se aceita token sem conferir.

Spec: docs/superpowers/specs/2026-11-04-login-microsoft-design.md.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Literal, Optional
from urllib.parse import urlencode

import httpx
from jose import jwt
from jose.exceptions import JOSEError

from app import config

logger = logging.getLogger(__name__)

AUTORIDADE = "https://login.microsoftonline.com"
ESCOPOS = "openid profile email offline_access User.Read"
TIMEOUT_S = 10.0
CACHE_JWKS_S = 24 * 3600
REBUSCA_MIN_S = 5 * 60

# Recusas que dizem "a pessoa não pode mais entrar": conta desativada
# (50057) ou apagada (50034) no locatário. Só estas desativam no CertGuard.
_BLOQUEADA = {"AADSTS50057", "AADSTS50034"}
# Erro do NOSSO aplicativo (segredo vencido/inválido, app inexistente): não
# diz nada da pessoa, e o TI precisa saber.
_ERRO_DO_APP = {"AADSTS7000215", "AADSTS7000222", "AADSTS700016"}
_RE_AADSTS = re.compile(r"AADSTS\d+")


class FalhaMicrosoft(Exception):
    """Qualquer falha na entrada pela Microsoft (rede, recusa, token inválido)."""


@dataclass
class Identidade:
    oid: str
    tid: str
    upn: str
    email: str
    nome: str
    convidado: bool


@dataclass
class Renovacao:
    resultado: Literal["ok", "bloqueada", "sem_conferencia", "falha"]
    refresh_novo: Optional[str]
    codigo_aadsts: Optional[str]


def configurado() -> bool:
    return bool(
        config.MICROSOFT_TENANT_ID
        and config.MICROSOFT_CLIENT_ID
        and config.MICROSOFT_CLIENT_SECRET
        and config.MICROSOFT_DOMINIOS
        and config.PORTAL_BASE_URL
    )


def dominio_liberado(email: str) -> bool:
    e = (email or "").strip().lower()
    if "@" not in e:
        return False
    return e.rsplit("@", 1)[1] in config.MICROSOFT_DOMINIOS


def _retorno() -> str:
    return f"{config.PORTAL_BASE_URL}/entrar/microsoft/retorno"


def _base() -> str:
    return f"{AUTORIDADE}/{config.MICROSOFT_TENANT_ID}"


def url_de_autorizacao(state: str, nonce: str, verificador: str) -> str:
    desafio = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
    return f"{_base()}/oauth2/v2.0/authorize?" + urlencode({
        "client_id": config.MICROSOFT_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": _retorno(),
        "response_mode": "query",
        "scope": ESCOPOS,
        "state": state,
        "nonce": nonce,
        "code_challenge": desafio,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    })


def _post(cliente: Optional[httpx.Client], dados: dict) -> httpx.Response:
    """Cliente de fora (testes) não é fechado aqui; o próprio vive só na chamada."""
    url = f"{_base()}/oauth2/v2.0/token"
    dados = {"client_id": config.MICROSOFT_CLIENT_ID, "client_secret": config.MICROSOFT_CLIENT_SECRET,
             "scope": ESCOPOS, **dados}
    if cliente is not None:
        return cliente.post(url, data=dados, timeout=TIMEOUT_S)
    with httpx.Client(timeout=TIMEOUT_S) as http:
        return http.post(url, data=dados)


# ── Chaves públicas (JWKS) ──────────────────────────────────────────────────

_relogio = time.monotonic
_trava = threading.Lock()
_chaves: dict[str, dict] = {}
_buscado_em: Optional[float] = None


def esquecer_chaves() -> None:
    global _buscado_em
    with _trava:
        _chaves.clear()
        _buscado_em = None


def _chave(kid: str, cliente: Optional[httpx.Client]) -> dict:
    global _buscado_em
    agora = _relogio()
    with _trava:
        idade = None if _buscado_em is None else agora - _buscado_em
        if idade is not None and idade < CACHE_JWKS_S and (kid in _chaves or idade < REBUSCA_MIN_S):
            if kid in _chaves:
                return _chaves[kid]
            raise FalhaMicrosoft("kid desconhecido")
    url = f"{_base()}/discovery/v2.0/keys"
    try:
        if cliente is not None:
            r = cliente.get(url, timeout=TIMEOUT_S)
        else:
            with httpx.Client(timeout=TIMEOUT_S) as http:
                r = http.get(url)
        r.raise_for_status()
        novas = {k["kid"]: k for k in r.json()["keys"] if k.get("kid")}
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        with _trava:
            guardada = _chaves.get(kid)
        if guardada is not None:
            # Cache vencido e Microsoft fora: a chave conhecida ainda vale, e o
            # login não cai por isso. A próxima chamada tenta buscar de novo.
            logger.warning("Microsoft: chaves públicas não renovadas (%s); usando as guardadas", type(e).__name__)
            return guardada
        logger.error("Microsoft: falha ao baixar as chaves públicas: %s", type(e).__name__)
        raise FalhaMicrosoft("JWKS indisponível") from None
    with _trava:
        _chaves.clear()
        _chaves.update(novas)
        _buscado_em = agora
    if kid not in novas:
        raise FalhaMicrosoft("kid desconhecido")
    return novas[kid]


def _conferir(id_token: str, nonce: str, access_token: Optional[str], cliente: Optional[httpx.Client]) -> dict:
    try:
        cabecalho = jwt.get_unverified_header(id_token)
    except JOSEError:
        raise FalhaMicrosoft("id_token malformado") from None
    if cabecalho.get("alg") != "RS256" or not cabecalho.get("kid"):
        raise FalhaMicrosoft("id_token com alg/kid inesperado")
    chave = _chave(str(cabecalho["kid"]), cliente)
    try:
        claims = jwt.decode(
            id_token, chave, algorithms=["RS256"], audience=config.MICROSOFT_CLIENT_ID,
            issuer=f"{AUTORIDADE}/{config.MICROSOFT_TENANT_ID}/v2.0", access_token=access_token,
            # leeway: relógio do servidor um pouco atrasado não pode barrar
            # todo login pelo nbf/iat (python-jose 3.5 lê de `options`).
            options={"require_exp": True, "require_aud": True, "require_iss": True, "leeway": 120},
        )
    except JOSEError as e:
        raise FalhaMicrosoft(f"id_token recusado: {type(e).__name__}") from None
    if claims.get("tid") != config.MICROSOFT_TENANT_ID:
        raise FalhaMicrosoft("tid de outro locatário")
    if not hmac.compare_digest(str(claims.get("nonce") or ""), nonce or "-"):
        raise FalhaMicrosoft("nonce diferente")
    if not claims.get("oid"):
        raise FalhaMicrosoft("id_token sem oid")
    return claims


def trocar_codigo(
    codigo: str, verificador: str, nonce: str, cliente: Optional[httpx.Client] = None
) -> tuple[Identidade, str]:
    try:
        r = _post(cliente, {"grant_type": "authorization_code", "code": codigo,
                            "redirect_uri": _retorno(), "code_verifier": verificador})
    except httpx.HTTPError as e:
        raise FalhaMicrosoft(f"token: {type(e).__name__}") from None
    corpo = _json(r)
    if r.status_code != 200 or not corpo.get("id_token"):
        logger.warning("Microsoft: troca do código recusada (%s, %s)", r.status_code, _aadsts(corpo))
        raise FalhaMicrosoft(f"token: HTTP {r.status_code}")
    c = _conferir(str(corpo["id_token"]), nonce, corpo.get("access_token"), cliente)
    upn = str(c.get("preferred_username") or "")
    ident = Identidade(
        oid=str(c["oid"]), tid=str(c["tid"]), upn=upn, email=str(c.get("email") or upn),
        # `acct` (claim opcional do registro do app): 1 = convidado, 0 = membro.
        nome=str(c.get("name") or ""), convidado="#EXT#" in upn.upper() or c.get("acct") == 1,
    )
    return ident, str(corpo.get("refresh_token") or "")


def _json(r: httpx.Response) -> dict[str, Any]:
    try:
        corpo = r.json()
    except ValueError:
        return {}
    return corpo if isinstance(corpo, dict) else {}


def _aadsts(corpo: dict[str, Any]) -> Optional[str]:
    codigos = corpo.get("error_codes") or []
    if isinstance(codigos, list) and codigos:
        return f"AADSTS{codigos[0]}"
    achado = _RE_AADSTS.search(str(corpo.get("error_description") or ""))
    return achado.group(0) if achado else None


def renovar(refresh: str, cliente: Optional[httpx.Client] = None) -> Renovacao:
    """Classifica a resposta da Microsoft à chave de renovação. Na dúvida,
    `falha` (nada muda para a pessoa) — só `bloqueada` desativa no CertGuard."""
    try:
        r = _post(cliente, {"grant_type": "refresh_token", "refresh_token": refresh})
    except httpx.HTTPError as e:
        logger.warning("Microsoft: renovação sem resposta (%s)", type(e).__name__)
        return Renovacao("falha", None, None)
    corpo = _json(r)
    if r.status_code == 200 and corpo.get("access_token"):
        return Renovacao("ok", corpo.get("refresh_token") or None, None)
    codigo = _aadsts(corpo)
    if r.status_code == 400 and codigo in _BLOQUEADA:
        return Renovacao("bloqueada", None, codigo)
    if r.status_code == 400 and codigo not in _ERRO_DO_APP and corpo.get("error") == "invalid_grant":
        return Renovacao("sem_conferencia", None, codigo)
    logger.warning("Microsoft: renovação falhou (%s, %s)", r.status_code, codigo)
    return Renovacao("falha", None, codigo)
