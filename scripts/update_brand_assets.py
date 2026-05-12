"""
Gera os assets de marca (logo PNG transparente + favicon multi-tamanho)
a partir de uma imagem-fonte com fundo preto liso.

Uso:
  python scripts/update_brand_assets.py CAMINHO_DA_IMAGEM

Saídas:
  static/logo.png          quadrado, 1024x1024, fundo transparente
  ico/icone.ico            multi-tamanho (16/24/32/48/64/128/256)
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"
ICO_DIR = ROOT / "ico"

# Pixels com luminância <= este valor (em 0..255) viram transparentes.
# A logo da AG tem fundo preto liso, então um corte baixo evita comer o azul.
BLACK_CUTOFF = 24


def transparentize_black(img: Image.Image) -> Image.Image:
    """Converte pixels quase-pretos para transparentes; preserva o resto."""
    img = img.convert("RGBA")
    pixels = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if max(r, g, b) <= BLACK_CUTOFF:
                pixels[x, y] = (0, 0, 0, 0)
    return img


def square_pad(img: Image.Image, size: int = 1024) -> Image.Image:
    """Encaixa a imagem num canvas quadrado transparente, mantendo proporção."""
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    src = img.copy()
    src.thumbnail((size, size), Image.LANCZOS)
    off_x = (size - src.width) // 2
    off_y = (size - src.height) // 2
    canvas.paste(src, (off_x, off_y), src)
    return canvas


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)

    source = Path(sys.argv[1]).expanduser()
    if not source.is_file():
        print(f"Imagem-fonte nao encontrada: {source}", file=sys.stderr)
        sys.exit(2)

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    ICO_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Lendo {source} ...")
    src = Image.open(source)
    print(f"  origem: {src.size} {src.mode}")

    transp = transparentize_black(src)
    squared = square_pad(transp, size=1024)

    logo_out = STATIC_DIR / "logo.png"
    squared.save(logo_out, format="PNG", optimize=True)
    print(f"  -> {logo_out} ({squared.size})")

    ico_out = ICO_DIR / "icone.ico"
    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    squared.save(ico_out, format="ICO", sizes=ico_sizes)
    print(f"  -> {ico_out} (sizes: {ico_sizes})")


if __name__ == "__main__":
    main()
