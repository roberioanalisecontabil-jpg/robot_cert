# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ["tools\\service_smoke\\smoke_service.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=[
        "win32timezone",
        "win32service",
        "win32serviceutil",
        "win32event",
        "win32api",
        "servicemanager",
        "pywintypes",
        "pythoncom",
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
    name="AnaliseCertiDigital_Smoke_Service",
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AnaliseCertiDigital_Smoke_Service",
)
