"""Manifesto assinado da atualização automática do CertGuard Análise (1.1.0).

Vieram do Hardlyze (tests/test_manifesto_de_versao.py), com o produto e o
script daqui. O que este arquivo prende:

  * assinatura certa passa; qualquer byte mexido no manifesto, chave
    desconhecida ou assinatura de outra chave é recusado;
  * o formato é fechado: campo a mais, a menos ou com tipo errado é recusado,
    e o pacote do Hardlyze ("hardlyze") não serve aqui;
  * versão menor só com `pode_voltar` (assinado); sem ele, recusa;
  * sem chaves embutidas, nada é aceito;
  * o script assina com a chave cifrada, recusa pacote que a frota não
    conferiria, e as chaves embutidas são as duas, válidas e distintas.
"""

from __future__ import annotations

import copy
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from estacao import manifesto as mf


def _manifesto(**muda) -> dict:
    m = {
        "produto": "certificados",
        "versao": "1.1.1",
        "arquivo": "Instalador_CertguardAnalise_1.1.1.exe",
        "sha256": "a" * 64,
        "tamanho": 29_000_000,
        "pode_voltar": False,
        "publicado_em": "2026-10-11T12:00:00Z",
    }
    m.update(muda)
    return m


@pytest.fixture
def par():
    privada = Ed25519PrivateKey.generate()
    return privada, {"principal": mf.chave_publica_b64(privada)}


def test_assinatura_certa_passa(par) -> None:
    privada, chaves = par
    pacote = mf.assinar(_manifesto(), privada, "principal")
    assert mf.conferir(pacote, chaves)["versao"] == "1.1.1"


@pytest.mark.parametrize(
    ("campo", "valor"),
    [("versao", "9.9.9"), ("sha256", "b" * 64), ("pode_voltar", True), ("tamanho", 1)],
)
def test_qualquer_campo_mexido_e_recusado(par, campo, valor) -> None:
    privada, chaves = par
    pacote = mf.assinar(_manifesto(), privada, "principal")
    pacote["manifesto"][campo] = valor
    with pytest.raises(mf.ManifestoInvalido, match="assinatura"):
        mf.conferir(pacote, chaves)


def test_assinado_por_outra_chave_e_recusado(par) -> None:
    _, chaves = par
    intrusa = Ed25519PrivateKey.generate()
    pacote = mf.assinar(_manifesto(), intrusa, "principal")
    with pytest.raises(mf.ManifestoInvalido, match="assinatura"):
        mf.conferir(pacote, chaves)


def test_chave_desconhecida_e_recusada(par) -> None:
    privada, chaves = par
    pacote = mf.assinar(_manifesto(), privada, "principal")
    pacote["chave"] = "qualquer"
    with pytest.raises(mf.ManifestoInvalido, match="chave desconhecida"):
        mf.conferir(pacote, chaves)


def test_reserva_tambem_vale(par) -> None:
    _, chaves = par
    reserva = Ed25519PrivateKey.generate()
    chaves = {**chaves, "reserva": mf.chave_publica_b64(reserva)}
    assert mf.conferir(mf.assinar(_manifesto(), reserva, "reserva"), chaves)


def test_sem_chaves_embutidas_nada_passa(par, monkeypatch) -> None:
    privada, _ = par
    monkeypatch.setattr(mf, "CHAVES_PUBLICAS", {})
    with pytest.raises(mf.ManifestoInvalido):
        mf.conferir(mf.assinar(_manifesto(), privada, "principal"))


@pytest.mark.parametrize(
    "mexe",
    [
        lambda m: m.update(extra=1),
        lambda m: m.pop("sha256"),
        lambda m: m.update(produto="outro"),
        lambda m: m.update(versao="1.1"),
        lambda m: m.update(produto="hardlyze"),
        lambda m: m.update(arquivo="../../windows/system32/x.exe"),
        lambda m: m.update(tamanho=True),
        lambda m: m.update(pode_voltar="sim"),
        lambda m: m.update(sha256="A" * 64),
    ],
)
def test_formato_fechado(par, mexe) -> None:
    privada, _ = par
    m = _manifesto()
    mexe(m)
    with pytest.raises(mf.ManifestoInvalido):
        mf.assinar(m, privada, "principal")


def test_canonico_independe_da_ordem() -> None:
    m = _manifesto()
    invertido = dict(reversed(list(copy.deepcopy(m).items())))
    assert mf.canonico(m) == mf.canonico(invertido)


# ── decidir ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("nova", "atual", "pode", "esperado"),
    [
        ("1.1.1", "1.1.0", False, "atualizar"),
        ("1.10.0", "1.9.9", False, "atualizar"),
        ("1.1.0", "1.1.0", False, "nada"),
        ("1.0.9", "1.1.0", True, "voltar"),
    ],
)
def test_decidir(nova, atual, pode, esperado) -> None:
    assert mf.decidir(_manifesto(versao=nova, pode_voltar=pode), "certificados", atual) == esperado


def test_rebaixamento_sem_marca_e_recusado() -> None:
    with pytest.raises(mf.ManifestoInvalido, match="pode_voltar"):
        mf.decidir(_manifesto(versao="1.0.9"), "certificados", "1.1.0")


def test_manifesto_de_outro_produto_e_recusado() -> None:
    with pytest.raises(mf.ManifestoInvalido, match="outro produto"):
        mf.decidir(_manifesto(), "hardlyze", "1.1.0")


# ── o script da máquina de build ──────────────────────────────────────────


def test_script_gera_chaves_e_publica(tmp_path, monkeypatch) -> None:
    from scripts import versoes_certguard as versoes

    monkeypatch.setenv("CERTGUARD_SENHA_CHAVE", "senha-de-teste-comprida")
    pasta = tmp_path / "chaves"
    publicas = versoes.gerar_chaves(pasta)
    assert set(publicas) == {"principal", "reserva"}
    assert b"ENCRYPTED" in (pasta / "principal.key").read_bytes()

    instalador = tmp_path / "Instalador_CertguardAnalise_1.1.1.exe"
    instalador.write_bytes(b"MZ" + b"\0" * 1000)
    privada = versoes.carregar_privada(pasta / "principal.key")
    destino = versoes.publicar(instalador, privada, "principal", False, tmp_path / "publicar", publicas)

    assert destino == tmp_path / "publicar" / "certificados"
    pacote = json.loads((destino / "vigente.json").read_text(encoding="utf-8"))
    m = mf.conferir(pacote, publicas)
    assert (m["versao"], m["arquivo"], m["tamanho"]) == ("1.1.1", instalador.name, 1002)
    assert m["sha256"] == mf.sha256_do_arquivo(str(destino / instalador.name))


def test_script_recusa_pacote_que_a_frota_nao_confere(tmp_path, monkeypatch) -> None:
    """Assinado com uma chave que as estações não trazem, ninguém atualizaria."""
    from scripts import versoes_certguard as versoes

    monkeypatch.setenv("CERTGUARD_SENHA_CHAVE", "senha-de-teste-comprida")
    versoes.gerar_chaves(tmp_path / "chaves")
    instalador = tmp_path / "Instalador_CertguardAnalise_1.1.1.exe"
    instalador.write_bytes(b"MZ")
    privada = versoes.carregar_privada(tmp_path / "chaves" / "principal.key")
    outras = {"principal": mf.chave_publica_b64(Ed25519PrivateKey.generate())}
    with pytest.raises(SystemExit):
        versoes.publicar(instalador, privada, "principal", False, tmp_path / "publicar", outras)
    assert not (tmp_path / "publicar").exists()


def test_script_le_a_versao_do_nome(tmp_path) -> None:
    from scripts import versoes_certguard as versoes

    assert versoes.versao_do_nome(tmp_path / "Instalador_CertguardAnalise_1.12.3.exe") == "1.12.3"
    with pytest.raises(SystemExit):
        versoes.versao_do_nome(tmp_path / "certguard.exe")


def test_script_nao_sobrescreve_chave(tmp_path, monkeypatch) -> None:
    from scripts import versoes_certguard as versoes

    monkeypatch.setenv("CERTGUARD_SENHA_CHAVE", "senha-de-teste-comprida")
    versoes.gerar_chaves(tmp_path)
    with pytest.raises(SystemExit):
        versoes.gerar_chaves(tmp_path)


def test_senha_errada_nao_abre_a_chave(tmp_path, monkeypatch) -> None:
    from scripts import versoes_certguard as versoes

    monkeypatch.setenv("CERTGUARD_SENHA_CHAVE", "senha-de-teste-comprida")
    versoes.gerar_chaves(tmp_path)
    monkeypatch.setenv("CERTGUARD_SENHA_CHAVE", "outra-senha-qualquer")
    with pytest.raises(SystemExit):
        versoes.carregar_privada(tmp_path / "principal.key")


def test_chaves_embutidas_validas_e_distintas() -> None:
    """Sem as duas, a frota não atualiza (ou não tem como trocar a principal).
    E não são as do Hardlyze: chave própria, decidido em 20/10/2026."""
    import base64

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    assert set(mf.CHAVES_PUBLICAS) == {"principal", "reserva"}
    assert mf.CHAVES_PUBLICAS["principal"] != mf.CHAVES_PUBLICAS["reserva"]
    for valor in mf.CHAVES_PUBLICAS.values():
        Ed25519PublicKey.from_public_bytes(base64.b64decode(valor, validate=True))
    hardlyze = {"TAuj60FOVvAkXYvQHcgY0e8v5Uuoqgpr0GVAo5n8844=", "RLYv3Ukb8IhlcU/fH5T9Fd76rXuvEDI65HgCrYUa/DI="}
    assert not hardlyze & set(mf.CHAVES_PUBLICAS.values())
