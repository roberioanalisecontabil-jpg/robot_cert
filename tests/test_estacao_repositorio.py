"""Repositorio do Windows na bandeja: listar e remover, com PowerShell falso."""

import base64
import hashlib
import json
from types import SimpleNamespace

from estacao import repositorio

THUMB = "A" * 40
DER = b"\x30\x82\x01\x0aconteudo-der"


def _ok(obj):
    return SimpleNamespace(returncode=0, stdout=json.dumps(obj), stderr="")


def _linha(thumb=THUMB, subject="CN=EMPRESA LTDA:12345678000199, O=ICP-Brasil"):
    return {"Thumbprint": thumb, "Subject": subject, "Raw": base64.b64encode(DER).decode()}


def test_listar_calcula_sha256_do_der():
    itens = repositorio.listar(lambda s: _ok([_linha(), _linha("B" * 40, "OU=sem cn")]))
    assert itens[0] == repositorio.Item(
        sha256=hashlib.sha256(DER).hexdigest(),
        thumbprint=THUMB,
        nome="EMPRESA LTDA:12345678000199",
    )
    assert itens[1].nome == "OU=sem cn"


def test_listar_falha_devolve_vazio():
    falha = SimpleNamespace(returncode=1, stdout="", stderr="erro")
    assert repositorio.listar(lambda s: falha) == []

    def explode(s):
        raise OSError("sem powershell")

    assert repositorio.listar(explode) == []
    assert repositorio.listar(lambda s: SimpleNamespace(returncode=0, stdout="", stderr="")) == []


def test_listar_um_item_so():
    itens = repositorio.listar(lambda s: _ok(_linha()))
    assert len(itens) == 1 and itens[0].thumbprint == THUMB


def test_remover_monta_comando_com_delete_key():
    vistos = []

    def fake(script):
        vistos.append(script)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    item = repositorio.Item(sha256="x", thumbprint=THUMB.lower(), nome="n")
    assert repositorio.remover(item, fake) == (True, "")
    assert f'Remove-Item -LiteralPath "Cert:\\CurrentUser\\My\\{THUMB}" -DeleteKey -ErrorAction Stop' in vistos[0]

    ruim = SimpleNamespace(returncode=1, stdout="", stderr="  negado  ")
    assert repositorio.remover(item, lambda s: ruim) == (False, "negado")


def test_remover_thumbprint_invalido_nao_executa():
    def nao_deve(script):
        raise AssertionError("executou")

    for t in ("", "ZZ" * 20, THUMB + '"; calc', "A" * 39):
        item = repositorio.Item(sha256="x", thumbprint=t, nome="n")
        assert repositorio.remover(item, nao_deve) == (False, "thumbprint inválido")
