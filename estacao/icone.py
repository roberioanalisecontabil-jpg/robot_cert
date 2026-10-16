"""Ícone do Certguard Análise: o C dourado (ico/certguard.png e .ico, 15/10/2026).

O mesmo desenho serve à bandeja, às janelas de login e de status, ao
executável (CertguardAnalise.spec, `icon=`) e ao instalador
(estacao_setup.iss, SetupIconFile). No executável os dois arquivos vão como
`datas` em `ico/`, dentro do _MEIPASS. O ico/icone.ico (o A da Análise)
continua sendo o do portal e do agente do servidor.

Se o arquivo faltar, a bandeja não pode ficar sem ícone (o pystray não sobe
sem um): `imagem()` cai num quadrado em vez de derrubar o programa.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def caminho(extensao: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "ico" / f"certguard.{extensao}"


def imagem():
    """PIL.Image para o pystray."""
    from PIL import Image

    try:
        img = Image.open(caminho("png"))
        img.load()
        return img
    except Exception:
        logger.warning("Ícone não encontrado; usando um quadrado.")
        return Image.new("RGB", (64, 64), (0, 120, 215))


def aplicar_na_janela(raiz) -> None:
    """Ícone da barra de título e de tarefas de uma janela Tk; sem ele, a pena do Tk."""
    try:
        raiz.iconbitmap(default=str(caminho("ico")))
    except Exception:
        pass
