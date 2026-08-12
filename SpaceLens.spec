# -*- mode: python ; coding: utf-8 -*-

import sys

icon_file = "packaging/icons/SpaceLens.ico" if sys.platform == "win32" else "packaging/icons/SpaceLens.png"

a = Analysis(
    ["local_server.py"],
    pathex=[],
    binaries=[],
    datas=[("local", "local")],
    hiddenimports=[],
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
    name="SpaceLens",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    icon=icon_file,
)
