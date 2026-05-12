# -*- mode: python ; coding: utf-8 -*-
# Executável hospedeiro SCM (Serviços Windows): CertGuard_Agent_Service.exe
#
# Build: pyinstaller CertGuard_Service.spec --clean

import os

# Diretório raiz do repositório (onde este .spec vive)
REPO = os.path.abspath(".")

a = Analysis(
    ["agent\\service_host.py"],
    pathex=[REPO, os.path.join(REPO, "agent")],
    binaries=[],
    datas=[
        # Inclui o pacote app/ inteiro para que app.cert_scanner seja encontrado
        (os.path.join(REPO, "app"), "app"),
        # Inclui run_agent.py ao lado do service_host no bundle
        (os.path.join(REPO, "agent", "run_agent.py"), "."),
    ],
    hiddenimports=[
        "run_agent",
        "app",
        "app.cert_scanner",
        "watchdog",
        "watchdog.events",
        "watchdog.observers",
        "pystray",
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
        "win32timezone",
        "win32service",
        "win32serviceutil",
        "win32event",
        "win32api",
        "servicemanager",
        "pywintypes",
        "pythoncom",
        # httpx e dependências usadas pelo run_agent
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
    [],
    exclude_binaries=True,
    name="CertGuard_Agent_Service",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(REPO, "ico", "icone.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="CertGuard_Agent_Service",
)
