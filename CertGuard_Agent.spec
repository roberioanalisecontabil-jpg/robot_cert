# -*- mode: python ; coding: utf-8 -*-


import os

REPO = os.path.abspath(".")

a = Analysis(
    ['agent\\run_agent.py'],
    pathex=[REPO, os.path.join(REPO, "agent")],
    binaries=[],
    datas=[
        # Inclui o pacote app/ inteiro para que app.cert_scanner seja encontrado
        (os.path.join(REPO, "app"), "app"),
    ],
    hiddenimports=[
        "app",
        "app.cert_scanner",
        'watchdog',
        'watchdog.events',
        'watchdog.observers',
        'pystray',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        "httpx",
        "httpx._transports",
        "httpx._transports.default",
        "httpcore",
        "h11",
        "certifi",
        "dotenv",
        "cryptography",
        "cryptography.hazmat.primitives",
        "cryptography.hazmat.primitives.hashes",
        "cryptography.hazmat.primitives.serialization",
        "cryptography.hazmat.primitives.serialization.pkcs12",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='CertGuard_Agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
