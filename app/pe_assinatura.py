"""Inspeção do executável do instalador: identidade e assinatura Authenticode.

Existe porque `INSTALADOR_AVULSO_EXE.is_file()` só era consultado no clique do
usuário, e a falha virava um 503 com a mensagem "rode
scripts/build_instalador_avulso.ps1" — instrução inútil para quem está na
Vercel, onde o sistema de arquivos é somente leitura e o binário vem no bundle.
Quem administra o portal não tinha como saber se havia binário, qual, nem de
quando.

A assinatura importa mais do que parece. A pendência de 11/08 registra que a
assinatura de código foi **adiada**, com mitigação por diretiva de grupo e a
observação de que não foi verificada em máquina real. Enquanto for assim, esta
tela é o lugar de a dívida ficar visível em vez de dormir num changelog.

**Regra de leitura deste módulo:** na dúvida, dizer que não sabe. Um falso
"assinado" é pior que um "não consegui determinar" — o primeiro faz alguém
confiar num binário que o Windows vai barrar na frente do usuário final.
"""

from __future__ import annotations

import hashlib
import logging
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Índice da Certificate Table nos data directories do cabeçalho opcional PE.
# É onde o Authenticode guarda o PKCS#7; ao contrário dos outros diretórios, o
# endereço ali é offset de ARQUIVO, não RVA.
_IDX_CERTIFICATE_TABLE = 4

_MAGIC_PE32 = 0x10B
_MAGIC_PE32_PLUS = 0x20B

# Tamanho do cabeçalho opcional até o início dos data directories.
_ATE_DIRETORIOS = {_MAGIC_PE32: 96, _MAGIC_PE32_PLUS: 112}


@dataclass
class Signatario:
    subject: str
    issuer: str
    nao_antes: Optional[str]
    nao_depois: Optional[str]
    expirado: Optional[bool]


@dataclass
class Binario:
    """Tudo o que dá para afirmar sobre o executável, sem executá-lo."""

    existe: bool
    caminho: str
    tamanho_bytes: Optional[int] = None
    sha256: Optional[str] = None
    modificado_em: Optional[str] = None
    assinado: Optional[bool] = None          # None = não foi possível determinar
    assinatura_detalhe: Optional[str] = None
    signatarios: List[Signatario] = field(default_factory=list)


def _le_diretorio_de_certificados(dados: bytes) -> Optional[tuple]:
    """(offset, tamanho) da Certificate Table, ou None se o PE não for legível."""
    if len(dados) < 0x40 or dados[:2] != b"MZ":
        return None
    (e_lfanew,) = struct.unpack_from("<I", dados, 0x3C)
    if e_lfanew + 24 > len(dados) or dados[e_lfanew : e_lfanew + 4] != b"PE\0\0":
        return None

    inicio_opcional = e_lfanew + 24
    (magic,) = struct.unpack_from("<H", dados, inicio_opcional)
    deslocamento = _ATE_DIRETORIOS.get(magic)
    if deslocamento is None:
        return None

    pos = inicio_opcional + deslocamento + _IDX_CERTIFICATE_TABLE * 8
    if pos + 8 > len(dados):
        return None
    offset, tamanho = struct.unpack_from("<II", dados, pos)
    return offset, tamanho


def _signatarios_do_pkcs7(blob: bytes) -> List[Signatario]:
    from cryptography.hazmat.primitives.serialization import pkcs7

    agora = datetime.now(timezone.utc)
    out: List[Signatario] = []
    for cert in pkcs7.load_der_pkcs7_certificates(blob):
        try:
            depois = cert.not_valid_after_utc
            antes = cert.not_valid_before_utc
        except AttributeError:  # cryptography antigo
            depois = cert.not_valid_after.replace(tzinfo=timezone.utc)
            antes = cert.not_valid_before.replace(tzinfo=timezone.utc)
        out.append(
            Signatario(
                subject=cert.subject.rfc4514_string(),
                issuer=cert.issuer.rfc4514_string(),
                nao_antes=antes.isoformat(),
                nao_depois=depois.isoformat(),
                expirado=depois < agora,
            )
        )
    return out


def inspecionar(caminho: Path) -> Binario:
    """
    Descreve o executável. Nunca levanta: a tela de diagnóstico não pode cair
    porque o binário está corrompido — é justamente quando ela mais serve.
    """
    if not caminho.is_file():
        return Binario(existe=False, caminho=str(caminho))

    info = Binario(existe=True, caminho=str(caminho))
    try:
        st = caminho.stat()
        info.tamanho_bytes = st.st_size
        info.modificado_em = datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()

        h = hashlib.sha256()
        with caminho.open("rb") as f:
            for bloco in iter(lambda: f.read(1024 * 1024), b""):
                h.update(bloco)
        info.sha256 = h.hexdigest()
    except OSError as e:
        info.assinatura_detalhe = f"Não foi possível ler o arquivo: {e}"
        return info

    try:
        with caminho.open("rb") as f:
            cabecalho = f.read(4096)
            diretorio = _le_diretorio_de_certificados(cabecalho)
            if diretorio is None:
                info.assinatura_detalhe = "Arquivo não parece um executável PE válido."
                return info

            offset, tamanho = diretorio
            if not offset or not tamanho:
                info.assinado = False
                info.assinatura_detalhe = (
                    "Sem assinatura digital. O SmartScreen vai alertar o usuário final "
                    "na primeira execução."
                )
                return info

            f.seek(offset)
            bruto = f.read(tamanho)

        # WIN_CERTIFICATE: dwLength(4) wRevision(2) wCertificateType(2), depois o PKCS#7.
        if len(bruto) <= 8:
            info.assinatura_detalhe = "Tabela de certificados truncada."
            return info

        info.signatarios = _signatarios_do_pkcs7(bruto[8:])
        info.assinado = True
        if any(s.expirado for s in info.signatarios):
            info.assinatura_detalhe = "Assinado, mas há certificado expirado na cadeia."
        else:
            info.assinatura_detalhe = "Assinado."
    except Exception as e:  # noqa: BLE001
        # Assinado-porém-ilegível e não-assinado são coisas diferentes, e afirmar
        # a segunda por não conseguir a primeira seria mentir para quem decide.
        logger.warning("Falha ao ler assinatura de %s: %s", caminho, e)
        info.assinado = None
        info.assinatura_detalhe = f"Não foi possível determinar a assinatura: {e}"

    return info
