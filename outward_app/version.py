from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from outward_app.paths import app_dir, bundled_dir, source_root


def _trim_version(parts: tuple[int, int, int, int]) -> str:
    values = list(parts)
    while len(values) > 3 and values[-1] == 0:
        values.pop()
    return ".".join(str(part) for part in values)


def _windows_file_version(path: Path) -> str | None:
    if sys.platform != "win32" or not path.exists():
        return None
    try:
        size = ctypes.windll.version.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return None
        buffer = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(str(path), 0, size, buffer):
            return None
        value = ctypes.c_void_p()
        value_len = ctypes.c_uint()
        if not ctypes.windll.version.VerQueryValueW(buffer, "\\", ctypes.byref(value), ctypes.byref(value_len)):
            return None

        class VSFixedFileInfo(ctypes.Structure):
            _fields_ = [
                ("dwSignature", ctypes.c_uint32),
                ("dwStrucVersion", ctypes.c_uint32),
                ("dwFileVersionMS", ctypes.c_uint32),
                ("dwFileVersionLS", ctypes.c_uint32),
                ("dwProductVersionMS", ctypes.c_uint32),
                ("dwProductVersionLS", ctypes.c_uint32),
                ("dwFileFlagsMask", ctypes.c_uint32),
                ("dwFileFlags", ctypes.c_uint32),
                ("dwFileOS", ctypes.c_uint32),
                ("dwFileType", ctypes.c_uint32),
                ("dwFileSubtype", ctypes.c_uint32),
                ("dwFileDateMS", ctypes.c_uint32),
                ("dwFileDateLS", ctypes.c_uint32),
            ]

        fixed = ctypes.cast(value, ctypes.POINTER(VSFixedFileInfo)).contents
        if fixed.dwSignature != 0xFEEF04BD:
            return None
        parts = (
            fixed.dwFileVersionMS >> 16,
            fixed.dwFileVersionMS & 0xFFFF,
            fixed.dwFileVersionLS >> 16,
            fixed.dwFileVersionLS & 0xFFFF,
        )
        return _trim_version(parts)
    except Exception:
        return None


def _version_from_file(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def get_app_version() -> str:
    if getattr(sys, "frozen", False):
        resource_version = _windows_file_version(Path(sys.executable))
        if resource_version:
            return resource_version

    for base in (bundled_dir(), app_dir(), source_root()):
        version = _version_from_file(base / "VERSION")
        if version:
            return version

    return "0.1.0"
