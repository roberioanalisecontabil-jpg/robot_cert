"""Manifesto assinado da atualização automática da bandeja (1.1.0, 20/10/2026).

Um manifesto diz: "a versão X do CertGuard Análise é o instalador com este
SHA-256". Ele é assinado com Ed25519 por `scripts/versoes_certguard.py` e
conferido pela estação antes de baixar qualquer coisa. O portal só guarda e
entrega: invadir o servidor não basta para publicar versão, porque a chave
privada não mora lá.

Veio de `core/manifesto.py` do Hardlyze, com CHAVE PRÓPRIA (decidido em
20/10/2026): os dois programas não aceitam a versão um do outro. O formato é o
mesmo de propósito, mas aqui ele só vale para o produto "certificados".

A estação traz DUAS chaves públicas (`CHAVES_PUBLICAS`): a principal, que fica
cifrada com senha na máquina que assina, e a reserva, guardada fora do
computador. Com a reserva se publica a versão que troca a principal — por
perda ou vazamento — sem passar máquina por máquina.

Este módulo é o ÚNICO lugar que sabe o formato no robot_cert. O script que
assina, a estação que confere e a rota do portal importam daqui.

Versão menor que a instalada só é aceita com `pode_voltar` — que também é
assinado. Sem isso, quem conseguisse servir um manifesto antigo (legítimo,
de uma versão com falha conhecida) empurraria a frota para trás.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

# Preenchidas com a saída de `python scripts/versoes_certguard.py gerar-chaves`. Vazias,
# o agente recusa todo manifesto: sem chave não há atualização, e isso é o
# certo — nunca "aceitar qualquer coisa enquanto não houver chave".
CHAVES_PUBLICAS: dict[str, str] = {
    # Geradas em 20/10/2026. A privada principal fica na máquina de build
    # (%USERPROFILE%\.certguard-chaves, cifrada); a reserva, fora do computador.
    "principal": "7wPrM/lhSnnasSKJh3+ayyxOH8Pq+cvObjVb1nVRTTQ=",
    "reserva": "zvEsEgU8MBX0ZZVcqbOh0XJXV1NrGJmem2AijGzjBFQ=",
}

PRODUTO = "certificados"
PRODUTOS = frozenset({PRODUTO})
_RE_VERSAO = re.compile(r"^\d{1,4}\.\d{1,4}\.\d{1,4}$")
_RE_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RE_ARQUIVO = re.compile(r"^[A-Za-z0-9._-]{1,120}\.exe$")


class ManifestoInvalido(ValueError):
    """Formato, assinatura ou chave não conferem. Nunca instalar."""


def versao_tupla(versao: str) -> tuple[int, int, int]:
    if not _RE_VERSAO.match(str(versao or "")):
        raise ManifestoInvalido(f"versão em formato inesperado: {versao!r}")
    a, b, c = (int(x) for x in versao.split("."))
    return a, b, c


def canonico(manifesto: dict[str, Any]) -> bytes:
    """Os bytes que se assinam: JSON com chaves ordenadas e sem espaços.
    Qualquer outra serialização daria outra assinatura."""
    return json.dumps(manifesto, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


def _validar_campos(m: Any) -> dict[str, Any]:
    if not isinstance(m, dict):
        raise ManifestoInvalido("manifesto não é um objeto")
    esperados = {"produto", "versao", "arquivo", "sha256", "tamanho", "pode_voltar", "publicado_em"}
    if set(m) != esperados:
        raise ManifestoInvalido(f"campos diferentes do esperado: {sorted(set(m) ^ esperados)}")
    if m["produto"] not in PRODUTOS:
        raise ManifestoInvalido(f"produto desconhecido: {m['produto']!r}")
    versao_tupla(m["versao"])
    if not isinstance(m["arquivo"], str) or not _RE_ARQUIVO.match(m["arquivo"]):
        raise ManifestoInvalido("nome de arquivo inválido")
    if not isinstance(m["sha256"], str) or not _RE_SHA256.match(m["sha256"]):
        raise ManifestoInvalido("sha256 inválido")
    if not isinstance(m["tamanho"], int) or isinstance(m["tamanho"], bool) or m["tamanho"] <= 0:
        raise ManifestoInvalido("tamanho inválido")
    if not isinstance(m["pode_voltar"], bool):
        raise ManifestoInvalido("pode_voltar precisa ser verdadeiro ou falso")
    if not isinstance(m["publicado_em"], str) or not m["publicado_em"]:
        raise ManifestoInvalido("publicado_em vazio")
    return m


def chave_publica_b64(privada: Ed25519PrivateKey) -> str:
    from cryptography.hazmat.primitives import serialization

    bruta = privada.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return base64.b64encode(bruta).decode("ascii")


def assinar(manifesto: dict[str, Any], privada: Ed25519PrivateKey, chave_id: str) -> dict[str, Any]:
    """O pacote que vai para o servidor: manifesto, qual chave assinou, assinatura."""
    _validar_campos(manifesto)
    assinatura = privada.sign(canonico(manifesto))
    return {
        "manifesto": manifesto,
        "chave": chave_id,
        "assinatura": base64.b64encode(assinatura).decode("ascii"),
    }


def conferir(pacote: Any, chaves: dict[str, str] | None = None) -> dict[str, Any]:
    """O manifesto, se a assinatura confere com uma das chaves; senão levanta.

    `chaves` é o mapa id -> chave pública em base64; por padrão, as embutidas.
    """
    chaves = CHAVES_PUBLICAS if chaves is None else chaves
    if not isinstance(pacote, dict):
        raise ManifestoInvalido("pacote não é um objeto")
    chave_id = pacote.get("chave")
    if not isinstance(chave_id, str) or chave_id not in chaves:
        raise ManifestoInvalido(f"chave desconhecida: {chave_id!r}")
    try:
        publica = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(chaves[chave_id], validate=True)
        )
        assinatura = base64.b64decode(str(pacote.get("assinatura") or ""), validate=True)
    except (ValueError, TypeError) as e:
        raise ManifestoInvalido(f"chave ou assinatura ilegível: {e}") from None
    manifesto = _validar_campos(pacote.get("manifesto"))
    try:
        publica.verify(assinatura, canonico(manifesto))
    except InvalidSignature:
        raise ManifestoInvalido("assinatura não confere") from None
    return manifesto


def decidir(manifesto: dict[str, Any], produto: str, versao_atual: str) -> str:
    """'atualizar', 'voltar' ou 'nada'. Um manifesto já CONFERIDO.

    Versão maior: atualizar. Igual: nada. Menor: voltar só com `pode_voltar`;
    sem a marca é recusa (levanta), porque é o desenho de um ataque de
    rebaixamento.
    """
    if manifesto["produto"] != produto:
        raise ManifestoInvalido(f"manifesto de outro produto: {manifesto['produto']!r}")
    nova, atual = versao_tupla(manifesto["versao"]), versao_tupla(versao_atual)
    if nova > atual:
        return "atualizar"
    if nova == atual:
        return "nada"
    if manifesto["pode_voltar"]:
        return "voltar"
    raise ManifestoInvalido(
        f"versão {manifesto['versao']} é menor que a instalada ({versao_atual}) e não traz pode_voltar"
    )


def sha256_do_arquivo(caminho: str) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()
