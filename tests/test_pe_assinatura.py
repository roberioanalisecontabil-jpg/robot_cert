"""Leitura do executável do instalador: identidade e assinatura Authenticode.

A regra que estes testes protegem é uma só: **na dúvida, dizer que não sabe**.

Um falso "assinado" é pior que um "não consegui determinar". O primeiro faz
alguém confiar num binário que o Windows vai barrar na frente do usuário final;
o segundo manda investigar. E o inverso também importa: relatar "não assinado"
porque o parser tropeçou levaria a comprar um certificado de assinatura que já
existe.

Os PEs aqui são sintéticos, montados byte a byte. Depender do `.exe` real
tornaria o teste refém de um artefato de build que nem sempre está presente — e
o que se testa é o parser, não o binário do dia.
"""

import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import pe_assinatura


def _pe(certificado: bytes = b"", *, magic: int = 0x10B) -> bytes:
    """
    PE mínimo válido para o parser: MZ, e_lfanew, assinatura PE, COFF e o
    cabeçalho opcional até a Certificate Table.
    """
    e_lfanew = 0x80
    ate_diretorios = {0x10B: 96, 0x20B: 112}[magic]
    inicio_opcional = e_lfanew + 24
    pos_dir = inicio_opcional + ate_diretorios + 4 * 8   # índice 4 = Certificate Table
    tam_cabecalho = pos_dir + 8

    buf = bytearray(b"\0" * tam_cabecalho)
    buf[0:2] = b"MZ"
    struct.pack_into("<I", buf, 0x3C, e_lfanew)
    buf[e_lfanew : e_lfanew + 4] = b"PE\0\0"
    struct.pack_into("<H", buf, inicio_opcional, magic)

    if certificado:
        # WIN_CERTIFICATE: dwLength(4) wRevision(2) wCertificateType(2) + PKCS#7
        win_cert = struct.pack("<IHH", len(certificado) + 8, 0x0200, 0x0002) + certificado
        struct.pack_into("<II", buf, pos_dir, tam_cabecalho, len(win_cert))
        return bytes(buf) + win_cert

    struct.pack_into("<II", buf, pos_dir, 0, 0)
    return bytes(buf)


def _pkcs7_de_teste(dias_validade: int = 365) -> bytes:
    """PKCS#7 'certs-only' com um certificado autoassinado, em DER."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs7
    from cryptography.x509.oid import NameOID

    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "AnaliseGroup Teste")])
    agora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1))
        .not_valid_after(agora + timedelta(days=dias_validade))
        .sign(chave, hashes.SHA256())
    )
    return pkcs7.serialize_certificates([cert], serialization.Encoding.DER)


# ──────────────────────────────────────────────────────────────────────────
# Identidade do arquivo
# ──────────────────────────────────────────────────────────────────────────

def test_arquivo_ausente(tmp_path: Path) -> None:
    """
    O caso que motivou o módulo: `is_file()` só era consultado no clique, e a
    falha virava um 503 mandando rodar um script de build — inútil na Vercel.
    """
    b = pe_assinatura.inspecionar(tmp_path / "nao-existe.exe")
    assert b.existe is False
    assert b.sha256 is None


def test_identidade_do_binario(tmp_path: Path) -> None:
    import hashlib

    alvo = tmp_path / "Instalar.exe"
    conteudo = _pe()
    alvo.write_bytes(conteudo)

    b = pe_assinatura.inspecionar(alvo)
    assert b.existe is True
    assert b.tamanho_bytes == len(conteudo)
    assert b.sha256 == hashlib.sha256(conteudo).hexdigest()
    assert b.modificado_em


# ──────────────────────────────────────────────────────────────────────────
# Assinado, não assinado e "não sei" são TRÊS estados
# ──────────────────────────────────────────────────────────────────────────

def test_sem_assinatura_e_afirmado_como_false(tmp_path: Path) -> None:
    alvo = tmp_path / "sem_assinatura.exe"
    alvo.write_bytes(_pe())

    b = pe_assinatura.inspecionar(alvo)
    assert b.assinado is False, "tabela de certificados zerada é ausência comprovada"
    assert "SmartScreen" in (b.assinatura_detalhe or "")


@pytest.mark.parametrize("magic", [0x10B, 0x20B], ids=["PE32", "PE32+"])
def test_assinatura_valida_e_lida(tmp_path: Path, magic: int) -> None:
    """
    Os data directories ficam em deslocamentos diferentes em PE32 e PE32+. Errar
    isso leria lixo como se fosse a Certificate Table — e o resultado não seria
    um erro, seria uma resposta errada.
    """
    alvo = tmp_path / "assinado.exe"
    alvo.write_bytes(_pe(_pkcs7_de_teste(), magic=magic))

    b = pe_assinatura.inspecionar(alvo)
    assert b.assinado is True
    assert len(b.signatarios) == 1
    assert "AnaliseGroup Teste" in b.signatarios[0].subject
    assert b.signatarios[0].expirado is False


def test_certificado_expirado_e_sinalizado(tmp_path: Path) -> None:
    """
    Assinado com certificado vencido continua sendo "assinado" — mas quem lê a
    tela precisa saber, porque o efeito prático no Windows é outro.
    """
    alvo = tmp_path / "expirado.exe"

    # `_pkcs7_de_teste` só emite certificado válido; aqui o ponto é a validade
    # no passado, então o certificado é montado à mão.
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs7
    from cryptography.x509.oid import NameOID

    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Vencido")])
    agora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nome).issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=800))
        .not_valid_after(agora - timedelta(days=10))
        .sign(chave, hashes.SHA256())
    )
    alvo.write_bytes(_pe(pkcs7.serialize_certificates([cert], serialization.Encoding.DER)))

    b = pe_assinatura.inspecionar(alvo)
    assert b.assinado is True
    assert b.signatarios[0].expirado is True
    assert "expirado" in (b.assinatura_detalhe or "").lower()


@pytest.mark.parametrize("conteudo,porque", [
    (b"nao sou um executavel", "arquivo comum"),
    (b"MZ" + b"\0" * 200, "MZ sem cabeçalho PE"),
    (b"MZ" + b"\0" * 0x3C + struct.pack("<I", 0x80) + b"\0" * 200, "e_lfanew apontando para lixo"),
])
def test_arquivo_ilegivel_nao_vira_nao_assinado(
    tmp_path: Path, conteudo: bytes, porque: str
) -> None:
    """
    O ponto do módulo inteiro.

    Nenhum destes é "não assinado" — são "não deu para saber". Relatar `False`
    aqui mandaria alguém comprar um certificado de assinatura para resolver um
    problema que é de outra natureza.
    """
    alvo = tmp_path / "estranho.exe"
    alvo.write_bytes(conteudo)

    b = pe_assinatura.inspecionar(alvo)
    assert b.assinado is None, f"{porque} foi reportado como não assinado"
    assert b.sha256, "a identidade do arquivo continua legível mesmo assim"


def test_pkcs7_corrompido_nao_vira_nao_assinado(tmp_path: Path) -> None:
    """Tabela de certificados presente mas ilegível também é 'não sei'."""
    alvo = tmp_path / "corrompido.exe"
    alvo.write_bytes(_pe(b"\x30\x82isto nao e um PKCS7 valido" * 4))

    b = pe_assinatura.inspecionar(alvo)
    assert b.assinado is None
    assert "não foi possível determinar" in (b.assinatura_detalhe or "").lower()


def test_inspecionar_nunca_levanta(tmp_path: Path) -> None:
    """
    A tela de diagnóstico não pode cair porque o binário está corrompido — é
    justamente quando ela mais serve.
    """
    for conteudo in (b"", b"MZ", b"\xff" * 5000, _pe(b"\x00" * 4)):
        alvo = tmp_path / "x.exe"
        alvo.write_bytes(conteudo)
        pe_assinatura.inspecionar(alvo)   # não deve levantar
