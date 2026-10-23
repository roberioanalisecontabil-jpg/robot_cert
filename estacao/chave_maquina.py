"""A chave desta MÁQUINA para o portal (adendo de 10/10/2026 ao ADR 0002).

O `machine_id` é só o MAC. Com a senha de alguém e o MAC da máquina dela dava
para registrar uma bandeja "autorizada" de qualquer lugar; o portal só reconecta
um computador já autorizado quando a bandeja apresenta a chave fixada daquela
máquina. Todo usuário da estação LÊ a chave (a bandeja roda como a pessoa e
precisa enviá-la); só SYSTEM e Administradores a alteram.

── Quem grava ─────────────────────────────────────────────────────────────

No Hardlyze era o serviço. O CertGuard Análise 1.0 não tem serviço (adendo de
14/10/2026 ao ADR 0003): quem grava é o INSTALADOR, que já roda como
administrador, chamando `certguard_analise.exe --preparar-chave`. Na troca, ele
copia a chave do Hardlyze — o hash é o mesmo, então o vínculo já aprovado
continua valendo — e apaga a original. Sem chave antiga, gera uma nova, e a
máquina passa pela aprovação do administrador como equipamento novo.

O blob é copiado como está, sem decifrar e cifrar de novo: a entropia continua
a do Hardlyze, e é por isso que o nome dela fala em "invent-agent".
"""

from __future__ import annotations

import contextlib
import logging
import os
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path

from estacao import caminhos
from estacao.dpapi import SemCofreLocal, desproteger, proteger

LOGGER = logging.getLogger(__name__)

ARQUIVO = "chave_maquina.dat"
# Amarra o blob a este uso; não é segredo. Herdada do Hardlyze (ver acima).
_ENTROPIA = b"invent-agent-chave-certificados-v1"

_SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def caminho() -> Path:
    return caminhos.pasta_maquina() / ARQUIVO


def _decifrar(bruto: bytes) -> str | None:
    try:
        chave = desproteger(bruto, _ENTROPIA).decode("utf-8").strip()
    except (SemCofreLocal, UnicodeDecodeError):
        return None
    return chave if len(chave) >= 32 else None


def _ler_de(origem: Path) -> str | None:
    try:
        if not origem.is_file():
            return None
        return _decifrar(origem.read_bytes())
    except OSError:
        return None


def ler() -> str | None:
    """A chave desta máquina, ou None. Nunca levanta: sem chave a bandeja entra
    assim mesmo e o portal pede confirmação ao administrador."""
    chave = _ler_de(caminho())
    if chave is None and caminho().exists():
        LOGGER.warning("Chave da máquina ilegível em %s.", caminho())
    return chave


def _icacls(alvo: Path, *concessoes: str) -> None:
    """Herança cortada e só as concessões dadas, por SID (Windows em português
    não tem "Administrators"). Levanta se não pegar."""
    args = ["icacls", str(alvo), "/inheritance:r"]
    for c in concessoes:
        args += ["/grant", c]
    r = subprocess.run(args, capture_output=True, creationflags=_SEM_JANELA, timeout=30, check=False)
    if r.returncode != 0:
        erro = (r.stderr or r.stdout or b"").decode("utf-8", "replace").strip()
        raise SemCofreLocal(f"icacls falhou ao restringir {alvo}: {erro or 'sem detalhe'}")


def _gravar(cifrado: bytes) -> None:
    """Grava sem nenhum instante com a chave e permissão herdada (achado da
    auditoria de 10/10/2026): o conteúdo nasce numa subpasta já restrita a
    SYSTEM e Administradores, com criação exclusiva, e só então vai para o
    destino, que recebe a ACL final (Usuários passam a ler)."""
    destino = caminho()
    destino.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".novo-", dir=str(destino.parent)))
    try:
        _icacls(temp, "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F")
        novo = temp / (secrets.token_hex(16) + ".tmp")
        fd = os.open(str(novo), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(cifrado)
        os.replace(str(novo), str(destino))
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    try:
        _icacls(destino, "*S-1-5-18:F", "*S-1-5-32-544:F", "*S-1-5-32-545:R")
    except Exception:
        with contextlib.suppress(OSError):
            destino.unlink()
        raise


def preparar() -> str:
    """Deixa a chave pronta. Roda no instalador, como administrador.

    Devolve "existente" (reinstalação), "copiada" (veio do Hardlyze, original
    apagado) ou "gerada". Levanta se não conseguir gravar: o instalador mostra
    o erro em vez de seguir com uma máquina sem chave.
    """
    if ler():
        return "existente"

    legado = caminhos.chave_hardlyze()
    try:
        bruto = legado.read_bytes() if legado.is_file() else b""
    except OSError:
        LOGGER.warning("Chave do Hardlyze em %s não pôde ser lida; gerando uma nova.", legado)
        bruto = b""
    chave_antiga = _decifrar(bruto) if bruto else None

    if chave_antiga:
        _gravar(bruto)
        if ler() != chave_antiga:
            raise SemCofreLocal("A chave copiada do Hardlyze não confere depois de gravada.")
        # Só depois de conferir a cópia (adendo de 14/10: cada agente é dono da
        # sua). Se apagar falhar, a cópia já vale; o original fica esquecido.
        try:
            legado.unlink()
        except OSError:
            LOGGER.warning("Chave copiada, mas o original em %s não pôde ser apagado.", legado)
        LOGGER.info("Chave da máquina copiada do Hardlyze para %s.", caminho())
        return "copiada"

    if bruto:
        LOGGER.warning("Chave do Hardlyze em %s ilegível; gerando uma nova (fica onde está).", legado)
    _gravar(proteger(secrets.token_urlsafe(32).encode("utf-8"), _ENTROPIA, maquina=True))
    if not ler():
        raise SemCofreLocal("A chave gerada não pôde ser lida de volta.")
    LOGGER.info("Chave da máquina gerada em %s.", caminho())
    return "gerada"
