from __future__ import annotations

from dataclasses import dataclass
import json
import os
import socket
import ssl
import subprocess
import time
import threading
import ipaddress
import struct
from urllib.parse import urlsplit

from outward_app.core.singbox import hidden_startupinfo


@dataclass(frozen=True)
class NetworkInfo:
    interface: str = ""
    signature: str = ""
    local_routes: tuple[str, ...] = ()
    interface_index: int = 0


class NetworkCache:
    """Share one OS route query across all windows, including simultaneous starts."""
    def __init__(self, reader, ttl=5):
        self.reader, self.ttl = reader, ttl
        self.lock = threading.Lock()
        self.stamp, self.value, self.error = 0, None, None

    def __call__(self):
        with self.lock:
            if (self.value is None and self.error is None) or time.monotonic() - self.stamp >= self.ttl:
                try:
                    self.value, self.error = self.reader(), None
                except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                    self.error = OSError(str(exc))
                self.stamp = time.monotonic()
            if self.error:
                raise self.error
            return self.value


def read_network() -> NetworkInfo:
    if os.name != "nt":
        return NetworkInfo()
    # Only a real, connected hardware adapter can carry the control connections.
    # Own TUN default routes must never become the upstream of the proxy processes.
    script = """
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$adapters = @(Get-NetAdapter -Physical | Where-Object Status -eq 'Up')
$routes = @(Get-NetRoute | Where-Object DestinationPrefix -in @('0.0.0.0/0','::/0'))
$candidates = foreach ($a in $adapters) {
  foreach ($r in $routes | Where-Object InterfaceIndex -eq $a.ifIndex) {
    $ip = Get-NetIPInterface -InterfaceIndex $a.ifIndex -AddressFamily $r.AddressFamily
    [pscustomobject]@{Name=$a.Name; Index=$a.ifIndex; Gateway=$r.NextHop; Metric=($r.RouteMetric+$ip.InterfaceMetric)}
  }
}
$best = $candidates | Sort-Object Metric | Select-Object -First 1
if ($null -ne $best) {
  $local = @(Get-NetRoute -InterfaceIndex $best.Index | Where-Object {
    $_.NextHop -in @('0.0.0.0','::') -and $_.DestinationPrefix -notin @('0.0.0.0/0','::/0') -and
    $_.DestinationPrefix -notmatch '/(32|128)$'
  } | Select-Object -ExpandProperty DestinationPrefix)
  [pscustomobject]@{interface=$best.Name; gateway=$best.Gateway; index=$best.Index; routes=$local} | ConvertTo-Json -Compress
}
"""
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=12,
                            startupinfo=hidden_startupinfo(), creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise OSError("Не удалось прочитать маршруты Windows")
    if not result.stdout.strip():
        raise OSError("Нет доступного внешнего сетевого интерфейса")
    data = json.loads(result.stdout)
    routes = tuple(sorted(set(data.get("routes") or [])))
    signature = json.dumps([data["interface"], data["gateway"], data["index"], routes], ensure_ascii=False)
    return NetworkInfo(data["interface"], signature, routes, int(data["index"]))


class AddressCache:
    """Bounded daemon DNS lookups: a slow OS resolver cannot block ping or app shutdown."""
    def __init__(self):
        self.lock = threading.Lock()
        self.cache, self.pending = {}, {}
        self.slots = threading.BoundedSemaphore(4)

    def resolve(self, host, port, deadline, cancel):
        key = (host, port)
        with self.lock:
            cached = self.cache.get(key)
            if cached and time.monotonic() - cached[0] < 60:
                return cached[1]
            event = self.pending.get(key)
            if event is None:
                if not self.slots.acquire(blocking=False):
                    return []
                event = threading.Event()
                self.pending[key] = event
                threading.Thread(target=self._lookup, args=(key, event), daemon=True, name='outward-ping-dns').start()
        while not event.is_set():
            if cancel.is_set() or time.monotonic() >= deadline:
                return []
            event.wait(min(.05, max(0, deadline - time.monotonic())))
        with self.lock:
            return self.cache.get(key, (0, []))[1]

    def _lookup(self, key, event):
        try:
            try:
                addresses = socket.getaddrinfo(*key, type=socket.SOCK_STREAM)
            except (OSError, UnicodeError, ValueError):
                addresses = []
            with self.lock:
                if len(self.cache) >= 128:
                    self.cache.pop(next(iter(self.cache)))
                if addresses:
                    self.cache[key] = (time.monotonic(), addresses)
                else:
                    self.cache.pop(key, None)
                self.pending.pop(key, None)
        finally:
            event.set()
            self.slots.release()


_PING_ADDRESSES = AddressCache()
_ROUTE_ADDRESSES = AddressCache()


def _route_socket(host, port, deadline, cancel):
    addresses = _ROUTE_ADDRESSES.resolve(host, port, deadline, cancel or threading.Event())
    for family, kind, protocol, _name, address in sorted(addresses, key=lambda a: a[0] != socket.AF_INET):
        if (cancel and cancel.is_set()) or time.monotonic() >= deadline:
            break
        sock = socket.socket(family, kind, protocol)
        try:
            sock.settimeout(min(4, max(.001, deadline - time.monotonic())))
            sock.connect(address)
            return sock
        except OSError:
            sock.close()
    raise OSError('Не удалось соединиться с контрольным сервером')


def tcp_latency(host: str, port: int, interface_index: int = 0, cancel=None, timeout=2.0) -> int | None:
    """TCP handshake to the profile server; DNS/TLS/HTTP are not part of the measurement."""
    cancel = cancel or threading.Event()
    deadline = time.monotonic() + timeout
    try:
        ip = ipaddress.ip_address(host)
        family = socket.AF_INET if ip.version == 4 else socket.AF_INET6
        addresses = [(family, socket.SOCK_STREAM, 0, '', (host, port))]
    except ValueError:
        addresses = _PING_ADDRESSES.resolve(host, port, deadline, cancel)
    for family, kind, protocol, _name, address in sorted(addresses, key=lambda a: a[0] != socket.AF_INET):
        if cancel.is_set() or time.monotonic() >= deadline:
            return None
        try:
            with socket.socket(family, kind, protocol) as sock:
                if os.name == 'nt' and interface_index:
                    level = socket.IPPROTO_IP if family == socket.AF_INET else socket.IPPROTO_IPV6
                    # IPv4 index is network-endian; IPv6 index is host-endian (Winsock).
                    sock.setsockopt(level, 31, struct.pack('!I' if family == socket.AF_INET else '=I', interface_index))
                sock.settimeout(min(1.0, max(.001, deadline - time.monotonic())))
                started = time.perf_counter()
                sock.connect(address)
                return max(1, round((time.perf_counter() - started) * 1000))
        except OSError:
            continue
    return None


def wait_for_route(probe, port, cancel, is_running, attempts=3):
    """Allow startup routes/DNS to settle without restarting a healthy core."""
    for attempt in range(attempts):
        if cancel.is_set():
            raise InterruptedError('Подключение отменено')
        try:
            return probe(port, cancel)
        except InterruptedError:
            raise
        except OSError:
            if cancel.is_set():
                raise InterruptedError('Подключение отменено')
            if attempt == attempts - 1 or not is_running():
                raise
            if cancel.wait(.5 * (attempt + 1)):
                raise InterruptedError('Подключение отменено')


def _headers(sock: socket.socket, deadline=None) -> bytes:
    result = bytearray()
    while not result.endswith(b"\r\n\r\n"):
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Истекло время проверки маршрута')
            sock.settimeout(min(4, remaining))
        chunk = sock.recv(1)
        if not chunk:
            raise OSError("Соединение закрыто до получения ответа")
        result.extend(chunk)
        if len(result) > 16384:
            raise OSError("Слишком большой ответ проверки связи")
    return bytes(result)


PROBE_TARGETS = ("https://www.gstatic.com/generate_204", "https://cp.cloudflare.com/generate_204")


def probe_route(http_port: int | None, cancel=None) -> int:
    """TLS-verified request through THIS proxy, or the OS path without environment proxies."""
    errors = []
    deadline = time.monotonic() + 12
    for target in PROBE_TARGETS:
        if cancel and cancel.is_set():
            raise InterruptedError("Подключение отменено")
        url = urlsplit(target)
        started = time.monotonic()
        if started >= deadline:
            break
        try:
            address = ("127.0.0.1", http_port) if http_port else (url.hostname, 443)
            connection = socket.create_connection(address, timeout=min(4, deadline - started)) if http_port else _route_socket(url.hostname, 443, deadline, cancel)
            with connection as raw:
                if http_port:
                    raw.sendall(f"CONNECT {url.hostname}:443 HTTP/1.1\r\nHost: {url.hostname}:443\r\n\r\n".encode("ascii"))
                    response = _headers(raw, deadline).split(b"\r\n", 1)[0].split()
                    if len(response) < 2 or response[1] != b"200":
                        raise OSError("Прокси не установил соединение с контрольным сервером")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Истекло время проверки маршрута')
                raw.settimeout(min(4, remaining))
                with ssl.create_default_context().wrap_socket(raw, server_hostname=url.hostname) as secured:
                    secured.settimeout(min(4, max(.001, deadline - time.monotonic())))
                    secured.sendall(f"HEAD {url.path or '/'} HTTP/1.1\r\nHost: {url.hostname}\r\nConnection: close\r\n\r\n".encode("ascii"))
                    response = _headers(secured, deadline).split(b"\r\n", 1)[0].split()
                    if len(response) < 2 or not 200 <= int(response[1]) < 400:
                        raise OSError("Контрольный сервер вернул ошибку")
            return max(1, round((time.monotonic() - started) * 1000))
        except (OSError, ValueError) as exc:
            errors.append(type(exc).__name__)
    raise OSError("Нет ответа через подключение. Проверьте сервер и DNS. " + ", ".join(errors))
