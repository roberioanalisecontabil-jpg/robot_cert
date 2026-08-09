"""Instalação do PFX na estação: manuseio do arquivo temporário.

`_import_pfx_non_exportable` grava o PFX decifrado em disco para entregá-lo ao
`certutil`, porque certutil lê de arquivo — não de stdin. Esse arquivo é, por
alguns instantes, uma chave privada em claro no disco da estação. O que o
código faz com ele depois é a parte crítica, e não tinha teste nenhum.

`subprocess.run` é substituído em todos os testes: rodar certutil de verdade
importaria certificados no repositório do Windows de quem roda a suíte.

O que estes testes NÃO cobrem, e por quê:

- A importação em si (se o Windows realmente marca a chave como não-exportável)
  depende do certutil e do repositório do usuário. Verificável só numa estação
  real, com um PFX real.
- Permissões POSIX não existem no Windows, e o código não define ACL alguma:
  confia no `tempfile.mkdtemp`, que cria o diretório acessível só ao usuário
  corrente. O que dá para afirmar em teste é que o arquivo não sobrevive à
  chamada — é essa a garantia que o código realmente oferece.
"""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.installer_client import _import_pfx_non_exportable

PFX_FALSO = b"\x30\x82\x0a\x2f conteudo que representa uma chave privada \xff\x00" * 20


class _ResultadoFake:
    def __init__(self, returncode: int = 0, stdout: str = "ok", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _capturando_chamada(registro: list, returncode: int = 0):
    """Substitui subprocess.run e fotografa o estado do arquivo temporário."""

    def fake_run(cmd, **kwargs):  # noqa: ANN001, ARG001
        caminho = Path(cmd[-2])  # penúltimo argumento é o caminho do .pfx
        registro.append(
            {
                "cmd": list(cmd),
                "caminho": caminho,
                "existia_durante": caminho.is_file(),
                "conteudo_durante": caminho.read_bytes() if caminho.is_file() else None,
                "dir": caminho.parent,
            }
        )
        return _ResultadoFake(returncode=returncode)

    return fake_run


def test_pfx_e_entregue_ao_certutil_e_apagado_depois() -> None:
    registro: list = []
    with patch.object(subprocess, "run", _capturando_chamada(registro)):
        ok, detalhe = _import_pfx_non_exportable(PFX_FALSO, "senha123")

    assert ok, detalhe
    assert len(registro) == 1
    chamada = registro[0]

    # Durante a chamada, o arquivo existe e tem o conteúdo certo.
    assert chamada["existia_durante"]
    assert chamada["conteudo_durante"] == PFX_FALSO

    # Depois, nem o arquivo nem o diretório sobrevivem.
    assert not chamada["caminho"].exists(), "o PFX ficou no disco da estação"
    assert not chamada["dir"].exists(), "o diretório temporário ficou para trás"


def test_arquivo_e_sobrescrito_antes_de_remover() -> None:
    """
    O código zera o arquivo antes do `os.remove` — apagar só desvincula o nome,
    deixando os bytes recuperáveis no disco. Este teste fotografa o conteúdo no
    momento exato do `os.remove` para provar que a sobrescrita aconteceu.
    """
    visto: dict = {}
    remove_real = os.remove

    def remove_espiao(caminho, *a, **k):  # noqa: ANN001
        p = Path(caminho)
        if p.suffix == ".pfx" and p.is_file():
            visto["conteudo_no_remove"] = p.read_bytes()
        return remove_real(caminho, *a, **k)

    with patch.object(subprocess, "run", _capturando_chamada([])):
        with patch.object(os, "remove", remove_espiao):
            ok, _ = _import_pfx_non_exportable(PFX_FALSO, "senha123")

    assert ok
    conteudo = visto.get("conteudo_no_remove")
    assert conteudo is not None, "o arquivo não foi removido pelo caminho esperado"
    assert conteudo != PFX_FALSO, "removido sem sobrescrever: bytes recuperáveis"
    assert set(conteudo) == {0}, "a sobrescrita tem de ser com zeros"
    assert len(conteudo) == len(PFX_FALSO), "tamanho preservado na sobrescrita"


def test_importa_como_nao_exportavel_no_repositorio_do_usuario() -> None:
    """A garantia central do módulo: a chave não sai da estação depois."""
    registro: list = []
    with patch.object(subprocess, "run", _capturando_chamada(registro)):
        _import_pfx_non_exportable(PFX_FALSO, "senha123")

    cmd = registro[0]["cmd"]
    assert cmd[0] == "certutil"
    assert "NoExport" in cmd, "sem NoExport a chave privada vira exportável"
    assert "-user" in cmd, "tem de ir para o repositório do usuário, não da máquina"
    assert "My" in cmd


def test_falha_do_certutil_nao_deixa_o_pfx_no_disco() -> None:
    """
    O caminho de erro é o que mais importa: é onde limpeza costuma escapar.
    A remoção está num `finally`, e este teste fixa isso.
    """
    registro: list = []
    with patch.object(subprocess, "run", _capturando_chamada(registro, returncode=1)):
        ok, detalhe = _import_pfx_non_exportable(PFX_FALSO, "senha123")

    assert not ok
    assert "Certutil falhou" in detalhe
    assert not registro[0]["caminho"].exists()
    assert not registro[0]["dir"].exists()


def test_excecao_no_meio_tambem_limpa() -> None:
    """Timeout do certutil, permissão negada — o `finally` vale para todos."""
    caminhos: list = []

    def run_que_explode(cmd, **kwargs):  # noqa: ANN001, ARG001
        caminhos.append(Path(cmd[-2]))
        raise subprocess.TimeoutExpired(cmd, 30)

    with patch.object(subprocess, "run", run_que_explode):
        ok, _ = _import_pfx_non_exportable(PFX_FALSO, "senha123")

    assert not ok
    assert caminhos and not caminhos[0].exists()
    assert not caminhos[0].parent.exists()


def test_duas_instalacoes_seguidas_nao_deixam_residuo() -> None:
    """
    Idempotência do lado do disco: instalar o mesmo certificado duas vezes não
    acumula diretórios temporários nem reaproveita caminho.

    (Idempotência dentro do repositório do Windows é do certutil, com `-f`, e
    não é observável daqui.)
    """
    registro: list = []
    with patch.object(subprocess, "run", _capturando_chamada(registro)):
        ok1, _ = _import_pfx_non_exportable(PFX_FALSO, "senha123")
        ok2, _ = _import_pfx_non_exportable(PFX_FALSO, "senha123")

    assert ok1 and ok2
    assert len(registro) == 2

    d1, d2 = registro[0]["dir"], registro[1]["dir"]
    assert d1 != d2, "cada instalação usa diretório próprio"
    assert not d1.exists() and not d2.exists(), "nenhum resíduo após as duas"


def test_diretorio_temporario_fica_na_area_privada_do_usuario() -> None:
    """
    O código confia no `tempfile.mkdtemp` para o isolamento — não define ACL.
    Este teste fixa ao menos que o arquivo nasce na área temporária privada e
    com o prefixo esperado, em vez de num caminho compartilhado.
    """
    import tempfile

    registro: list = []
    with patch.object(subprocess, "run", _capturando_chamada(registro)):
        _import_pfx_non_exportable(PFX_FALSO, "senha123")

    d = registro[0]["dir"]
    assert d.name.startswith("cert_inst_")
    assert str(d).startswith(str(Path(tempfile.gettempdir())))


@pytest.mark.parametrize("senha", ["", None])
def test_senha_vazia_nao_quebra_a_chamada(senha) -> None:  # noqa: ANN001
    """PFX sem senha é caso real; o código normaliza para string vazia."""
    registro: list = []
    with patch.object(subprocess, "run", _capturando_chamada(registro)):
        ok, _ = _import_pfx_non_exportable(PFX_FALSO, senha)

    assert ok
    assert "-p" in registro[0]["cmd"]
