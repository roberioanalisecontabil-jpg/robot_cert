"""Repositorio de certificados do Windows (`Cert:\\CurrentUser\\My`) na bandeja.

Roda como o usuario logado, por isso enxerga e remove o que a pessoa ve no
navegador. O portal compara o SHA-256 do DER (hex minusculo); aqui ele e
calculado em Python a partir do `RawData`, nao do thumbprint (que e SHA-1).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import subprocess
from dataclasses import dataclass

LOGGER = logging.getLogger(__name__)

TEMPO_LIMITE = 60

_THUMB = re.compile(r"^[0-9A-F]{40}$")

_LISTAR = (
    "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
    "$r = @(Get-ChildItem Cert:\\CurrentUser\\My | ForEach-Object { "
    "[pscustomobject]@{ Thumbprint = $_.Thumbprint; Subject = $_.Subject; "
    "Raw = [Convert]::ToBase64String($_.RawData) } }); "
    "if ($r.Count -gt 0) { ConvertTo-Json -InputObject $r -Compress -Depth 3 }"
)


@dataclass
class Item:
    sha256: str
    thumbprint: str
    nome: str


def _powershell(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TEMPO_LIMITE,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _nome(subject: str) -> str:
    """O CN do Subject, como esta; sem CN, o Subject inteiro."""
    for parte in re.split(r",\s*(?=[A-Za-z]+=)", subject or ""):
        if parte.upper().startswith("CN="):
            return parte[3:].strip()
    return (subject or "").strip()


def listar(executar=_powershell) -> list[Item]:
    """Certificados do repositorio pessoal; falha devolve [] e registra no log."""
    try:
        r = executar(_LISTAR)
        if r.returncode != 0:
            LOGGER.warning("Listagem do repositorio falhou: %s", (r.stderr or "").strip()[:300])
            return []
        texto = (r.stdout or "").strip()
        if not texto:
            return []
        dados = json.loads(texto)
        if isinstance(dados, dict):  # ConvertTo-Json desembrulha lista de um item
            dados = [dados]
        return [
            Item(
                sha256=hashlib.sha256(base64.b64decode(d["Raw"])).hexdigest(),
                thumbprint=d["Thumbprint"],
                nome=_nome(d.get("Subject") or ""),
            )
            for d in dados
        ]
    except Exception:
        LOGGER.exception("Erro ao listar o repositorio de certificados")
        return []


def remover(item: Item, executar=_powershell) -> tuple[bool, str]:
    """Remove o certificado e a chave privada dele do repositorio do usuario."""
    thumb = (item.thumbprint or "").upper()
    if not _THUMB.fullmatch(thumb):  # nunca entra em comando sem passar daqui
        return False, "thumbprint inválido"
    try:
        r = executar(
            f'Remove-Item -LiteralPath "Cert:\\CurrentUser\\My\\{thumb}" -DeleteKey -ErrorAction Stop'
        )
        if r.returncode == 0:
            return True, ""
        return False, ((r.stderr or "").strip() or (r.stdout or "").strip() or f"codigo {r.returncode}")[:500]
    except Exception as e:
        LOGGER.exception("Erro ao remover certificado")
        return False, str(e)
