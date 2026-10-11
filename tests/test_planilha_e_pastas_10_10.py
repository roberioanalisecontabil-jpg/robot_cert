"""Auditoria de 10/10/2026: bomba de zip no .xlsx da carteira e UNC pelas
formas mistas de separador."""

import io
import zipfile

import pytest
from fastapi import HTTPException

from app import config
from app.rotas import carteiras
from app.settings_state import PastaRecusada, _e_unc, validar_pasta


def _xlsx_com(parte: str, tamanho: int, conteudo: bytes = b" ") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr(parte, b"<a>" + (conteudo * (tamanho // len(conteudo) + 1))[:tamanho] + b"</a>")
    return buf.getvalue()


def test_xlsx_que_expande_demais_e_recusado_antes_do_openpyxl() -> None:
    bomba = _xlsx_com("xl/sharedStrings.xml", 60 * 1024 * 1024)
    assert len(bomba) < 1024 * 1024, "comprimido é pequeno"
    with pytest.raises(HTTPException) as e:
        carteiras._linhas_da_planilha("c.xlsx", bomba)
    assert e.value.status_code == 422 and "grande demais" in e.value.detail


def test_xlsx_normal_passa_pela_conferencia() -> None:
    import os

    carteiras._conferir_zip_do_xlsx(_xlsx_com("xl/worksheets/sheet1.xml", 10_000, os.urandom(4096)))


@pytest.mark.parametrize("p", [r"\\host\share", "//host/share", r"\/host/share", r"/\host\share"])
def test_todas_as_formas_de_unc(p: str) -> None:
    assert _e_unc(p)


@pytest.mark.parametrize("p", [r"\/atacante/share", r"/\atacante\share"])
def test_unc_misto_recusado_sem_tocar_a_rede(p: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "PASTAS_PERMITIDAS", [], raising=False)
    from pathlib import Path

    def _nao_resolve(*_a, **_k):
        raise AssertionError("resolve() tocaria o host")

    monkeypatch.setattr(Path, "resolve", _nao_resolve)
    with pytest.raises(PastaRecusada):
        validar_pasta(p, "Pasta de origem")
