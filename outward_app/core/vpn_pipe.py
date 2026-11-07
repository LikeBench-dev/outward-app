"""Small, local-only, owner-ACL named pipe transport. JSON, never pickle or shell commands."""
from __future__ import annotations

import ctypes
from ctypes import wintypes as W
import json
import os
import time

PIPE_NAME = r"\\.\pipe\OutwardAppVPN-v1"
SERVICE_NAME = "OutwardAppVPN"
PROTOCOL_VERSION = 1
MAX_MESSAGE = 65536


def api():
    if os.name != "nt":
        raise OSError("Системный VPN поддерживается только в Windows")
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateNamedPipeW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, W.DWORD, W.DWORD, W.DWORD, W.DWORD, ctypes.c_void_p]
    k.CreateNamedPipeW.restype = W.HANDLE
    k.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, ctypes.c_void_p, W.DWORD, W.DWORD, W.HANDLE]
    k.CreateFileW.restype = W.HANDLE
    for name in ("CloseHandle", "DisconnectNamedPipe"):
        getattr(k, name).argtypes = [W.HANDLE]
    k.ConnectNamedPipe.argtypes = [W.HANDLE, ctypes.c_void_p]
    k.ReadFile.argtypes = [W.HANDLE, ctypes.c_void_p, W.DWORD, ctypes.POINTER(W.DWORD), ctypes.c_void_p]
    k.WriteFile.argtypes = k.ReadFile.argtypes
    k.GetNamedPipeServerProcessId.argtypes = [W.HANDLE, ctypes.POINTER(W.ULONG)]
    k.GetNamedPipeClientProcessId.argtypes = [W.HANDLE, ctypes.POINTER(W.ULONG)]
    k.SetNamedPipeHandleState.argtypes = [W.HANDLE, ctypes.POINTER(W.DWORD), ctypes.c_void_p, ctypes.c_void_p]
    k.LocalFree.argtypes = [ctypes.c_void_p]
    return k


def service_status() -> tuple[int, int]:
    a = ctypes.WinDLL("advapi32", use_last_error=True)
    a.OpenSCManagerW.argtypes = [W.LPCWSTR, W.LPCWSTR, W.DWORD]
    a.OpenSCManagerW.restype = W.HANDLE
    a.OpenServiceW.argtypes = [W.HANDLE, W.LPCWSTR, W.DWORD]
    a.OpenServiceW.restype = W.HANDLE
    a.QueryServiceStatusEx.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD, ctypes.POINTER(W.DWORD)]
    a.CloseServiceHandle.argtypes = [W.HANDLE]
    scm = a.OpenSCManagerW(None, None, 1)
    if not scm:
        raise ctypes.WinError(ctypes.get_last_error())
    service = None
    try:
        service = a.OpenServiceW(scm, SERVICE_NAME, 4)
        if not service:
            if ctypes.get_last_error() == 1060:
                return (0, 0)
            raise OSError("Не установлена служба VPN. Откройте меню системного подключения и выберите «Установить службу системного VPN».")
        status = (W.DWORD * 9)()
        needed = W.DWORD()
        if not a.QueryServiceStatusEx(service, 0, status, ctypes.sizeof(status), ctypes.byref(needed)):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(status[1]), int(status[7])
    finally:
        if service:
            a.CloseServiceHandle(service)
        a.CloseServiceHandle(scm)


def service_pid() -> int:
    state, pid = service_status()
    if not state:
        raise OSError("Не установлена служба VPN. Откройте меню системного подключения и выберите «Установить службу системного VPN».")
    if state != 4 or not pid:
        raise OSError("Служба VPN не запущена. Обновите компонент VPN.")
    return pid


def request(payload: dict, timeout: float = 5) -> dict:
    k = api()
    expected_pid = service_pid()
    raw = json.dumps({"version": PROTOCOL_VERSION, **payload}, ensure_ascii=False).encode("utf-8")
    if len(raw) >= MAX_MESSAGE:
        raise ValueError("Слишком большой запрос VPN")
    deadline = time.monotonic() + timeout
    while True:
        handle = k.CreateFileW(PIPE_NAME, 0xC0000000, 0, None, 3, 0, None)
        if handle != ctypes.c_void_p(-1).value:
            break
        if ctypes.get_last_error() not in (2, 231) or time.monotonic() >= deadline:
            raise OSError("Компонент VPN недоступен. Проверьте установку службы.")
        time.sleep(.02)
    try:
        actual_pid = W.ULONG()
        if not k.GetNamedPipeServerProcessId(handle, ctypes.byref(actual_pid)) or actual_pid.value != expected_pid:
            raise OSError("Не удалось подтвердить владельца канала VPN")
        mode = W.DWORD(3)  # message read mode + nonblocking: bounded read timeout
        if not k.SetNamedPipeHandleState(handle, ctypes.byref(mode), None, None):
            raise ctypes.WinError(ctypes.get_last_error())
        count = W.DWORD()
        if not k.WriteFile(handle, raw, len(raw), ctypes.byref(count), None) or count.value != len(raw):
            raise OSError("Не удалось отправить запрос службе VPN")
        deadline = time.monotonic() + timeout
        buffer = ctypes.create_string_buffer(MAX_MESSAGE)
        while time.monotonic() < deadline:
            if k.ReadFile(handle, buffer, len(buffer), ctypes.byref(count), None):
                response = json.loads(buffer.raw[:count.value].decode("utf-8"))
                if response.get("version") != PROTOCOL_VERSION:
                    raise OSError("Версии приложения и службы VPN несовместимы. Обновите компонент.")
                if response.get("error"):
                    raise OSError(response["error"])
                return response
            error = ctypes.get_last_error()
            if error not in (232, 536):
                raise OSError("Служба VPN закрыла соединение")
            time.sleep(0.02)
        raise TimeoutError("Служба VPN не ответила")
    finally:
        k.CloseHandle(handle)


class PipeServer:
    def __init__(self, owner_sid: str):
        self.k = api()
        class Security(ctypes.Structure):
            _fields_ = [("length", W.DWORD), ("descriptor", ctypes.c_void_p), ("inherit", W.BOOL)]
        descriptor = ctypes.c_void_p()
        a = ctypes.WinDLL("advapi32", use_last_error=True)
        a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [W.LPCWSTR, W.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        # Only SYSTEM, administrators and the installing user. Reject remote clients at pipe creation too.
        sddl = f"D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GRGW;;;{owner_sid})"
        if not a.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            security = Security(ctypes.sizeof(Security), descriptor, False)
            self.handle = self.k.CreateNamedPipeW(PIPE_NAME, 3 | 0x80000, 4 | 2 | 1 | 8,
                                                 1, MAX_MESSAGE, MAX_MESSAGE, 1000, ctypes.byref(security))
            if self.handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.k.LocalFree(descriptor)

    def serve_once(self, handler, stop):
        if not self.k.ConnectNamedPipe(self.handle, None) and ctypes.get_last_error() not in (535,):
            return
        try:
            deadline = time.monotonic() + 3
            buffer = ctypes.create_string_buffer(MAX_MESSAGE)
            count = W.DWORD()
            while not stop.is_set() and time.monotonic() < deadline:
                if self.k.ReadFile(self.handle, buffer, len(buffer), ctypes.byref(count), None):
                    pid = W.ULONG()
                    if not self.k.GetNamedPipeClientProcessId(self.handle, ctypes.byref(pid)):
                        return
                    try:
                        payload = json.loads(buffer.raw[:count.value].decode("utf-8"))
                        response = handler(payload, int(pid.value))
                    except Exception:
                        response = {"error": "Некорректный запрос службы VPN"}
                    raw = json.dumps({"version": PROTOCOL_VERSION, **response}, ensure_ascii=False).encode("utf-8")
                    self.k.WriteFile(self.handle, raw[:MAX_MESSAGE - 1], min(len(raw), MAX_MESSAGE - 1), ctypes.byref(count), None)
                    # Disconnect only after the client consumes the reply and closes its handle.
                    # A bounded nonblocking read avoids both dropped replies and a stuck client.
                    deadline = time.monotonic() + 3
                    while not stop.is_set() and time.monotonic() < deadline:
                        if not self.k.ReadFile(self.handle, buffer, len(buffer), ctypes.byref(count), None):
                            if ctypes.get_last_error() not in (232, 536):
                                break
                        stop.wait(0.01)
                    return
                if ctypes.get_last_error() not in (232, 536):
                    return
                stop.wait(0.02)
        finally:
            self.k.DisconnectNamedPipe(self.handle)

    def close(self):
        self.k.CloseHandle(self.handle)
