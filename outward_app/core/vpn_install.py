from __future__ import annotations

import ctypes
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from outward_app.core.singbox import hidden_startupinfo
from outward_app.core.vpn_pipe import SERVICE_NAME, service_status
from outward_app.core.vpn_service import service_data, service_root
from outward_app.paths import bundled_dir


def user_sid() -> str:
    result = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, timeout=8,
                            startupinfo=hidden_startupinfo(), creationflags=subprocess.CREATE_NO_WINDOW)
    match = re.search(r"S-1-5-\d+(?:-\d+)+", result.stdout.decode("ascii", errors="ignore"))
    if not match:
        raise OSError("Не удалось определить пользователя Windows")
    return match.group()


def elevate_install(remove=False) -> None:
    if not getattr(sys, "frozen", False):
        raise OSError("Установка VPN-компонента доступна в собранном приложении. Соберите установщик Outward App.")
    arguments = ["--remove-vpn-service", user_sid()] if remove else ["--install-vpn-service", user_sid()]
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    class Execute(ctypes.Structure):
        _fields_ = [("size", W.DWORD), ("mask", W.ULONG), ("window", W.HWND), ("verb", W.LPCWSTR),
                    ("file", W.LPCWSTR), ("parameters", W.LPCWSTR), ("directory", W.LPCWSTR), ("show", ctypes.c_int),
                    ("instance", W.HINSTANCE), ("idlist", ctypes.c_void_p), ("class_name", W.LPCWSTR),
                    ("class_key", W.HKEY), ("hotkey", W.DWORD), ("icon", W.HANDLE), ("process", W.HANDLE)]
    info = Execute()
    info.size, info.mask, info.verb = ctypes.sizeof(info), 0x40 | 0x400, "runas"
    info.file, info.parameters, info.show = sys.executable, subprocess.list2cmdline(arguments), 0
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(Execute)]
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        raise OSError("Установка компонента VPN отменена или отклонена Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    kernel.GetExitCodeProcess.argtypes = [W.HANDLE, ctypes.POINTER(W.DWORD)]
    kernel.CloseHandle.argtypes = [W.HANDLE]
    try:
        if kernel.WaitForSingleObject(info.process, 120000) != 0:
            raise TimeoutError("Установка компонента VPN еще выполняется. Повторите подключение позже.")
        code = W.DWORD()
        kernel.GetExitCodeProcess(info.process, ctypes.byref(code))
        if code.value:
            raise OSError("Не удалось установить VPN-компонент. Проверьте права администратора.")
    finally:
        kernel.CloseHandle(info.process)


def _run(arguments, *, check=True):
    result = subprocess.run(arguments, capture_output=True, timeout=30, startupinfo=hidden_startupinfo(),
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if check and result.returncode:
        raise OSError(f"Ошибка настройки службы Windows: {result.returncode}")
    return result


def _stop_service():
    _run(["sc.exe", "stop", SERVICE_NAME], check=False)
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        state, _ = service_status()
        if state in (0, 1):
            return
        time.sleep(0.5)
    raise TimeoutError("Служба VPN не остановилась. Ее файлы не изменены.")


def _protected_directory(path: Path):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetFileAttributesW.argtypes = [W.LPCWSTR]
    kernel.GetFileAttributesW.restype = W.DWORD
    a = ctypes.WinDLL("advapi32", use_last_error=True)
    a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [W.LPCWSTR, W.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    a.GetNamedSecurityInfoW.argtypes = [W.LPWSTR, ctypes.c_int, W.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                                      ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    a.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(W.LPWSTR)]
    a.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [ctypes.c_void_p, W.DWORD, W.DWORD, ctypes.POINTER(W.LPWSTR), ctypes.c_void_p]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    class Security(ctypes.Structure):
        _fields_ = [("length", W.DWORD), ("descriptor", ctypes.c_void_p), ("inherit", W.BOOL)]
    descriptor = ctypes.c_void_p()
    if not a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            "O:BAG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)", 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    kernel.CreateDirectoryW.argtypes = [W.LPCWSTR, ctypes.POINTER(Security)]
    try:
        security = Security(ctypes.sizeof(Security), descriptor, False)
        if not kernel.CreateDirectoryW(str(path), ctypes.byref(security)) and ctypes.get_last_error() != 183:
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.LocalFree(descriptor)
    if kernel.GetFileAttributesW(str(path)) & 0x400:
        raise OSError("Каталог VPN не может быть ссылкой или junction")
    owner, dacl, sd, string, acl_string = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p(), W.LPWSTR(), W.LPWSTR()
    try:
        if a.GetNamedSecurityInfoW(str(path), 1, 5, ctypes.byref(owner), None, ctypes.byref(dacl), None, ctypes.byref(sd)):
            raise OSError("Не удалось проверить владельца каталога VPN")
        if not a.ConvertSidToStringSidW(owner, ctypes.byref(string)) or string.value not in {"S-1-5-18", "S-1-5-32-544"}:
            # Do not elevate pre-created user-owned files/directories into trusted service code.
            raise OSError("Каталог VPN уже существует и принадлежит непривилегированному пользователю")
        if not dacl or not a.ConvertSecurityDescriptorToStringSecurityDescriptorW(sd, 1, 4, ctypes.byref(acl_string), None):
            raise OSError("Не удалось проверить разрешения каталога VPN")
        allowed = re.findall(r"\(A;[^)]*;;;([^;)]+)\)", acl_string.value)
        if not allowed or any(sid not in {"BA", "SY", "S-1-5-18", "S-1-5-32-544"} for sid in allowed):
            raise OSError("Каталог службы VPN имеет небезопасные разрешения")
    finally:
        if string:
            kernel.LocalFree(string)
        if sd:
            kernel.LocalFree(sd)
        if acl_string:
            kernel.LocalFree(acl_string)


def install(owner_sid: str):
    if not getattr(sys, "frozen", False) or not re.fullmatch(r"S-1-5-\d+(?:-\d+)+", owner_sid):
        raise ValueError("Invalid installation request")
    root, data = service_root(), service_data()
    _protected_directory(root)
    _protected_directory(data)
    manifest = data / "installation.json"
    if manifest.exists() and json.loads(manifest.read_text(encoding="utf-8")).get("owner_sid") != owner_sid:
        raise OSError("Компонент VPN установлен для другого пользователя Windows")
    _stop_service()
    payload = bundled_dir() / "vpn-service"
    if not (payload / "OutwardVPNService.exe").is_file():
        raise OSError("В сборке отсутствует отдельный компонент VPN")
    sources = [p for p in payload.rglob("*")]
    for source in sorted(sources, key=lambda p: len(p.parts)):
        target = root / source.relative_to(payload)
        if source.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
            raise OSError("Недопустимый путь в VPN-компоненте")
        if source.is_dir():
            _protected_directory(target)
            continue
        if target.exists() and (target.is_symlink() or target.stat().st_nlink > 1):
            raise OSError("Файл службы не может быть ссылкой")
        shutil.copy2(source, target)
        _set_admin_owner(target)
    kernel_target = root / "sing-box.exe"
    if kernel_target.exists() and (kernel_target.is_symlink() or kernel_target.stat().st_nlink > 1):
        raise OSError("Недопустимый файл сетевого ядра")
    shutil.copy2(bundled_dir() / "sing-box.exe", kernel_target)
    _set_admin_owner(kernel_target)
    manifest.write_text(json.dumps({"owner_sid": owner_sid, "version": 1}), encoding="utf-8")
    _set_admin_owner(manifest)
    executable = subprocess.list2cmdline([str(root / "OutwardVPNService.exe")])
    exists = _run(["sc.exe", "query", SERVICE_NAME], check=False).returncode == 0
    _run(["sc.exe", "config" if exists else "create", SERVICE_NAME, "binPath=", executable,
          "start=", "auto", "DisplayName=", "Outward App VPN"])
    _run(["sc.exe", "description", SERVICE_NAME, "Manages the Outward App system VPN. Local proxy windows run without this service."])
    _run(["sc.exe", "start", SERVICE_NAME])


def remove(owner_sid: str):
    manifest = service_data() / "installation.json"
    if manifest.exists() and json.loads(manifest.read_text(encoding="utf-8")).get("owner_sid") != owner_sid:
        raise OSError("Компонент VPN принадлежит другому пользователю Windows")
    _stop_service()
    _run(["sc.exe", "delete", SERVICE_NAME], check=False)
    # Keep directories and diagnostics; never recursively remove a computed system path.
    (service_data() / "runtime" / "config.json").unlink(missing_ok=True)


def _set_admin_owner(path: Path):
    a = ctypes.WinDLL("advapi32", use_last_error=True)
    a.ConvertStringSidToSidW.argtypes = [W.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    a.SetNamedSecurityInfoW.argtypes = [W.LPWSTR, ctypes.c_int, W.DWORD, ctypes.c_void_p,
                                      ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    sid = ctypes.c_void_p()
    if not a.ConvertStringSidToSidW("S-1-5-32-544", ctypes.byref(sid)):
        raise ctypes.WinError(ctypes.get_last_error())
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    try:
        result = a.SetNamedSecurityInfoW(str(path), 1, 1, sid, None, None, None)
        if result:
            raise OSError(f"Не удалось защитить файл службы: {result}")
    finally:
        kernel.LocalFree(sid)
