# -*- mode: python ; coding: utf-8 -*-

import os

from outward_app.app_info import APP_NAME


block_cipher = None


a = Analysis(
    ['outward_app/__main__.py'],
    pathex=[],
    binaries=[('bin/sing-box.exe', '.')],
    datas=[('assets/outward.ico', 'assets'), ('assets/outward.png', 'assets'), ('VERSION', '.')],
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
    name=APP_NAME,
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
    icon=['assets/outward.ico'],
    version=os.environ.get('APP_VERSION_INFO'),
)

