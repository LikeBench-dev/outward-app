# The SYSTEM service runs from a protected onedir bundle, never a temporary onefile directory.
import os
import ssl
from pathlib import Path

ssl_policy = Path(ssl.__file__).with_name('codex-rejected-cas.pem')
runtime_data = [('VERSION', '.')]
if ssl_policy.is_file():
    runtime_data.append((str(ssl_policy), '.'))

a = Analysis(
    ['outward_app/vpn_service_entry.py'], pathex=[], binaries=[], datas=runtime_data,
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['PySide6', 'qfluentwidgets'], noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name='OutwardVPNService',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=True, disable_windowed_traceback=False,
    version=os.environ.get('APP_VERSION_INFO'),
)
collect = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='OutwardVPNService')
