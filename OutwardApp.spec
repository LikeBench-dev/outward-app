# -*- mode: python ; coding: utf-8 -*-

import os
import ssl
from pathlib import Path
from PySide6.QtCore import QLibraryInfo

from outward_app.app_info import APP_NAME


block_cipher = None
runtime_data = [('assets/outward.ico', 'assets'), ('assets/outward.png', 'assets'), ('VERSION', '.'),
                ('dist/OutwardVPNService', 'vpn-service'), ('assets/flags', 'assets/flags')]
runtime_data.append((str(Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)) / 'qtbase_ru.qm'),
                     'assets/translations'))
ssl_policy = Path(ssl.__file__).with_name('codex-rejected-cas.pem')
if ssl_policy.is_file():
    runtime_data.append((str(ssl_policy), '.'))


a = Analysis(
    ['outward_app/__main__.py'],
    pathex=[],
    binaries=[('bin/sing-box.exe', '.')],
    datas=runtime_data,
    hiddenimports=['PySide6.QtSvg'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

def exclude_bundled_binaries(toc, names):
    excluded = {name.lower() for name in names}
    return [entry for entry in toc if os.path.basename(entry[0]).lower() not in excluded]


# QtCore should load the Windows ICU DLLs. The Codex/Poppler ICU DLLs can be
# picked up by PyInstaller and have suffixed exports, which breaks PySide6.
a.binaries = exclude_bundled_binaries(a.binaries, {"icudt78.dll", "icuuc.dll"})
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
