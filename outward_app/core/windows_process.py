"""Keep managed children from surviving a crashed GUI or VPN service."""
from __future__ import annotations

import ctypes
from ctypes import wintypes as W
import os
from pathlib import Path
import subprocess
import sys


def _creation_time(kernel, handle):
    kernel.GetProcessTimes.argtypes = [W.HANDLE, ctypes.POINTER(W.FILETIME), ctypes.POINTER(W.FILETIME),
                                      ctypes.POINTER(W.FILETIME), ctypes.POINTER(W.FILETIME)]
    times = [W.FILETIME() for _ in range(4)]
    if not kernel.GetProcessTimes(handle, *[ctypes.byref(value) for value in times]):
        raise ctypes.WinError(ctypes.get_last_error())
    return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime


def signal_console_child(pid: int, created: int) -> int:
    """Run in a short-lived helper, never detach the GUI/user terminal's console."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    kernel.OpenProcess.restype = W.HANDLE
    kernel.CloseHandle.argtypes = [W.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return 1
    try:
        # Refuse PID reuse before attaching or sending any event.
        if _creation_time(kernel, handle) != created:
            return 1
        kernel.FreeConsole()
        if not kernel.AttachConsole(pid):
            return 1
        try:
            return 0 if kernel.GenerateConsoleCtrlEvent(1, pid) else 1  # CTRL_BREAK_EVENT
        finally:
            kernel.FreeConsole()
    finally:
        kernel.CloseHandle(handle)


def request_graceful_stop(process) -> bool:
    """Signal an owned child via its private hidden console; bounded fallback if unavailable."""
    try:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        created = _creation_time(kernel, W.HANDLE(int(process._handle)))
        arguments = ['--signal-child', str(process.pid), str(created)]
        if getattr(sys, 'frozen', False):
            from outward_app.paths import bundled_dir
            helper = Path(sys.executable) if Path(sys.executable).stem == 'OutwardVPNService' else bundled_dir() / 'vpn-service' / 'OutwardVPNService.exe'
            command, cwd = [str(helper), *arguments], None
        else:
            command = [sys.executable, '-m', 'outward_app.core.windows_process', *arguments]
            cwd = str(Path(__file__).resolve().parents[2])
        result = subprocess.run(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW, timeout=4)
        return result.returncode == 0
    except (OSError, ValueError, AttributeError, subprocess.TimeoutExpired):
        return False


class ProcessJob:
    def __init__(self, process) -> None:
        self.handle = None
        if os.name != "nt":
            return
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, W.LPCWSTR]
        kernel.CreateJobObjectW.restype = W.HANDLE
        kernel.SetInformationJobObject.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [W.HANDLE, W.HANDLE]
        kernel.CloseHandle.argtypes = [W.HANDLE]
        class Basic(ctypes.Structure):
            _fields_ = [("per_process", ctypes.c_longlong), ("per_job", ctypes.c_longlong),
                        ("flags", W.DWORD), ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t),
                        ("active", W.DWORD), ("affinity", ctypes.c_size_t), ("priority", W.DWORD), ("scheduling", W.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in ("read", "write", "other", "read_bytes", "write_bytes", "other_bytes")]
        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", IO), ("process_memory", ctypes.c_size_t),
                        ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
        handle = kernel.CreateJobObjectW(None, None)
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            if handle:
                kernel.CloseHandle(handle)
            process.terminate()
            process.wait(timeout=5)
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel.AssignProcessToJobObject(handle, W.HANDLE(int(process._handle))):
            kernel.CloseHandle(handle)
            process.terminate()
            process.wait(timeout=5)
            raise ctypes.WinError(ctypes.get_last_error())
        self.handle = handle
        self.kernel = kernel

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--signal-child':
        raise SystemExit(signal_console_child(int(sys.argv[2]), int(sys.argv[3])))
    raise SystemExit(1)
