"""A senha do PFX na hora de instalar.

O endurecimento de 03/08 parou de armazenar a senha no servidor — era cifrada
com a MESMA chave do PFX, então guardá-la junto não protegia nada. Três
comentários no código registraram que o agente passaria a lê-la do nome do
arquivo local. Essa parte nunca foi escrita.

O resultado: o bundle chega com `pfxPassword: None`, o agente seguia com
`password = ""` e o certutil recusava todo PFX protegido — que são todos, na
prática. As etapas anteriores (autorizar, upload, ECDH, decifrar) funcionavam;
quebrava na última, com uma mensagem do Windows sobre senha incorreta, que
aponta para o lugar errado.

A extração já existia em `cert_scanner` (padrão «nome» senha «valor».pfx,
exposto em `CertInfo.password_from_name`). Faltava ligar as duas pontas.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

import agent.installer_client as ic


class _CertFalso:
    def __init__(self, fp: str, senha) -> None:  # noqa: ANN001
        self.fingerprint_sha256 = fp
        self.password_from_name = senha


FP_A = "a" * 64
FP_B = "b" * 64


# ──────────────────────────────────────────────────────────────────────────
# Mapa de senhas a partir da pasta local
# ──────────────────────────────────────────────────────────────────────────

def test_mapa_relaciona_fingerprint_e_senha() -> None:
    certs = [_CertFalso(FP_A, "senhaDoA"), _CertFalso(FP_B, "senhaDoB")]
    with patch("app.cert_scanner.scan_folder", lambda *a, **k: certs):
        mapa = ic._senhas_por_fingerprint(Path("C:/qualquer"))

    assert mapa == {FP_A: "senhaDoA", FP_B: "senhaDoB"}


def test_arquivo_sem_senha_no_nome_fica_de_fora() -> None:
    """Nome fora do padrão não vira entrada com senha vazia."""
    certs = [_CertFalso(FP_A, None), _CertFalso(FP_B, "senhaDoB")]
    with patch("app.cert_scanner.scan_folder", lambda *a, **k: certs):
        mapa = ic._senhas_por_fingerprint(Path("C:/qualquer"))

    assert FP_A not in mapa
    assert mapa[FP_B] == "senhaDoB"


def test_sem_pasta_devolve_mapa_vazio_sem_levantar() -> None:
    assert ic._senhas_por_fingerprint(None) == {}


def test_falha_ao_varrer_nao_derruba_a_instalacao() -> None:
    """Pasta inacessível vira mapa vazio, não exceção no meio do processo."""
    def explode(*a, **k):
        raise OSError("unidade F: indisponível")

    with patch("app.cert_scanner.scan_folder", explode):
        assert ic._senhas_por_fingerprint(Path("F:/certificados")) == {}


# ──────────────────────────────────────────────────────────────────────────
# Uso da senha na instalação
# ──────────────────────────────────────────────────────────────────────────

def _bundle(fp: str) -> dict:
    return {"certificateId": "id-1", "fingerprint": fp, "pfxPassword": None}


def _instalar(monkeypatch: pytest.MonkeyPatch, senhas: dict, item: dict) -> list:
    """Roda o trecho de instalação isolando rede e certutil."""
    chamadas: list = []

    monkeypatch.setattr(ic, "_senhas_por_fingerprint", lambda _d: senhas)
    monkeypatch.setattr(ic, "_decrypt_payload_ecdh", lambda _k, _b: b"conteudo-pfx")
    monkeypatch.setattr(
        ic,
        "_import_pfx_non_exportable",
        lambda pfx, senha: (chamadas.append(senha) or (True, "ok")),
    )

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"certificates": [item]}

    class _Cli:
        def post(self, *a, **k):
            return _Resp()

    ic.process_install_command(_Cli(), "http://portal", {}, "token", source_dir="F:/certs")
    return chamadas


def test_usa_a_senha_do_arquivo_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """O caso que estava quebrado: senha vinha vazia e o certutil recusava."""
    chamadas = _instalar(monkeypatch, {FP_A: "senhaCorreta"}, _bundle(FP_A))

    assert chamadas == ["senhaCorreta"]


def test_sem_senha_conhecida_nao_tenta_instalar(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Falhar nomeando a causa é melhor que deixar o certutil recusar.

    Antes, um PFX sem senha disponível ia para o certutil com `-p ""` e voltava
    "senha incorreta" — mensagem que manda investigar o certificado, quando o
    problema é que o arquivo não está na estação.
    """
    chamadas = _instalar(monkeypatch, {}, _bundle(FP_A))

    assert chamadas == [], "não pode chamar o certutil sem senha"


def test_bundle_antigo_com_senha_ainda_funciona(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Compatibilidade: registros anteriores ao endurecimento podem trazer
    `pfxPassword` preenchido, e nesse caso não há arquivo local a consultar.
    """
    chamadas: list = []
    monkeypatch.setattr(ic, "_senhas_por_fingerprint", lambda _d: {})
    monkeypatch.setattr(
        ic, "_decrypt_payload_ecdh",
        lambda _k, b: b"senhaAntiga" if b == {"cifrado": True} else b"conteudo-pfx",
    )
    monkeypatch.setattr(
        ic, "_import_pfx_non_exportable",
        lambda pfx, senha: (chamadas.append(senha) or (True, "ok")),
    )

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"certificates": [{
                "certificateId": "id-1",
                "fingerprint": FP_A,
                "pfxPassword": {"cifrado": True},
            }]}

    class _Cli:
        def post(self, *a, **k):
            return _Resp()

    ic.process_install_command(_Cli(), "http://portal", {}, "token", source_dir=None)

    assert chamadas == ["senhaAntiga"]


def test_arquivo_local_tem_precedencia_sobre_o_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    """A senha local é a verdade corrente; a do bundle é resquício."""
    chamadas = _instalar(
        monkeypatch,
        {FP_A: "senhaLocal"},
        {"certificateId": "id-1", "fingerprint": FP_A, "pfxPassword": {"cifrado": True}},
    )

    assert chamadas == ["senhaLocal"]
