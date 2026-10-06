"""Envio de e-mail pelo Microsoft Graph, em nome de uma caixa, por aplicativo
(03/10/2026, Leva B de "feche o que falta").

Por que Graph e não SMTP com a senha da caixa: a Microsoft desliga o SMTP
básico por padrão no fim de 2026 e anuncia a remoção em 2027; com MFA no
tenant o SMTP básico já depende de exceção. O aplicativo autentica com
*client credentials* (tenant + id do app + segredo), pede um token para
`https://graph.microsoft.com/.default` e chama `POST /users/{caixa}/sendMail`.
Nenhuma senha de caixa fica no servidor — só o segredo do app, cifrado com a
mesma chave do SMTP (`smtp_service.encrypt_password`).

A permissão `Mail.Send` de aplicativo vale para o tenant inteiro; a política
de acesso (`ApplicationAccessPolicy`) que restringe o app à caixa de envio é
feita no Exchange Online, fora deste código — ver docs/envio-microsoft-365.md.

O token é guardado em memória até expirar (menos uma folga), por processo.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional, Tuple

import httpx

from app.smtp_service import decrypt_password

logger = logging.getLogger(__name__)

AUTORIDADE = "https://login.microsoftonline.com"
GRAPH = "https://graph.microsoft.com/v1.0"
ESCOPO = "https://graph.microsoft.com/.default"
TIMEOUT_S = 15.0
FOLGA_TOKEN_S = 60

# Tenant: GUID ou domínio verificado (contoso.onmicrosoft.com). App: GUID.
_RE_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_RE_DOMINIO = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")
_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ErroGraph(RuntimeError):
    """Falha ao enviar pelo Graph. Subclasses dizem QUAL, para a tela responder
    por classe sem repetir o texto da Microsoft (mesma regra do SMTP, #35)."""


class ErroConexaoGraph(ErroGraph):
    """Não alcançou login.microsoftonline.com ou graph.microsoft.com."""


class ErroAutenticacaoGraph(ErroGraph):
    """Tenant, id do app ou segredo recusados (ou segredo vencido)."""


class ErroPermissaoGraph(ErroGraph):
    """Token válido, mas sem `Mail.Send` consentida ou fora da política de
    acesso: o Graph respondeu 403."""


class ErroEnvioGraph(ErroGraph):
    """O Graph recusou a mensagem (caixa inexistente, destinatário inválido…)."""


def validar_config(tenant_id: str, client_id: str, remetente: str, reply_to: str = "") -> None:
    """Formato dos quatro campos; levanta ValueError com texto para a tela."""
    t = (tenant_id or "").strip()
    c = (client_id or "").strip()
    r = (remetente or "").strip()
    rt = (reply_to or "").strip()
    if not t or not (_RE_GUID.match(t) or _RE_DOMINIO.match(t)):
        raise ValueError("ID do tenant inválido: use o GUID do diretório ou o domínio (empresa.onmicrosoft.com).")
    if not c or not _RE_GUID.match(c):
        raise ValueError("ID do aplicativo (cliente) inválido: é o GUID que o Entra mostra na visão geral do app.")
    if not r or not _RE_EMAIL.match(r):
        raise ValueError("Caixa de envio inválida: informe o e-mail da caixa compartilhada (ex.: noreply@empresa.com.br).")
    if rt and not _RE_EMAIL.match(rt):
        raise ValueError("Responder para: informe um e-mail válido ou deixe vazio.")


def dias_para_vencer_segredo(validade: Any, hoje: Optional[date] = None) -> Optional[int]:
    """Dias até a validade do segredo (ISO `AAAA-MM-DD`); None se vazia ou
    ilegível. Negativo = já venceu."""
    s = str(validade or "").strip()
    if not s:
        return None
    try:
        d = date.fromisoformat(s[:10])
    except ValueError:
        return None
    return (d - (hoje or datetime.now(timezone.utc).date())).days


# ── Token ──────────────────────────────────────────────────────────────────

_cache: Dict[Tuple[str, str, str], Tuple[str, float]] = {}
_trava = threading.Lock()


def _classificar_http(e: BaseException) -> ErroGraph:
    if isinstance(e, (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError)):
        return ErroConexaoGraph(str(e))
    return ErroEnvioGraph(str(e))


def obter_token(tenant_id: str, client_id: str, segredo: str, *, cliente: Optional[httpx.Client] = None) -> str:
    """Token de aplicativo (client credentials). Cacheado até expirar."""
    chave = (tenant_id, client_id, segredo[-6:] if segredo else "")
    with _trava:
        guardado = _cache.get(chave)
        if guardado and guardado[1] > time.monotonic():
            return guardado[0]
    url = f"{AUTORIDADE}/{tenant_id}/oauth2/v2.0/token"
    dados = {
        "client_id": client_id,
        "client_secret": segredo,
        "scope": ESCOPO,
        "grant_type": "client_credentials",
    }
    try:
        r = _post(cliente, url, data=dados)
    except httpx.HTTPError as e:
        raise _classificar_http(e) from None
    if r.status_code in (400, 401):
        # O corpo traz `error_description` com o código AADSTS; fica no log.
        logger.error("Graph: token recusado (%s): %s", r.status_code, _resumo_erro(r))
        raise ErroAutenticacaoGraph(f"token recusado ({r.status_code})")
    if r.status_code >= 300:
        logger.error("Graph: falha ao pedir token (%s): %s", r.status_code, _resumo_erro(r))
        raise ErroConexaoGraph(f"token: HTTP {r.status_code}")
    corpo = r.json()
    token = str(corpo.get("access_token") or "")
    if not token:
        raise ErroAutenticacaoGraph("token vazio")
    validade = time.monotonic() + max(0, int(corpo.get("expires_in") or 0) - FOLGA_TOKEN_S)
    with _trava:
        _cache[chave] = (token, validade)
    return token


def esquecer_tokens() -> None:
    with _trava:
        _cache.clear()


def _post(cliente: Optional[httpx.Client], url: str, **kw: Any) -> httpx.Response:
    """Um cliente passado de fora (testes, reuso) não é fechado aqui; o
    próprio só vive durante a chamada."""
    if cliente is not None:
        return cliente.post(url, **kw)
    with httpx.Client(timeout=TIMEOUT_S) as http:
        return http.post(url, **kw)


def _resumo_erro(r: httpx.Response) -> str:
    """O código do erro, sem o texto inteiro (que pode trazer ids e tenant)."""
    try:
        j = r.json()
    except ValueError:
        return r.text[:120]
    if isinstance(j, dict):
        e = j.get("error")
        if isinstance(e, dict):
            return f"{e.get('code')}: {str(e.get('message') or '')[:160]}"
        return f"{e}: {str(j.get('error_description') or '')[:160]}"
    return str(j)[:120]


# ── Envio ──────────────────────────────────────────────────────────────────

def enviar(
    *,
    tenant_id: str,
    client_id: str,
    segredo_enc: str,
    remetente: str,
    reply_to: str,
    to_email: str,
    subject: str,
    html_content: str,
    cliente: Optional[httpx.Client] = None,
) -> None:
    """`POST /users/{remetente}/sendMail`. Levanta ErroGraph por classe."""
    validar_config(tenant_id, client_id, remetente, reply_to)
    segredo = decrypt_password(segredo_enc) if segredo_enc else ""
    if not segredo:
        raise ErroAutenticacaoGraph("segredo do aplicativo não configurado")

    token = obter_token(tenant_id.strip(), client_id.strip(), segredo, cliente=cliente)
    mensagem: Dict[str, Any] = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": html_content},
        "toRecipients": [{"emailAddress": {"address": to_email}}],
    }
    if (reply_to or "").strip():
        mensagem["replyTo"] = [{"emailAddress": {"address": reply_to.strip()}}]
    url = f"{GRAPH}/users/{remetente.strip()}/sendMail"
    try:
        r = _post(
            cliente,
            url,
            json={"message": mensagem, "saveToSentItems": False},
            headers={"Authorization": f"Bearer {token}"},
        )
    except httpx.HTTPError as e:
        raise _classificar_http(e) from None
    if r.status_code == 202:
        return
    resumo = _resumo_erro(r)
    logger.error("Graph: sendMail recusado (%s) para %s: %s", r.status_code, to_email, resumo)
    if r.status_code == 401:
        esquecer_tokens()
        raise ErroAutenticacaoGraph(f"sendMail 401: {resumo}")
    if r.status_code == 403:
        raise ErroPermissaoGraph(f"sendMail 403: {resumo}")
    raise ErroEnvioGraph(f"sendMail {r.status_code}: {resumo}")
