# -*- mode: python ; coding: utf-8 -*-
#
# Instalador avulso — o .exe que o usuário baixa do portal.
#
# Console em vez de janela (`console=True`): quando a instalação falha, o motivo
# precisa estar visível. Este binário roda uma vez, na máquina de alguém que não
# tem o portal aberto para consultar; uma janela que fecha sozinha não deixaria
# nada. O `input()` no fim do main segura o console.
#
# Sem watchdog/pystray/PIL, que só existem para o agente residente.

import os

REPO = os.path.abspath(".")

a = Analysis(
    ['agent\\instalador_standalone.py'],
    pathex=[REPO, os.path.join(REPO, "agent")],
    binaries=[],
    datas=[
        # cert_scanner vem junto por ser importado por installer_client, de onde
        # reaproveitamos o ECDH e a chamada ao certutil.
        (os.path.join(REPO, "app"), "app"),
    ],
    hiddenimports=[
        "agent",
        "agent.installer_client",
        "app",
        "app.cert_scanner",
        "httpx",
        "httpx._transports",
        "httpx._transports.default",
        "httpcore",
        "h11",
        "certifi",
        "cryptography",
        "cryptography.hazmat.primitives",
        "cryptography.hazmat.primitives.hashes",
        "cryptography.hazmat.primitives.serialization",
        "cryptography.hazmat.primitives.serialization.pkcs12",
        "cryptography.hazmat.primitives.asymmetric.ec",
        "cryptography.hazmat.primitives.ciphers.aead",
        "cryptography.hazmat.primitives.kdf.hkdf",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "watchdog",
        "pystray",
        "PIL",
        "tkinter",
        "numpy",
        "scipy",
        "matplotlib",
    ],
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
    name='Instalar_Certificado',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(REPO, "ico", "icone.ico"),
)
