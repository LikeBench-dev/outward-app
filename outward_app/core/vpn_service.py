"""Privileged VPN broker. No arbitrary configs, executable paths, plugins or shell input over IPC."""
from __future__ import annotations

import ctypes
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import re
import threading
import time

from outward_app.core.connections import parse_connection, sanitize_connection_error
from outward_app.core.network import probe_route, read_network, wait_for_route
from outward_app.core.singbox import SingBoxManager, build_session_config, hidden_startupinfo, write_config
from outward_app.core.vpn_pipe import PROTOCOL_VERSION, SERVICE_NAME, PipeServer
from outward_app.core.traffic import TrafficCounter, TrafficLedger


def service_root() -> Path:
    return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "OutwardAppVPN"


def service_data() -> Path:
    return Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "OutwardAppVPN"


def tun_is_default() -> bool:
    import subprocess
    # Prove an OS-selected route enters OUR adapter, rather than testing an auxiliary SOCKS listener.
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
        "if (@(Find-NetRoute -RemoteIPAddress '1.1.1.1' | Where-Object InterfaceAlias -eq 'OutwardVPN').Count -gt 0) { exit 0 }; exit 1"],
        capture_output=True, timeout=10, startupinfo=hidden_startupinfo(), creationflags=subprocess.CREATE_NO_WINDOW)
    return result.returncode == 0


class VpnBroker:
    def __init__(self, directory: Path, executable: Path, *, manager_factory=SingBoxManager,
                 network_reader=read_network, probe=probe_route, route_check=tun_is_default):
        self.directory, self.executable = directory, executable
        self.manager_factory, self.network_reader, self.probe, self.route_check = manager_factory, network_reader, probe, route_check
        self.lock, self.operation = threading.RLock(), threading.Lock()
        self.cancel = threading.Event()
        self.lease, self.pid = "", 0
        self.last_heartbeat = 0
        self.status, self.message = "offline", ""
        self.manager, self.worker = None, None
        self.latency = None
        self.network = ""
        self.last_probe = 0
        self.retryable = False
        self.probe_failures = 0
        self.traffic = TrafficLedger(directory / 'traffic.json')
        self.traffic_error = self.traffic.error
        self.last_traffic = 0

    def dispatch(self, payload: dict, pid: int) -> dict:
        try:
            if payload.get("version") != PROTOCOL_VERSION:
                raise ValueError("Обновите компонент VPN: несовместимая версия протокола")
            command, lease = payload.get("command"), payload.get("lease", "")
            if not isinstance(lease, str) or not re.fullmatch(r"[a-f0-9-]{36}", lease):
                raise ValueError("Некорректный владелец сессии")
            with self.lock:
                if self.lease and (self.lease != lease or self.pid != pid):
                    raise ValueError("Системный VPN уже используется другим экземпляром Outward")
                if command == "start":
                    if self.status not in {"offline", "error"}:
                        return self.snapshot()
                    if self.manager is not None:
                        raise ValueError("Сначала отключите предыдущее системное подключение")
                    link, dns = payload.get("link"), payload.get("dns", "")
                    if not isinstance(link, str) or len(link) > 24576 or not isinstance(dns, str) or len(dns) > 1024:
                        raise ValueError("Некорректные параметры профиля")
                    parsed = parse_connection(link)
                    if parsed.data.get("plugin") not in (None, "", "obfs-local", "v2ray-plugin"):
                        raise ValueError("Внешние плагины в системном VPN не разрешены")
                    self.lease, self.pid, self.last_heartbeat = lease, pid, time.monotonic()
                    self.cancel = threading.Event()
                    self.status, self.message = "connecting", "Подключаем системный VPN…"
                    self.worker = threading.Thread(target=self._start, args=(parsed, dns, self.cancel), daemon=True)
                    self.worker.start()
                elif command == "heartbeat":
                    if not self.lease:
                        raise ValueError("Системная сессия не запущена")
                    self.last_heartbeat = time.monotonic()
                elif command == "status":
                    return self.snapshot()
                elif command == "log":
                    path = self.directory / "sing-box.log"
                    if not path.exists():
                        return {"log": self.message}
                    with path.open("rb") as source:
                        source.seek(max(0, path.stat().st_size - 16000))
                        return {"log": sanitize_connection_error(source.read().decode("utf-8", errors="replace"))}
                elif command == 'traffic':
                    month, total = self.traffic.usage('system')
                    return {'traffic_month': month, 'traffic_bytes': None if self.traffic_error else total,
                            'traffic_error': self.traffic_error}
                elif command == "stop":
                    self.cancel.set()
                    self.status = "stopping"
                    threading.Thread(target=self.stop, daemon=True).start()
                else:
                    raise ValueError("Команда VPN не поддерживается")
                return self.snapshot()
        except Exception as exc:
            return {"error": sanitize_connection_error(str(exc))}

    def snapshot(self):
        return {"status": self.status, "message": self.message, "latency": self.latency, "retryable": self.retryable}

    def _start(self, parsed, dns, cancel):
        with self.operation:
            manager = None
            stage = "network"
            try:
                network = self.network_reader()
                stage = "configuration"
                config = build_session_config(parsed, custom_dns=dns, interface=network.interface,
                                              system=True, local_routes=list(network.local_routes))
                counter = TrafficCounter(config)
                self.directory.mkdir(parents=True, exist_ok=True)
                config_file = self.directory / "config.json"
                write_config(config, config_file)
                manager = self.manager_factory(config_file, self.directory / "sing-box.log")
                manager.traffic = counter
                manager.check_config(str(self.executable))
                if cancel.is_set():
                    raise InterruptedError("Подключение отменено")
                manager.start(str(self.executable))
                stage = "tun"
                deadline = time.monotonic() + 15
                while not cancel.is_set() and time.monotonic() < deadline:
                    if not manager.is_running():
                        raise OSError("Не удалось создать TUN. Проверьте журнал службы.")
                    if self.route_check():
                        break
                    cancel.wait(0.5)
                else:
                    raise OSError("Windows не направила системный трафик в адаптер OutwardVPN")
                stage = "network"
                latency = wait_for_route(self.probe, None, cancel, manager.is_running)
                with self.lock:
                    if cancel.is_set():
                        raise InterruptedError("Подключение отменено")
                    self.manager = manager
                    self.status, self.message = "connected", ""
                    self.network, self.last_probe = network.signature, time.monotonic()
                    self.latency = latency
                    self.probe_failures, self.retryable = 0, False
            except Exception as exc:
                if manager:
                    try:
                        self._sample_traffic(manager)
                        manager.stop()
                    except Exception:
                        self.manager = manager
                with self.lock:
                    self.status, self.message = "error", sanitize_connection_error(str(exc))
                    self.retryable = stage == "network" and isinstance(exc, OSError)
                self._clean_config()

    def _clean_config(self):
        # Credentials are not needed after the tunnel stops.
        (self.directory / "config.json").unlink(missing_ok=True)

    def stop(self):
        self.cancel.set()
        with self.operation:
            if self.manager:
                self._sample_traffic()
                self.manager.stop()
                self.manager = None
            self._clean_config()
            with self.lock:
                self.status, self.message, self.lease, self.pid = "offline", "", "", 0
                self.latency = None
                self.probe_failures = 0

    def _sample_traffic(self, manager=None):
        counter = getattr(manager if manager is not None else self.manager, 'traffic', None)
        if counter is not None:
            try:
                self.traffic.record('system', counter.identity, counter.read())
                self.traffic_error = ''
            except Exception:
                # Accounting failure must not disconnect the system VPN.
                self.traffic_error = 'Статистика трафика службы временно недоступна'

    def tick(self):
        if self.status == 'connected' and time.monotonic() - self.last_traffic >= 1:
            if self.operation.acquire(blocking=False):
                try:
                    self.last_traffic = time.monotonic()
                    self._sample_traffic()
                finally:
                    self.operation.release()
        with self.lock:
            expired = bool(self.lease) and time.monotonic() - self.last_heartbeat > 45
            check = self.status == "connected" and time.monotonic() - self.last_probe > 20
            if check:
                self.last_probe = time.monotonic()
        if expired:
            self.stop()
        elif check:
            if not self.operation.acquire(blocking=False):
                return
            structural = False
            try:
                with self.lock:
                    if self.status != 'connected':
                        return
                if not self.manager or not self.manager.is_running():
                    structural = True
                    raise OSError('Сетевой процесс остановлен')
                network = self.network_reader()
                if network.signature != self.network or not self.route_check():
                    structural = True
                    raise OSError("Сеть изменилась. Требуется переподключение системного VPN.")
                latency = self.probe(None, self.cancel)
                with self.lock:
                    if self.status == 'connected' and not self.cancel.is_set():
                        self.latency = latency
                        self.probe_failures, self.message = 0, ''
            except Exception as exc:
                with self.lock:
                    if self.status != 'connected' or self.cancel.is_set():
                        return
                    self.probe_failures += 1
                    self.latency = None
                    if structural or self.probe_failures >= 2:
                        self.status, self.message = "error", sanitize_connection_error(str(exc))
                        self.retryable = True
                    else:
                        self.message = 'Контрольная проверка не ответила. Повторяем проверку.'
                # Keep a live TUN on an upstream failure. No direct user-traffic fallback.
            finally:
                self.operation.release()


def run_service() -> int:
    """ServiceMain/HandlerEx implemented with Windows APIs; no pywin32 runtime required."""
    a = ctypes.WinDLL("advapi32", use_last_error=True)
    stop = threading.Event()
    class Status(ctypes.Structure):
        _fields_ = [(name, W.DWORD) for name in ("type", "state", "accepted", "exit", "specific", "checkpoint", "hint")]
    handler_type = ctypes.WINFUNCTYPE(W.DWORD, W.DWORD, W.DWORD, ctypes.c_void_p, ctypes.c_void_p)
    main_type = ctypes.WINFUNCTYPE(None, W.DWORD, ctypes.POINTER(W.LPWSTR))
    a.RegisterServiceCtrlHandlerExW.argtypes = [W.LPCWSTR, handler_type, ctypes.c_void_p]
    a.RegisterServiceCtrlHandlerExW.restype = W.HANDLE
    a.SetServiceStatus.argtypes = [W.HANDLE, ctypes.POINTER(Status)]
    handle = None
    def report(state, code=0):
        status = Status(0x10, state, 5 if state == 4 else 0, code, 0, 0, 15000 if state in (2, 3) else 0)
        a.SetServiceStatus(handle, ctypes.byref(status))
    @handler_type
    def handler(control, event_type, event_data, context):
        if control in (1, 5):
            report(3)
            stop.set()
        return 0
    @main_type
    def main(argc, argv):
        nonlocal handle
        handle = a.RegisterServiceCtrlHandlerExW(SERVICE_NAME, handler, None)
        if not handle:
            return
        report(2)
        broker = None
        pipe = None
        try:
            owner = json.loads((service_data() / "installation.json").read_text(encoding="utf-8"))["owner_sid"]
            if not re.fullmatch(r"S-1-5-\d+(?:-\d+)+", owner):
                raise ValueError("Invalid owner SID")
            broker = VpnBroker(service_data() / "runtime", service_root() / "sing-box.exe")
            pipe = PipeServer(owner)
            report(4)
            def monitor():
                while not stop.wait(1):
                    try:
                        broker.tick()
                    except Exception:
                        stop.set()
            thread = threading.Thread(target=monitor, name="vpn-watchdog", daemon=True)
            thread.start()
            while not stop.is_set():
                pipe.serve_once(broker.dispatch, stop)
                stop.wait(0.02)
            broker.stop()
            thread.join(timeout=15)
            report(1)
            return
        except Exception:
            if broker:
                broker.stop()
            report(1, 1)
        finally:
            if pipe:
                pipe.close()
    class Table(ctypes.Structure):
        _fields_ = [("name", W.LPWSTR), ("main", main_type)]
    table = (Table * 2)()
    table[0].name, table[0].main = SERVICE_NAME, main
    a.StartServiceCtrlDispatcherW.argtypes = [ctypes.POINTER(Table)]
    return 0 if a.StartServiceCtrlDispatcherW(table) else 1
