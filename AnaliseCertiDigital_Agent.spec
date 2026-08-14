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
        # Módulo instalador (03/08). É importado tarde, dentro das funções de
        # run_agent, e a pasta agent/ não era um pacote — duas razões para o
        # PyInstaller não o alcançar sozinho. Sem ele o agente empacotado nunca
        # consulta /vault-optin nem instala nada: o recurso simplesmente não
        # existe no executável, sem erro visível.
        "agent",
        "agent.installer_client",
        # Janela de status da bandeja. Importada tarde, dentro do handler do
        # menu — o PyInstaller não a alcança pela análise estática, e sem estas
        # entradas o item "Status do serviço" falharia só ao ser clicado, no
        # executável empacotado, sem sintoma nenhum antes disso.
        "agent.janela_status",
        "tkinter",
        "tkinter.ttk",
        "app.cert_installer",
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
        # Primitivas do transporte do instalador: ECDH P-256, AES-256-GCM e
        # HKDF. Nenhuma era usada antes de 03/08.
        "cryptography.hazmat.primitives.asymmetric.ec",
        "cryptography.hazmat.primitives.asymmetric.utils",
        "cryptography.hazmat.primitives.ciphers.aead",
        "cryptography.hazmat.primitives.kdf.hkdf",
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
    name='AnaliseCertiDigital_Agent',
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
    icon=os.path.join(REPO, "ico", "icone.ico"),
)
