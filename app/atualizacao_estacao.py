"""A versão publicada do Certguard Análise, para a atualização automática (1.1.0).

O portal só GUARDA e ENTREGA: o pacote vem assinado de
`scripts/versoes_certguard.py` e quem confere a assinatura é a estação
(`estacao/manifesto.py`). Invadir o servidor não basta para publicar versão.

A pasta é `config.ATUALIZACOES_DIR/certificados`: `vigente.json` (o pacote
assinado) e o instalador que ele aponta. Não há upload pelo portal: publicar é
copiar os dois arquivos para lá (`deploy/publicar-certguard.ps1`).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional

from app import config

logger = logging.getLogger(__name__)

PRODUTO = "certificados"
_RE_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RE_ARQUIVO = re.compile(r"^[A-Za-z0-9._-]{1,120}\.exe$")
_RE_VERSAO = re.compile(r"^\d{1,4}\.\d{1,4}\.\d{1,4}$")


class PublicacaoIlegivel(RuntimeError):
    """`vigente.json` existe mas não serve: ninguém atualiza até corrigir."""


def pasta() -> Path:
    return Path(config.ATUALIZACOES_DIR) / PRODUTO


def vigente() -> Optional[Dict[str, Any]]:
    """O pacote publicado, como está no disco; None se não há versão.

    Não confere assinatura (quem confere é a estação), só que é JSON e aponta
    para um arquivo de nome, hash e versão bem formados.
    """
    caminho = pasta() / "vigente.json"
    if not caminho.is_file():
        return None
    try:
        pacote = json.loads(caminho.read_text(encoding="utf-8"))
        m = pacote["manifesto"]
        if not (_RE_ARQUIVO.match(m["arquivo"]) and _RE_SHA256.match(m["sha256"]) and _RE_VERSAO.match(m["versao"])):
            raise ValueError("arquivo, sha256 ou versão malformado")
    except Exception as e:
        logger.exception("vigente.json do Certguard ilegível; ninguém atualiza até corrigir.")
        raise PublicacaoIlegivel(str(e)) from None
    return pacote


def instalador(sha256: str) -> Optional[Path]:
    """O instalador do pacote vigente, se `sha256` é o dele."""
    pacote = vigente()
    if pacote is None or pacote["manifesto"]["sha256"] != sha256:
        return None
    caminho = pasta() / pacote["manifesto"]["arquivo"]
    if not caminho.is_file():
        logger.error("vigente.json do Certguard aponta para %s, que não está na pasta.", caminho.name)
        raise PublicacaoIlegivel("instalador publicado não encontrado")
    return caminho


def versao_publicada() -> Optional[str]:
    """A versão vigente ("1.1.0"), ou None sem publicação ou com ela ilegível.
    É contra ela que a aba Computadores marca a bandeja desatualizada."""
    try:
        pacote = vigente()
    except PublicacaoIlegivel:
        return None
    return pacote["manifesto"]["versao"] if pacote else None
