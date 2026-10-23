"""Grava um roteiro da apresentação direto no MP4 da wiki (1280x720, H.264, sem áudio).

Uso: python scripts/wiki_videos/gravar.py ROTEIRO SAIDA.mp4   (ROTEIRO = bandeja | vencimentos | login)

Faz o mesmo que o gravar_video.py da skill video-apresentacao (seekPara quadro a quadro, 30 qps), mas
fotografa já em 1280x720, salva os quadros em disco em blocos (navegador reaberto a cada bloco; dá para
retomar) e só depois codifica: cabe em máquina com pouca memória livre.
Requer: playwright (chromium) e ffmpeg no PATH.
"""
import functools
import shutil
import tempfile
import http.server
import subprocess
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

PASTA = Path(__file__).resolve().parent
FPS = 30
# Sem a barra de controles, o palco ocupa a janela inteira (sem faixas pretas nas laterais).
ESCONDE_PLAYER = '.controls,.big-play,.msg,.start{display:none!important} body{cursor:none} .player .viewport{bottom:0!important}'


BLOCO = 250  # quadros por navegador: numa sessão só, a gravação era morta perto do quadro 300


def _fotografar(base: str, roteiro: str, quadros: Path) -> float:
    """Salva os JPEG em `quadros`, reabrindo o navegador a cada BLOCO. Retoma do que já existe."""
    with sync_playwright() as p:
        i, n, total = 0, None, 0.0
        while n is None or i < n:
            nav = p.chromium.launch()
            pg = nav.new_page(viewport={'width': 1280, 'height': 720})
            pg.goto(f'{base}/{roteiro}.html?t=0')
            pg.add_style_tag(content=ESCONDE_PLAYER)
            pg.evaluate('ajustarEscala()')
            pg.wait_for_timeout(1500)
            total = pg.evaluate('SCENES.total')
            n = int(total * FPS)
            fim = min(i + BLOCO, n)
            for j in range(i, fim):
                arq = quadros / f'{j:05d}.jpg'
                if not arq.exists():
                    pg.evaluate(f'seekPara({j / FPS})')
                    arq.write_bytes(pg.screenshot(type='jpeg', quality=92))
            nav.close()
            print(f'{roteiro}: quadro {fim}/{n}', flush=True)
            i = fim
    return total


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    roteiro, saida = sys.argv[1], Path(sys.argv[2]).resolve()
    quadros = Path(tempfile.gettempdir()) / f'wiki-video-{roteiro}'
    quadros.mkdir(exist_ok=True)
    servidor = http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(PASTA)))
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    try:
        total = _fotografar(f'http://127.0.0.1:{servidor.server_address[1]}', roteiro, quadros)
    finally:
        servidor.shutdown()
    r = subprocess.run(
        ['ffmpeg', '-y', '-loglevel', 'error', '-framerate', str(FPS), '-i', str(quadros / '%05d.jpg'),
         '-an', '-c:v', 'libx264', '-preset', 'medium', '-crf', '28', '-tune', 'animation', '-threads', '1',
         '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(saida)])
    if r.returncode:
        sys.exit(f'ffmpeg saiu com {r.returncode}')
    shutil.rmtree(quadros)
    print(f'pronto: {saida} ({total:.1f} s)')


if __name__ == '__main__':
    main()
