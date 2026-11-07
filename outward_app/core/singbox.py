from __future__ import annotations

import filecmp
import json
import os
import shutil
import socket
import subprocess
import time
import threading
from pathlib import Path
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from outward_app.core.connections import ParsedConnection
from outward_app.paths import app_data_dir, app_dir, bundled_dir, config_path, log_path, previous_log_path, sing_box_sessions_path


def hidden_startupinfo() -> subprocess.STARTUPINFO:
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return startupinfo


def decode_process_output(data: bytes) -> str:
    for encoding in ("cp866", "cp1251", "utf-8"):
        try:
            return data.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return data.decode(errors="replace").strip()


def dns_servers_from_text(custom_dns: str) -> list[str]:
    servers = []
    for item in custom_dns.replace(";", ",").replace("\n", ",").split(","):
        value = item.strip()
        if value:
            servers.append(value)
    return servers


def _dns_server_config(server: str, tag: str) -> dict:
    value = server.strip()
    lower = value.lower()
    if lower == "local":
        return {"type": "local", "tag": tag}

    parsed = urlparse(value)
    if parsed.scheme:
        dns_type = "h3" if parsed.scheme == "h3" else parsed.scheme
        host = parsed.hostname or parsed.netloc or parsed.path
        config = {"type": dns_type, "tag": tag, "server": host}
        if parsed.port:
            config["server_port"] = parsed.port
        if dns_type in {"https", "h3"} and parsed.path and parsed.path != "/dns-query":
            config["path"] = parsed.path
        return config

    return {"type": "udp", "tag": tag, "server": value}


def build_dns_config(custom_dns: str = "", profile_dns: list[str] | None = None) -> dict | None:
    servers = dns_servers_from_text(custom_dns)
    if not servers and profile_dns:
        servers = profile_dns
    if not servers:
        return None

    return {
        "servers": [
            _dns_server_config(server, f"custom-dns-{index}")
            for index, server in enumerate(servers)
        ],
        "final": "custom-dns-0",
    }


def build_inbounds(http_port: int, socks_port: int | None = None) -> list[dict]:
    if socks_port is None:
        return [
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": "127.0.0.1",
                "listen_port": http_port,
            }
        ]

    return [
        {
            "type": "http",
            "tag": "http-in",
            "listen": "127.0.0.1",
            "listen_port": http_port,
        },
        {
            "type": "socks",
            "tag": "socks-in",
            "listen": "127.0.0.1",
            "listen_port": socks_port,
        },
    ]


def _as_connection(connection: ParsedConnection | dict) -> ParsedConnection:
    if isinstance(connection, ParsedConnection):
        return connection
    return ParsedConnection(
        protocol="vless",
        server=connection["server"],
        port=connection["port"],
        remark=connection.get("remark") or "",
        data=connection,
    )


def build_vless_outbound(vless: dict) -> dict:
    outbound = {
        "type": "vless",
        "tag": "proxy",
        "server": vless["server"],
        "server_port": vless["port"],
        "uuid": vless["uuid"],
        "tls": {
            "enabled": True,
            "server_name": vless["server_name"],
            "utls": {
                "enabled": True,
                "fingerprint": vless.get("fingerprint") or "chrome",
            },
            "reality": {
                "enabled": True,
                "public_key": vless["public_key"],
                "short_id": vless["short_id"],
            },
        },
    }
    if vless["flow"]:
        outbound["flow"] = vless["flow"]
    return outbound


def build_shadowsocks_outbound(shadowsocks: dict) -> dict:
    outbound = {
        "type": "shadowsocks",
        "tag": "proxy",
        "server": shadowsocks["server"],
        "server_port": shadowsocks["port"],
        "method": shadowsocks["method"],
        "password": shadowsocks["password"],
    }
    for key in ("plugin", "plugin_opts", "network"):
        value = shadowsocks.get(key)
        if value:
            outbound[key] = value
    return outbound


def build_wireguard_endpoint(wireguard: dict) -> dict:
    endpoint = {
        "type": "wireguard",
        "tag": "proxy",
        "system": False,
        "address": wireguard["address"],
        "private_key": wireguard["private_key"],
        "peers": wireguard["peers"],
    }
    if wireguard.get("mtu"):
        endpoint["mtu"] = wireguard["mtu"]
    return endpoint


def build_sing_box_config(
    connection: ParsedConnection | dict,
    http_port: int,
    socks_port: int | None = None,
    custom_dns: str = "",
) -> dict:
    parsed = _as_connection(connection)
    config = {
        "log": {"level": "info", "timestamp": True},
        "inbounds": build_inbounds(http_port, socks_port),
        "outbounds": [{"type": "direct", "tag": "direct"}],
        "route": {"final": "proxy"},
    }

    if parsed.protocol == "vless":
        config["outbounds"].insert(0, build_vless_outbound(parsed.data))
    elif parsed.protocol == "shadowsocks":
        config["outbounds"].insert(0, build_shadowsocks_outbound(parsed.data))
    elif parsed.protocol == "wireguard":
        config["endpoints"] = [build_wireguard_endpoint(parsed.data)]
    else:
        raise ValueError(f"Unsupported protocol: {parsed.protocol}")

    dns_config = build_dns_config(custom_dns, parsed.data.get("dns") if isinstance(parsed.data.get("dns"), list) else None)
    if dns_config:
        config["dns"] = dns_config
        config["route"]["default_domain_resolver"] = "custom-dns-0"

    return config


def write_config(config: dict, path: Path | None = None) -> None:
    from outward_app.core.storage import atomic_write_json
    atomic_write_json(path or config_path(), config)


def build_session_config(connection: ParsedConnection, *, http_port: int = 0, socks_port: int = 0,
                         custom_dns: str = "", interface: str = "", system: bool = False,
                         local_routes: list[str] | None = None) -> dict:
    """Generate both modes from one protocol implementation, using sing-box 1.13 fields."""
    config = build_sing_box_config(connection, http_port or 1080, socks_port or 1081,
                                   custom_dns or ("1.1.1.1" if system else ""))
    config["route"]["auto_detect_interface"] = not bool(interface)
    if interface:
        config["route"]["default_interface"] = interface
    # Resolve server names independently of the user traffic resolver / not-yet-running tunnel.
    dns = config.setdefault("dns", {"servers": [], "final": "bootstrap-dns"})
    # Typed DNS servers already use a direct dialer. Detouring to an empty direct outbound
    # passes `check` but fails during module startup in sing-box 1.13.
    bootstrap = {"type": "https", "tag": "bootstrap-dns", "server": "1.1.1.1"}
    if interface:
        bootstrap["bind_interface"] = interface
    dns["servers"].append(bootstrap)
    config["route"]["default_domain_resolver"] = "bootstrap-dns"
    for server in dns["servers"]:
        if server["tag"] != "bootstrap-dns" and server["type"] != "local":
            server["detour"] = "proxy"
    if system:
        if not interface:
            raise ValueError("Не удалось определить внешний сетевой интерфейс")
        for server in dns["servers"]:
            if server["tag"] != "bootstrap-dns":
                if server["type"] == "local":
                    raise ValueError("Для системного VPN укажите DNS-сервер вместо local")
                server["detour"] = "proxy"
        config["inbounds"] = [{
            "type": "tun", "tag": "system-tun", "interface_name": "OutwardVPN",
            "address": ["172.29.255.1/30", "fdfe:dcba:9876::1/126"],
            "mtu": 1500, "auto_route": True, "strict_route": True, "stack": "mixed",
            "route_exclude_address": local_routes or [],
        }]
        config["route"]["rules"] = [{"action": "sniff"}, {"protocol": "dns", "action": "hijack-dns"}]
    return config


def append_log_entry(message: str, level: str = "ERROR") -> None:
    log_file = log_path()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%H:%M:%S")
    safe_level = level.strip().upper() or "INFO"
    log_file.open("a", encoding="utf-8").write(f"\n{timestamp} {safe_level} {message.strip()}\n")

def rotate_logs_on_app_start() -> None:
    log_file = log_path()
    previous_log_file = previous_log_path()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        if previous_log_file.exists():
            previous_log_file.unlink()
        if log_file.exists():
            log_file.replace(previous_log_file)
        log_file.write_text(f"=== Outward App session started {timestamp} ===\n", encoding="utf-8")
    except OSError as exc:
        try:
            with log_file.open("a", encoding="utf-8") as log:
                log.write(f"\n=== Outward App session started {timestamp} ===\n")
                log.write(f"{datetime.now().strftime('%H:%M:%S')} WARNING Could not rotate log: {exc}\n")
        except OSError:
            pass


def managed_sing_box_path() -> Path:
    return app_data_dir() / "bin" / "sing-box.exe"


_MANAGED_BINARY_LOCK = threading.Lock()


def _install_managed_sing_box(source: Path) -> Path:
    # Simultaneous window starts share one runtime executable and one staging path.
    with _MANAGED_BINARY_LOCK:
        return _copy_managed_sing_box(source)


def _copy_managed_sing_box(source: Path) -> Path:
    target = managed_sing_box_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() and filecmp.cmp(source, target, shallow=False):
        return target

    temp_target = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    try:
        shutil.copy2(source, temp_target)
        os.replace(temp_target, target)
    except OSError as exc:
        try:
            if temp_target.exists():
                temp_target.unlink()
        except OSError:
            pass
        if target.exists():
            append_log_entry(f"Could not update managed sing-box.exe: {exc}", "WARNING")
            return target
        raise RuntimeError(f"Could not install sing-box.exe to {target}: {exc}") from exc

    return target


def find_sing_box() -> str:
    bundled_candidates = [
        bundled_dir() / "sing-box.exe",
        bundled_dir() / "bin" / "sing-box.exe",
    ]
    for candidate in bundled_candidates:
        if candidate.exists():
            return str(_install_managed_sing_box(candidate))

    managed = managed_sing_box_path()
    if managed.exists():
        return str(managed)

    candidates = [
        app_dir() / "sing-box.exe",
        app_dir() / "bin" / "sing-box.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    from_path = shutil.which("sing-box.exe") or shutil.which("sing-box")
    if from_path:
        return from_path

    raise FileNotFoundError("sing-box.exe was not found. Put it in the app folder or add sing-box to PATH.")

def _normalize_process_text(value: object) -> str:
    return str(value or "").replace("/", "\\").lower()


def _read_sing_box_sessions() -> list[dict[str, Any]]:
    path = sing_box_sessions_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    sessions = data.get("sessions") if isinstance(data, dict) else None
    if not isinstance(sessions, list):
        return []
    return [session for session in sessions if isinstance(session, dict)]


def _write_sing_box_sessions(sessions: list[dict[str, Any]]) -> None:
    from outward_app.core.storage import atomic_write_json
    path = sing_box_sessions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, {"sessions": sessions})


def running_sing_box_processes() -> list[dict[str, str]]:
    script = (
        "$items = Get-CimInstance Win32_Process -Filter \"Name = 'sing-box.exe'\" | "
        "Select-Object ProcessId,ExecutablePath,CommandLine,"
        "@{Name='CreationDate';Expression={$_.CreationDate.ToString('o')}}; "
        "$items | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            cwd=str(app_data_dir()),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            startupinfo=hidden_startupinfo(),
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
    except OSError:
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    rows = data if isinstance(data, list) else [data]
    processes = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pid = row.get("ProcessId")
        if pid is None:
            continue
        processes.append(
            {
                "pid": str(pid),
                "creation_date": str(row.get("CreationDate") or ""),
                "executable_path": str(row.get("ExecutablePath") or ""),
                "command_line": str(row.get("CommandLine") or ""),
            }
        )
    return processes


def _find_sing_box_process(pid: int | str, timeout: float = 1.0) -> dict[str, str] | None:
    expected_pid = str(pid)
    deadline = time.time() + timeout
    while True:
        for process in running_sing_box_processes():
            if process.get("pid") == expected_pid:
                return process
        if time.time() >= deadline:
            return None
        time.sleep(0.1)


def sing_box_session_matches_process(session: dict[str, Any], process: dict[str, Any]) -> bool:
    if str(session.get("pid") or "") != str(process.get("pid") or ""):
        return False

    expected_creation_date = str(session.get("creation_date") or "")
    actual_creation_date = str(process.get("creation_date") or "")
    if not expected_creation_date or expected_creation_date != actual_creation_date:
        return False

    expected_config = _normalize_process_text(session.get("config_path"))
    command_line = _normalize_process_text(process.get("command_line"))
    if not expected_config or expected_config not in command_line:
        return False

    expected_exe = _normalize_process_text(session.get("sing_box") or session.get("executable_path"))
    actual_exe = _normalize_process_text(process.get("executable_path"))
    if expected_exe and actual_exe and expected_exe != actual_exe:
        return False

    return True


def sing_box_process_uses_outward_config(process: dict[str, Any]) -> bool:
    expected_config = _normalize_process_text(config_path())
    command_line = _normalize_process_text(process.get('command_line'))
    return bool(expected_config and expected_config in command_line)


def register_managed_sing_box_process(process: subprocess.Popen, sing_box: str) -> None:
    try:
        process_info = _find_sing_box_process(process.pid)
        if not process_info or not process_info.get("creation_date"):
            return
        sessions = [session for session in _read_sing_box_sessions() if str(session.get("pid") or "") != str(process.pid)]
        sessions.append(
            {
                "pid": str(process.pid),
                "creation_date": process_info["creation_date"],
                "executable_path": process_info.get("executable_path") or str(sing_box),
                "command_line": process_info.get("command_line") or "",
                "config_path": str(config_path()),
                "sing_box": str(sing_box),
            }
        )
        _write_sing_box_sessions(sessions)
    except Exception as exc:
        append_log_entry(f"Could not record sing-box session: {exc}")


def unregister_managed_sing_box_process(pid: int | str) -> None:
    try:
        sessions = [session for session in _read_sing_box_sessions() if str(session.get("pid") or "") != str(pid)]
        _write_sing_box_sessions(sessions)
    except Exception as exc:
        append_log_entry(f"Could not update sing-box session manifest: {exc}")


def wait_for_pids_to_exit(pids: list[str], timeout: float = 5.0) -> list[str]:
    if not pids:
        return []

    pending = {str(pid) for pid in pids}
    deadline = time.time() + timeout
    while pending and time.time() < deadline:
        running_pids = {process.get('pid') for process in running_sing_box_processes()}
        pending = {pid for pid in pending if pid in running_pids}
        if pending:
            time.sleep(0.2)
    return sorted(pending)


def wait_for_ports_to_close(ports: list[int], timeout: float = 5.0) -> list[int]:
    pending = {int(port) for port in ports}
    deadline = time.time() + timeout
    while pending and time.time() < deadline:
        pending = {port for port in pending if tcp_port_has_listener(port)}
        if pending:
            time.sleep(0.2)
    return sorted(pending)


def stop_managed_sing_box_processes() -> tuple[list[str], list[str]]:
    sessions = _read_sing_box_sessions()
    processes = running_sing_box_processes()
    pids = set()
    for session in sessions:
        if any(sing_box_session_matches_process(session, process) for process in processes):
            pids.add(str(session.get('pid')))
    ordered_pids = sorted(pids)
    errors = stop_pids(ordered_pids) if ordered_pids else []
    remaining_pids = wait_for_pids_to_exit(ordered_pids) if ordered_pids else []
    errors.extend(f'PID {pid}: process did not exit after stop request' for pid in remaining_pids)
    remaining_processes = running_sing_box_processes() if pids else processes
    remaining_sessions = [
        session
        for session in sessions
        if any(sing_box_session_matches_process(session, process) for process in remaining_processes)
    ]
    _write_sing_box_sessions(remaining_sessions)
    return ordered_pids, errors


def stop_pids(pids: list[str]) -> list[str]:
    errors = []
    for pid in pids:
        result = subprocess.run(
            ["taskkill", "/PID", pid, "/F", "/T"],
            cwd=str(app_data_dir()),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=hidden_startupinfo(),
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
        if result.returncode != 0:
            errors.append(f"PID {pid}: {decode_process_output(result.stdout + result.stderr)}")
    return errors


def is_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def tcp_port_has_listener(port: int) -> bool:
    # Reading the native table avoids a PowerShell/WMI process for every listener poll.
    import ctypes
    import struct
    from ctypes import wintypes as W
    api = ctypes.WinDLL('iphlpapi', use_last_error=True).GetExtendedTcpTable
    api.argtypes = [ctypes.c_void_p, ctypes.POINTER(W.DWORD), W.BOOL, W.ULONG, ctypes.c_int, W.ULONG]
    api.restype = W.DWORD
    size = W.DWORD()
    result = api(None, ctypes.byref(size), False, 2, 5, 0)
    if result not in (0, 122):
        raise OSError(f'Не удалось прочитать TCP listeners Windows: {result}')
    for _ in range(3):
        buffer = ctypes.create_string_buffer(size.value)
        result = api(buffer, ctypes.byref(size), False, 2, 5, 0)
        if result == 122:
            continue
        if result:
            raise OSError(f'Не удалось прочитать TCP listeners Windows: {result}')
        count = struct.unpack_from('<I', buffer)[0]
        for index in range(count):
            state, local, local_port, remote, remote_port, pid = struct.unpack_from('<6I', buffer, 4 + index * 24)
            if state == 2 and socket.ntohs(local_port & 0xffff) == port:
                return True
        return False
    return False


def choose_socks_port(default_port: int) -> int:
    if not is_port_open(default_port):
        return default_port

    for port in range(default_port + 1, default_port + 30):
        if not is_port_open(port):
            return port

    raise RuntimeError(f"No free proxy port was found near {default_port}.")


def choose_proxy_ports(default_http_port: int, default_socks_port: int) -> tuple[int, int]:
    http_port = choose_socks_port(default_http_port)
    if default_socks_port != http_port and not is_port_open(default_socks_port):
        return http_port, default_socks_port

    socks_start = max(default_socks_port, http_port + 1)
    for port in range(socks_start, socks_start + 30):
        if port != http_port and not is_port_open(port):
            return http_port, port

    raise RuntimeError(f"No free SOCKS5 proxy port was found near {default_socks_port}.")


class SingBoxManager:
    def __init__(self, config_file: Path | None = None, log_file: Path | None = None) -> None:
        self.process: subprocess.Popen | None = None
        self.ports: list[int] = []
        self.config_file = config_file
        self.log_file = log_file
        self._job = None
        self._log_thread = None

    @property
    def config(self) -> Path:
        return self.config_file or config_path()

    @property
    def log(self) -> Path:
        return self.log_file or log_path()

    def check_config(self, sing_box: str) -> None:
        result = subprocess.run(
            [sing_box, "check", "-c", str(self.config)],
            cwd=str(self.config.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            startupinfo=hidden_startupinfo(),
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
            timeout=20,
            encoding="utf-8", errors="replace",
        )

        if result.returncode != 0:
            details = (result.stdout + "\n" + result.stderr).strip()
            raise RuntimeError(f"sing-box rejected config.json:\n{details}")

    def start(self, sing_box: str) -> subprocess.Popen:
        log_file = self.log
        log_file.parent.mkdir(parents=True, exist_ok=True)
        if log_file.exists() and log_file.stat().st_size > 4 * 1024 * 1024:
            log_file.replace(log_file.with_suffix(".log.1"))
        # A private hidden console permits a targeted CTRL_BREAK for graceful TUN cleanup.
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NEW_CONSOLE
        self.process = subprocess.Popen(
            [sing_box, "run", "-c", str(self.config)],
            cwd=str(self.config.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            startupinfo=hidden_startupinfo(),
            creationflags=creationflags,
            close_fds=True,
        )
        self._log_thread = threading.Thread(target=self._collect_log, args=(self.process.stdout, log_file), daemon=True)
        self._log_thread.start()
        if self.config_file is None:
            register_managed_sing_box_process(self.process, sing_box)
        else:
            # A private process handle and a kill-on-close job provide ownership without a global kill sweep.
            from outward_app.core.windows_process import ProcessJob
            self._job = ProcessJob(self.process)
        return self.process

    @staticmethod
    def _collect_log(source, path: Path):
        from outward_app.core.connections import sanitize_connection_error
        try:
            for raw in iter(lambda: source.readline(65536), b""):
                text = sanitize_connection_error(raw.decode("utf-8", errors="replace"))
                try:
                    if path.exists() and path.stat().st_size > 4 * 1024 * 1024:
                        path.replace(path.with_suffix(".log.1"))
                    with path.open("a", encoding="utf-8") as destination:
                        destination.write(text)
                except OSError:
                    # Always drain the pipe, even if a log is temporarily locked or the disk is full.
                    continue
        finally:
            source.close()

    def wait_for_port(self, socks_port: int, timeout: float = 8.0) -> None:
        if not self.process:
            raise RuntimeError("sing-box process has not been started.")

        deadline = time.time() + timeout
        last_error: OSError | None = None
        while time.time() < deadline:
            code = self.process.poll()
            if code is not None:
                raise RuntimeError(self._startup_error(code))
            if tcp_port_has_listener(socks_port):
                return
            last_error = OSError("port is not listening yet")
            time.sleep(0.3)

        raise RuntimeError(f"Порт {socks_port} не открылся. Подробности — в журнале подключения.")

    def _startup_error(self, code: int) -> str:
        from outward_app.core.connections import sanitize_connection_error
        import re
        if self._log_thread:
            self._log_thread.join(timeout=0.3)
        reason = ""
        try:
            with self.log.open('rb') as stream:
                stream.seek(max(0, self.log.stat().st_size - 8192))
                lines = stream.read().decode('utf-8', errors='replace').splitlines()
            for line in reversed(lines):
                line = re.sub(r'\x1b\[[0-9;]*m', '', line)
                match = re.search(r'(?:FATAL|ERROR)(?:\[[^]]*\])?\s*(.*)', line)
                if match:
                    reason = sanitize_connection_error(match.group(1)).strip()[:280]
                    break
        except OSError:
            pass
        return f"Не удалось запустить подключение (код {code}). " + (reason or "Подробности — в журнале подключения.")

    def wait_for_ports(self, ports: list[int], timeout: float = 8.0) -> None:
        self.ports = list(ports)
        for port in ports:
            self.wait_for_port(port, timeout)

    def stop(self, ports: list[int] | None = None) -> None:
        process = self.process
        if not process:
            return
        if process.poll() is None:
            from outward_app.core.windows_process import request_graceful_stop
            if not self._job or not request_graceful_stop(process):
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if self._job:
                    self._job.close()
                    self._job = None
                else:
                    process.kill()
                process.wait(timeout=5)
        if self._job:
            self._job.close()
            self._job = None
        if self._log_thread:
            self._log_thread.join(timeout=2)
            self._log_thread = None
        if self.config_file is None:
            unregister_managed_sing_box_process(process.pid)
        ports_to_close = list(ports or self.ports)
        if ports_to_close:
            wait_for_ports_to_close(ports_to_close)
        self.process = None
        self.ports = []

    def is_running(self) -> bool:
        return bool(self.process and self.process.poll() is None)


def tail_log(max_chars: int = 12000) -> str:
    path = log_path()
    if not path.exists():
        return ""
    data = path.read_bytes()
    return data[-max_chars:].decode("utf-8", errors="replace")

