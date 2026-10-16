"""Ícone do Certguard Análise: o C dourado (15/10/2026, estacao/icone.py)."""
from pathlib import Path

from PIL import Image

from estacao import icone

RAIZ = Path(__file__).resolve().parent.parent


def test_arquivos_existem_com_transparencia_e_tamanhos():
    png = Image.open(icone.caminho("png"))
    assert png.mode == "RGBA" and png.getpixel((0, 0))[3] == 0  # fundo preto virou transparente
    tamanhos = Image.open(icone.caminho("ico")).info["sizes"]
    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= set(tamanhos)


def test_bandeja_recebe_o_png():
    img = icone.imagem()
    assert img.size == (512, 512)


def test_sem_arquivo_a_bandeja_ainda_tem_icone(monkeypatch, tmp_path):
    monkeypatch.setattr(icone, "caminho", lambda ext: tmp_path / f"nada.{ext}")
    assert icone.imagem().size == (64, 64)


def test_exe_e_instalador_usam_o_mesmo_icone():
    spec = (RAIZ / "CertguardAnalise.spec").read_text(encoding="utf-8")
    assert 'icon=os.path.join(REPO, "ico", "certguard.ico")' in spec
    assert '"certguard.png"), "ico")' in spec and '"certguard.ico"), "ico")' in spec
    assert "SetupIconFile=ico\certguard.ico" in (RAIZ / "estacao_setup.iss").read_text(encoding="utf-8")
