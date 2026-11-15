"""Contêiner da chave e SID (Frente C). O teste real só lê: não pode abrir chave."""

from __future__ import annotations

import logging
import re

import pytest

from estacao import conteineres
from tests.test_estacao import so_windows


@so_windows
def test_conteineres_le_o_repositorio_real(caplog: pytest.LogCaptureFixture) -> None:
    # conteineres() engole a exceção e devolve {}: só o log mostra regressão no ctypes.
    with caplog.at_level(logging.ERROR, logger=conteineres.LOGGER.name):
        mapa = conteineres.conteineres()
    assert "leitura falhou" not in caplog.text
    assert isinstance(mapa, dict)
    assert all(re.fullmatch(r"[0-9a-f]{64}", k) and v for k, v in mapa.items())


@so_windows
def test_sid_atual_tem_formato_de_sid() -> None:
    assert re.fullmatch(r"S-1-\d+(-\d+)+", conteineres.sid_atual())
