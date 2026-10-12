"""A senha do PFX mora no nome do arquivo ("EMPRESA senha 123456.pfx"), e o
texto de um erro de sistema traz o caminho completo. Auditoria run-2
(12/10/2026): o nome saía limpo nos campos de arquivo, mas a mensagem de erro
levava a senha para o inventário (lista do Início, para qualquer logado), o
relatório da entrada, o banco e o e-mail do administrador."""

from pathlib import Path

import pytest

from agent import entrada as ag
from app import entrada as pe
from app import nome_publico
from app.cert_scanner import scan_folder
from tests.test_entrada_certificados import CNPJ, _pfx, pastas  # noqa: F401

SENHA = "segredo42"
ERRO_COM_CAMINHO = PermissionError(13, "Acesso negado", rf"F:\CERT\EMPRESA senha {SENHA}.pfx", None,
                                   rf"F:\CERT\A\EMPRESA senha {SENHA}.pfx")


def test_mensagem_de_erro_com_caminho_vira_texto_fixo() -> None:
    assert SENHA not in nome_publico.mensagem_sem_arquivo(str(ERRO_COM_CAMINHO))
    assert SENHA not in nome_publico.mensagem_sem_arquivo(f"falhou em EMPRESA senha {SENHA}.pfx")
    # Mensagens de biblioteca, sem caminho, continuam úteis.
    assert nome_publico.mensagem_sem_arquivo("Senha incorreta") == "Senha incorreta"
    assert nome_publico.mensagem_sem_arquivo("Could not deserialize PKCS12 data") == "Could not deserialize PKCS12 data"


def test_scanner_nao_guarda_o_caminho_no_error_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / f"EMPRESA senha {SENHA}.pfx").write_bytes(b"x")

    def _nega(self):
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "read_bytes", _nega)
    (item,) = scan_folder(tmp_path)
    assert item.error_message and SENHA not in item.error_message and "\\" not in item.error_message


def test_inventario_de_agente_antigo_chega_limpo() -> None:
    item = {"file_name": f"EMPRESA senha {SENHA}.pfx", "status": "erro", "error_message": str(ERRO_COM_CAMINHO)}
    limpo = nome_publico.sanitizar_item(item)
    assert SENHA not in str(limpo)


def test_relatorio_da_entrada_de_agente_antigo_chega_limpo() -> None:
    linha = pe._linha("srv", {"resultado": "pendente", "arquivo_original": "EMPRESA", "motivo": f"Não foi possível mover o arquivo: {ERRO_COM_CAMINHO}"}, pendente=True)
    assert SENHA not in linha["motivo"]


def test_agente_nao_poe_o_erro_cru_no_motivo(pastas, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    _pfx(pastas.pasta_entrada, f"ALFA 1 senha {SENHA}.pfx", cnpj=CNPJ, senha=SENHA, nome="ALFA")

    def _falha(src, dst):
        raise PermissionError(13, "Acesso negado", str(src), None, str(dst))

    monkeypatch.setattr(ag.shutil, "move", _falha)
    r = ag.processar_entrada(pastas)
    assert r["pendentes"], r
    assert all(SENHA not in str(p) for p in r["pendentes"]), r["pendentes"]
