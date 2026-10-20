# -*- mode: python ; coding: utf-8 -*-
# Certguard Análise — o agente de certificados das estações (estacao/, ADR 0003).
# Um exe só: sem argumento é a bandeja; --preparar-chave é o passo do instalador;
# --atualizacao e --atualizar são a atualização automática (estacao/tarefa.py).

import os

REPO = os.path.abspath(".")

a = Analysis(
    [os.path.join("estacao", "__main__.py")],
    pathex=[REPO],
    binaries=[],
    # C dourado (estacao/icone.py): bandeja, janelas, exe e instalador.
    datas=[(os.path.join(REPO, "ico", "certguard.png"), "ico"), (os.path.join(REPO, "ico", "certguard.ico"), "ico")],
    hiddenimports=[
        # Importados dentro das funções (menu, laço, --preparar-chave): a análise
        # estática não os alcança, e faltar um só aparece no clique, no exe.
        "estacao.bandeja",
        "estacao.icone",
        "estacao.conta",
        "estacao.chave_maquina",
        "estacao.instalador_certificado",
        "estacao.janela_login",
        "estacao.janela_status",
        "estacao.manifesto",
        "estacao.atualizador",
        "estacao.tarefa",
        "estacao.sessoes",
        "win32ts",
        "win32profile",
        "win32process",
        "win32con",
        "cryptography.hazmat.primitives.asymmetric.ed25519",
        "pystray",
        "pystray._win32",
        "PIL.Image",
        "tkinter",
        "tkinter.scrolledtext",
        "httpx",
        "psutil",
        "cryptography.hazmat.primitives.asymmetric.ec",
        "cryptography.hazmat.primitives.ciphers.aead",
        "cryptography.hazmat.primitives.kdf.hkdf",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # O portal não entra no exe: nada de estacao/ importa app/.
    excludes=["app", "agent", "fastapi", "starlette", "uvicorn", "psycopg", "openpyxl"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="certguard_analise",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(REPO, "ico", "certguard.ico"),
)
