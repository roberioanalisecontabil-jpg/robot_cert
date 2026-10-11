"""Código de app autenticador (TOTP, RFC 6238) — a saída do login quando o
e-mail não chega (decisão do usuário, 10/10/2026).

Implementado aqui, e não por dependência: são vinte linhas de HMAC, e o
servidor não precisa de pacote novo para isso. Testado contra os vetores da
própria RFC (tests/test_totp.py).

* HMAC-SHA1, 6 dígitos, passo de 30 s — o padrão que Microsoft Authenticator,
  Google Authenticator e afins usam sem configuração;
* aceita o passo anterior e o seguinte (relógio do celular adiantado ou
  atrasado até 30 s);
* `verificar` devolve o PASSO que bateu, para quem chama gravar e recusar a
  reutilização do mesmo código (replay).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from typing import Optional
from urllib.parse import quote

DIGITOS = 6
PASSO_SEG = 30
TOLERANCIA = 1


def novo_segredo() -> str:
    """160 bits em base32, sem o preenchimento '=' (é o que os apps esperam)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _chave(segredo_b32: str) -> bytes:
    limpo = segredo_b32.replace(" ", "").upper()
    return base64.b32decode(limpo + "=" * (-len(limpo) % 8))


def codigo(segredo_b32: str, passo: int, digitos: int = DIGITOS, algoritmo=hashlib.sha1) -> str:
    mac = hmac.new(_chave(segredo_b32), struct.pack(">Q", passo), algoritmo).digest()
    deslocamento = mac[-1] & 0x0F
    valor = struct.unpack(">I", mac[deslocamento:deslocamento + 4])[0] & 0x7FFFFFFF
    return str(valor % (10 ** digitos)).zfill(digitos)


def passo_atual(agora: Optional[float] = None) -> int:
    return int((time.time() if agora is None else agora) // PASSO_SEG)


def verificar(segredo_b32: str, informado: str, agora: Optional[float] = None) -> Optional[int]:
    """O passo em que `informado` bate, ou None. Comparação em tempo constante."""
    informado = (informado or "").strip().replace(" ", "")
    if len(informado) != DIGITOS or not informado.isdigit():
        return None
    atual = passo_atual(agora)
    for passo in range(atual - TOLERANCIA, atual + TOLERANCIA + 1):
        if hmac.compare_digest(codigo(segredo_b32, passo), informado):
            return passo
    return None


def uri(segredo_b32: str, conta: str, emissor: str = "Certificados Análise") -> str:
    """O link `otpauth://` que os apps aceitam (e que um QR codificaria)."""
    rotulo = quote(f"{emissor}:{conta}")
    return f"otpauth://totp/{rotulo}?secret={segredo_b32}&issuer={quote(emissor)}&digits={DIGITOS}&period={PASSO_SEG}"


def qr_data_uri(conteudo: str):
    """O QR do link `otpauth://` como imagem SVG em `data:`, ou None se a
    biblioteca não estiver instalada (servidor ainda sem a dependência: a tela
    fica com a chave em texto, que sempre funciona)."""
    try:
        import segno
    except ImportError:
        return None
    return segno.make(conteudo, error="m").svg_data_uri(scale=5, border=2, dark="#000", light="#fff")


def agrupado(segredo_b32: str) -> str:
    """Para digitar no app: blocos de 4."""
    return " ".join(segredo_b32[i:i + 4] for i in range(0, len(segredo_b32), 4))
