"""Owned, reversible Windows user proxy settings (WinINet, not WinHTTP).

The recovery journal is written before applying settings. A small independent
helper restores it if the GUI dies; the next launch also recovers stale journals.
All writes compare ownership so another program's changes are never undone.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes as W
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

from outward_app.core.storage import atomic_write_json
from outward_app.core.windows_process import _creation_time
from outward_app.paths import app_data_dir, source_root


@dataclass(frozen=True)
class ProxySettings:
    flags: int
    server: str = ''
    bypass: str = ''
    pac_url: str = ''

    @classmethod
    def from_dict(cls, data):
        if (not isinstance(data, dict) or type(data.get('flags')) is not int
                or not 0 <= data['flags'] <= 15
                or any(not isinstance(data.get(key), str) for key in ('server', 'bypass', 'pac_url'))):
            raise ValueError('Повреждена резервная копия системного прокси')
        return cls(**data)


class WindowsProxySettings:
    """Use PER_CONNECTION_OPTION to preserve manual, PAC and autodetect modes."""
    def __init__(self):
        if os.name != 'nt':
            raise OSError('Системный прокси поддерживается только в Windows')
        self.api = ctypes.WinDLL('wininet', use_last_error=True)
        self.kernel = _kernel()

        class Value(ctypes.Union):
            _fields_ = [('number', W.DWORD), ('string', ctypes.c_void_p), ('time', W.FILETIME)]

        class Option(ctypes.Structure):
            _fields_ = [('kind', W.DWORD), ('value', Value)]

        class Options(ctypes.Structure):
            _fields_ = [('size', W.DWORD), ('connection', W.LPWSTR), ('count', W.DWORD),
                        ('error', W.DWORD), ('options', ctypes.POINTER(Option))]

        self.Option, self.Options = Option, Options
        self.api.InternetQueryOptionW.argtypes = [W.HANDLE, W.DWORD, ctypes.c_void_p, ctypes.POINTER(W.DWORD)]
        self.api.InternetQueryOptionW.restype = W.BOOL
        self.api.InternetSetOptionW.argtypes = [W.HANDLE, W.DWORD, ctypes.c_void_p, W.DWORD]
        self.api.InternetSetOptionW.restype = W.BOOL
        self.kernel.GlobalFree.argtypes = [ctypes.c_void_p]
        self.kernel.GlobalFree.restype = ctypes.c_void_p

    def read(self):
        values = (self.Option * 4)()
        for item, kind in zip(values, (10, 2, 3, 4)):  # FLAGS_UI, SERVER, BYPASS, AUTOCONFIG_URL
            item.kind = kind
        options = self.Options(ctypes.sizeof(self.Options), None, 4, 0, values)
        size = W.DWORD(ctypes.sizeof(options))
        try:
            if not self.api.InternetQueryOptionW(None, 75, ctypes.byref(options), ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
            return ProxySettings(values[0].value.number,
                                 *[ctypes.wstring_at(v.value.string) if v.value.string else '' for v in values[1:]])
        finally:
            for item in values[1:]:
                if item.value.string:
                    self.kernel.GlobalFree(item.value.string)

    def write(self, settings):
        values = (self.Option * 4)()
        buffers = [ctypes.create_unicode_buffer(text) for text in
                   (settings.server, settings.bypass, settings.pac_url)]
        values[0].kind, values[0].value.number = 1, settings.flags  # restore with FLAGS, not FLAGS_UI
        for item, kind, buffer in zip(values[1:], (2, 3, 4), buffers):
            item.kind, item.value.string = kind, ctypes.cast(buffer, ctypes.c_void_p).value
        options = self.Options(ctypes.sizeof(self.Options), None, 4, 0, values)
        if not self.api.InternetSetOptionW(None, 75, ctypes.byref(options), ctypes.sizeof(options)):
            raise ctypes.WinError(ctypes.get_last_error())
        for flag in (39, 37):  # SETTINGS_CHANGED, REFRESH: notify existing consumers
            if not self.api.InternetSetOptionW(None, flag, None, 0):
                raise ctypes.WinError(ctypes.get_last_error())


def _kernel():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    kernel.OpenProcess.restype = W.HANDLE
    kernel.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    kernel.WaitForSingleObject.restype = W.DWORD
    kernel.WaitForMultipleObjects.argtypes = [W.DWORD, ctypes.POINTER(W.HANDLE), W.BOOL, W.DWORD]
    kernel.WaitForMultipleObjects.restype = W.DWORD
    kernel.CloseHandle.argtypes = [W.HANDLE]
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, W.BOOL, W.LPCWSTR]
    kernel.CreateMutexW.restype = W.HANDLE
    kernel.ReleaseMutex.argtypes = [W.HANDLE]
    kernel.CreateEventW.argtypes = [ctypes.c_void_p, W.BOOL, W.BOOL, W.LPCWSTR]
    kernel.CreateEventW.restype = W.HANDLE
    kernel.OpenEventW.argtypes = [W.DWORD, W.BOOL, W.LPCWSTR]
    kernel.OpenEventW.restype = W.HANDLE
    kernel.SetEvent.argtypes = [W.HANDLE]
    return kernel


def process_identity(pid):
    if os.name != 'nt':
        return 0
    kernel = _kernel()
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
    if not handle:
        # Access denied must not be mistaken for a dead owner.
        if ctypes.get_last_error() == 5:
            raise ctypes.WinError(5)
        return None
    try:
        if kernel.WaitForSingleObject(handle, 0) == 0:
            return None
        return _creation_time(kernel, handle)
    finally:
        kernel.CloseHandle(handle)


@contextmanager
def _journal_lock(path):
    if os.name != 'nt':
        yield
        return
    kernel = _kernel()
    name = hashlib.sha256(str(path.resolve()).lower().encode()).hexdigest()[:24]
    handle = kernel.CreateMutexW(None, False, 'Local\\OutwardProxy-' + name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        result = kernel.WaitForSingleObject(handle, 5000)
        if result not in (0, 0x80):  # acquired / abandoned
            raise OSError('Не удалось получить доступ к настройкам системного прокси')
        try:
            yield
        finally:
            kernel.ReleaseMutex(handle)
    finally:
        kernel.CloseHandle(handle)


def _read_journal(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    if (data.get('version') != 1 or not re.fullmatch('[a-f0-9]{32}', str(data.get('token', '')))
            or type(data.get('pid')) is not int or data['pid'] <= 0
            or type(data.get('created')) is not int):
        raise ValueError('Повреждена резервная копия системного прокси')
    ProxySettings.from_dict(data['original'])
    ProxySettings.from_dict(data['applied'])
    return data


class SystemProxyLease:
    def __init__(self, path=None, backend=None, watchdog=True, identity_reader=process_identity):
        self.path = Path(path) if path else app_data_dir() / 'system-proxy.json'
        self.backend = backend
        self.watchdog = watchdog
        self.identity_reader = identity_reader
        self.token = None
        self.helper = None

    def _backend(self):
        if self.backend is None:
            self.backend = WindowsProxySettings()
        return self.backend

    def _recover_locked(self):
        if not self.path.exists():
            return
        data = _read_journal(self.path)
        if self.identity_reader(data['pid']) == data['created']:
            raise OSError('Системный прокси уже управляется работающим сеансом Outward')
        if self._backend().read() == ProxySettings.from_dict(data['applied']):
            self._backend().write(ProxySettings.from_dict(data['original']))
        self.path.unlink(missing_ok=True)

    def recover(self):
        with _journal_lock(self.path):
            self._recover_locked()

    def acquire(self, http_port):
        if type(http_port) is not int or not 1024 <= http_port <= 65535:
            raise ValueError('Некорректный порт системного прокси')
        with _journal_lock(self.path):
            self._recover_locked()
            original = self._backend().read()
            applied = ProxySettings(3, f'http=127.0.0.1:{http_port};https=127.0.0.1:{http_port}',
                                    '<local>;localhost;127.*;[::1]', '')
            self.token = uuid4().hex
            created = self.identity_reader(os.getpid())
            if created is None:
                raise OSError('Не удалось определить владельца системного прокси')
            data = {'version': 1, 'pid': os.getpid(), 'created': created, 'token': self.token,
                    'original': asdict(original), 'applied': asdict(applied)}
            atomic_write_json(self.path, data)
            # The helper must confirm it holds the parent's process handle before
            # any OS setting changes. It is deliberately outside the core's job.
            if self.watchdog:
                self.helper = start_watchdog(self.token)
            if self._backend().read() != original:
                raise OSError('Настройки прокси Windows изменены во время подключения. Повторите подключение.')
            self._backend().write(applied)
            if self._backend().read() != applied:
                raise OSError('Windows не применила настройки системного прокси')

    def is_owned(self):
        with _journal_lock(self.path):
            if not self.token or not self.path.exists():
                return False
            data = _read_journal(self.path)
            return data['token'] == self.token and self._backend().read() == ProxySettings.from_dict(data['applied'])

    def release(self):
        token = self.token
        with _journal_lock(self.path):
            if self.token and self.path.exists():
                data = _read_journal(self.path)
                if data['token'] == self.token:
                    if self._backend().read() == ProxySettings.from_dict(data['applied']):
                        self._backend().write(ProxySettings.from_dict(data['original']))
                    self.path.unlink(missing_ok=True)
        if self.helper is not None:
            stop_watchdog(token, self.helper)
            self.helper = None
        self.token = None


def start_watchdog(token):
    kernel = _kernel()
    ready = kernel.CreateEventW(None, True, False, 'Local\\OutwardProxyReady-' + token)
    if not ready:
        raise ctypes.WinError(ctypes.get_last_error())
    stop = kernel.CreateEventW(None, True, False, 'Local\\OutwardProxyStop-' + token)
    if not stop:
        kernel.CloseHandle(ready)
        raise ctypes.WinError(ctypes.get_last_error())
    process = None
    try:
        args = ['--system-proxy-watchdog', token]
        command = ([sys.executable, *args] if getattr(sys, 'frozen', False)
                   else [sys.executable, '-m', 'outward_app', *args])
        process = subprocess.Popen(command, cwd=None if getattr(sys, 'frozen', False) else str(source_root()),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        if kernel.WaitForSingleObject(ready, 5000) != 0 or process.poll() is not None:
            raise OSError('Не удалось запустить восстановление системного прокси')
        return process
    except Exception:
        if process is not None:
            kernel.SetEvent(stop)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
        raise
    finally:
        kernel.CloseHandle(ready)
        kernel.CloseHandle(stop)


def stop_watchdog(token, process):
    if process.poll() is None:
        kernel = _kernel()
        stop = kernel.OpenEventW(2, False, 'Local\\OutwardProxyStop-' + token)
        if stop:
            try:
                kernel.SetEvent(stop)
            finally:
                kernel.CloseHandle(stop)
        # A cooperative stop also reaps the child of a frozen one-file launcher.
        process.wait(timeout=5)
    else:
        process.wait(timeout=5)


def run_watchdog(token):
    if not re.fullmatch('[a-f0-9]{32}', token):
        return 1
    lease = SystemProxyLease(watchdog=False)
    kernel = _kernel()
    parent = ready = stop = None
    try:
        data = _read_journal(lease.path)
        if data['token'] != token:
            return 1
        parent = kernel.OpenProcess(0x1000 | 0x100000, False, data['pid'])
        if not parent or _creation_time(kernel, parent) != data['created']:
            return 1
        ready = kernel.OpenEventW(2, False, 'Local\\OutwardProxyReady-' + token)
        stop = kernel.OpenEventW(0x100000, False, 'Local\\OutwardProxyStop-' + token)
        if not ready or not stop or not kernel.SetEvent(ready):
            return 1
        result = kernel.WaitForMultipleObjects(2, (W.HANDLE * 2)(parent, stop), False, 0xFFFFFFFF)
        if result == 1:
            return 0
        if result != 0:
            return 1
        # Serialize with a new GUI's recovery/start. Never consume a newer lease.
        with _journal_lock(lease.path):
            if lease.path.exists() and _read_journal(lease.path)['token'] == token:
                lease._recover_locked()
        return 0
    except (OSError, ValueError, KeyError):
        return 1  # journal remains for recovery on next launch
    finally:
        for handle in (parent, ready, stop):
            if handle:
                kernel.CloseHandle(handle)


class SystemProxyManager:
    """Keep the proxy listener alive until Windows settings have been restored."""
    def __init__(self, manager, lease):
        self.manager, self.lease = manager, lease

    def __getattr__(self, name):
        return getattr(self.manager, name)

    def activate(self, http_port):
        self.lease.acquire(http_port)

    def stop(self):
        self.lease.release()
        self.manager.stop()
