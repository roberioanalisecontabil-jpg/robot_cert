"""Transporte ponta a ponta do instalador: ECDH + HKDF + AES-256-GCM.

Os dois lados do handshake vivem em arquivos diferentes e nunca eram
exercitados juntos:

  servidor  app/cert_installer.py       encrypt_bundle_for_client()
  agente    agent/installer_client.py   _decrypt_payload_ecdh()

Cada um tinha teste de unidade do seu pedaço. Um desencontro entre eles — outra
curva, outro `info` do HKDF, outro layout de nonce/tag — passaria pelos dois
conjuntos e só apareceria numa instalação real, como "o agente não decifra".
É a mesma classe de defeito do bug de machine_id: cada lado, isolado, correto.

Aqui o bundle sai do código de produção do servidor e entra no código de
produção do agente, sem intermediário.
"""

import base64

import pytest
from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidTag

from agent.installer_client import _decrypt_payload_ecdh
from app.cert_installer import encrypt_bundle_for_client


def _par_de_chaves_do_agente():
    """Reproduz o passo 1 de `process_install_command`."""
    priv = generate_private_key(SECP256R1())
    spki = priv.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv, base64.b64encode(spki).decode()


# ──────────────────────────────────────────────────────────────────────────
# (a) Handshake e round-trip
# ──────────────────────────────────────────────────────────────────────────

def test_round_trip_devolve_os_bytes_identicos() -> None:
    """Servidor cifra, agente decifra, e o PFX volta byte a byte."""
    priv, pub_b64 = _par_de_chaves_do_agente()
    pfx_original = b"\x30\x82\x0a\x2f conteudo binario de um PFX \x00\xff" * 40

    bundle = encrypt_bundle_for_client(pfx_original, pub_b64)
    recuperado = _decrypt_payload_ecdh(priv, bundle)

    assert recuperado == pfx_original


def test_bundle_tem_o_formato_que_o_agente_espera() -> None:
    """As quatro chaves são o contrato entre os dois arquivos."""
    _, pub_b64 = _par_de_chaves_do_agente()

    bundle = encrypt_bundle_for_client(b"conteudo", pub_b64)

    assert set(bundle) == {"serverPublicKey", "iv", "authTag", "ciphertext"}
    assert len(base64.b64decode(bundle["iv"])) == 12, "nonce AES-GCM de 96 bits"
    assert len(base64.b64decode(bundle["authTag"])) == 16, "tag de 128 bits"


def test_o_texto_cifrado_nao_contem_o_pfx_em_claro() -> None:
    marcador = b"CHAVE-PRIVADA-EM-CLARO"
    _, pub_b64 = _par_de_chaves_do_agente()

    bundle = encrypt_bundle_for_client(b"xx" + marcador + b"yy", pub_b64)

    assert marcador not in base64.b64decode(bundle["ciphertext"])


def test_cada_bundle_usa_chave_efemera_nova() -> None:
    """
    Dois bundles do mesmo PFX para o mesmo agente não podem coincidir: a chave
    do servidor é efêmera por chamada. Se coincidissem, a chave estaria fixa.
    """
    _, pub_b64 = _par_de_chaves_do_agente()

    a = encrypt_bundle_for_client(b"mesmo conteudo", pub_b64)
    b = encrypt_bundle_for_client(b"mesmo conteudo", pub_b64)

    assert a["serverPublicKey"] != b["serverPublicKey"]
    assert a["iv"] != b["iv"]
    assert a["ciphertext"] != b["ciphertext"]


def test_agente_de_outro_par_de_chaves_nao_decifra() -> None:
    """O bundle é endereçado: só a chave privada do solicitante abre."""
    _, pub_alvo = _par_de_chaves_do_agente()
    priv_intruso, _ = _par_de_chaves_do_agente()

    bundle = encrypt_bundle_for_client(b"segredo", pub_alvo)

    with pytest.raises(InvalidTag):
        _decrypt_payload_ecdh(priv_intruso, bundle)


# ──────────────────────────────────────────────────────────────────────────
# (a continuação) Adulteração — a autenticação do GCM tem de recusar
# ──────────────────────────────────────────────────────────────────────────

def _vira_um_bit(b64: str) -> str:
    """Inverte o bit menos significativo do primeiro byte."""
    dados = bytearray(base64.b64decode(b64))
    dados[0] ^= 0x01
    return base64.b64encode(bytes(dados)).decode()


@pytest.mark.parametrize("campo", ["ciphertext", "authTag", "iv"])
def test_adulteracao_falha_na_autenticacao(campo: str) -> None:
    """
    Um bit trocado em qualquer um dos três campos derruba a decifragem.

    É o ponto do GCM sobre um modo só de confidencialidade: sem a tag, um
    ciphertext alterado viraria um PFX corrompido — ou pior, manipulado — e o
    agente tentaria instalá-lo.
    """
    priv, pub_b64 = _par_de_chaves_do_agente()
    bundle = encrypt_bundle_for_client(b"conteudo autentico do pfx", pub_b64)

    bundle[campo] = _vira_um_bit(bundle[campo])

    with pytest.raises(InvalidTag):
        _decrypt_payload_ecdh(priv, bundle)


def test_troca_da_chave_publica_do_servidor_falha() -> None:
    """
    Substituir `serverPublicKey` por outra válida quebra o segredo compartilhado.

    Cobre o caso em que o atacante não corrompe bytes, mas troca uma peça
    legítima por outra legítima — o que um teste de bit-flip não pega.
    """
    priv, pub_b64 = _par_de_chaves_do_agente()
    bundle = encrypt_bundle_for_client(b"conteudo", pub_b64)

    outro = generate_private_key(SECP256R1()).public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    bundle["serverPublicKey"] = base64.b64encode(outro).decode()

    with pytest.raises(InvalidTag):
        _decrypt_payload_ecdh(priv, bundle)


def test_ciphertext_truncado_falha() -> None:
    """Truncar é adulterar: não pode virar decifragem parcial."""
    priv, pub_b64 = _par_de_chaves_do_agente()
    bundle = encrypt_bundle_for_client(b"conteudo longo o suficiente" * 10, pub_b64)

    bruto = base64.b64decode(bundle["ciphertext"])
    bundle["ciphertext"] = base64.b64encode(bruto[: len(bruto) // 2]).decode()

    with pytest.raises(InvalidTag):
        _decrypt_payload_ecdh(priv, bundle)
