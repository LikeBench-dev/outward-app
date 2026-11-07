"""Platform-neutral connection collection and Windows process adapters. No Qt imports."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field
import threading
import time
from itertools import chain

from outward_app.core.connections import parse_connection, sanitize_connection_error
from outward_app.core.browser import browser_port_owners
from outward_app.core.models import AppSettings, ConnectionProfile, RuntimeState, SavedConnection
from outward_app.core.network import NetworkCache, probe_route, read_network, tcp_latency, wait_for_route
from outward_app.core.singbox import SingBoxManager, build_session_config, find_sing_box, is_port_open, stop_managed_sing_box_processes, write_config
from outward_app.paths import session_dir
from outward_app.core.traffic import TrafficCounter, TrafficLedger, current_month
from outward_app.core.system_proxy import SystemProxyLease, SystemProxyManager


def _uses_tun(connection):
    return connection.kind == 'system' and connection.system_mode == 'tun'


@dataclass
class SessionView:
    connection: SavedConnection
    status: str = "offline"
    message: str = ""
    runtime: RuntimeState | None = None
    generation: int = 0
    connected_at: float = 0
    latency: int | None = None
    latency_kind: str = 'tcp'
    latency_pending: bool = False
    traffic_bytes: int | None = 0
    traffic_month: str = ''
    traffic_error: str = ''


@dataclass
class _Entry:
    view: SessionView
    manager: object = None
    cancel: threading.Event = field(default_factory=threading.Event)
    operation: threading.Lock = field(default_factory=threading.Lock)
    health_pending: bool = False
    last_check: float = 0
    failures: int = 0
    retry_at: float = 0
    network: str = ""
    network_info: object = None
    ping_pending: bool = False
    last_ping: float = 0
    traffic_pending: bool = False


class PortAllocator:
    def __init__(self, occupied=is_port_open):
        self.occupied = occupied
        self.reserved: dict[str, tuple[int, int]] = {}
        self.browser_owners: dict[str, int] = {}
        self.lock = threading.Lock()

    def acquire(self, connection: SavedConnection) -> tuple[int, int]:
        with self.lock:
            used = {port for owner, pair in self.reserved.items() if owner != connection.id for port in pair}
            used.update(port for owner, port in self.browser_owners.items() if owner != connection.id)
            pair = []
            for requested in (connection.http_port, connection.socks_port):
                candidates = [requested] if connection.fixed_ports else chain(range(requested, 65536), range(1024, requested))
                port = next((p for p in candidates if p not in used and p not in pair and not self.occupied(p)), None)
                if port is None:
                    raise OSError(f"Порт {requested} занят" if connection.fixed_ports else "Нет свободных локальных портов")
                pair.append(port)
            result = (pair[0], pair[1])
            self.reserved[connection.id] = result
            return result

    def release(self, connection_id: str) -> None:
        with self.lock:
            self.reserved.pop(connection_id, None)

    def remember(self, connection_id, pair):
        with self.lock:
            self.reserved[connection_id] = pair

    def owned_ports(self, exclude=""):
        with self.lock:
            return {port for owner, pair in self.reserved.items() if owner != exclude for port in pair}

    def update_browsers(self, owners):
        with self.lock:
            self.browser_owners = owners


class SessionController:
    def __init__(self, store, settings: AppSettings, profiles: list[ConnectionProfile], on_change=None,
                 manager_factory=SingBoxManager, network_reader=read_network, probe=probe_route,
                 vpn_factory=None, browser_reader=browser_port_owners, latency_reader=tcp_latency,
                 system_proxy_factory=None):
        self.store, self.settings = store, settings
        self.profiles = {p.id: p for p in profiles}
        self.collection = store.load_connections(settings, profiles[0].id if profiles else "")
        self.on_change = on_change or (lambda view: None)
        self.manager_factory, self.network_reader, self.probe = manager_factory, NetworkCache(network_reader), probe
        self.vpn_factory = vpn_factory
        self.latency_reader = latency_reader
        self.browser_reader = NetworkCache(browser_reader, ttl=3)
        self.entries = {c.id: _Entry(SessionView(c)) for c in [self.collection.system, *self.collection.windows]}
        ledger_path = getattr(store, 'connections_file', None)
        self.traffic = TrafficLedger(ledger_path.with_name('traffic.json') if ledger_path else None)
        for entry in self.entries.values():
            entry.view.traffic_month, entry.view.traffic_bytes = self._traffic_usage(entry.view.connection)
            entry.view.traffic_error = self.traffic.error
        self.proxy_journal = ledger_path.with_name('system-proxy.json') if ledger_path else None
        self.system_proxy_factory = system_proxy_factory or (lambda: SystemProxyLease(self.proxy_journal))
        self._proxy_recovery_lock = threading.Lock()
        self._proxy_recovered = not (self.proxy_journal and self.proxy_journal.exists())
        self.ports = PortAllocator()
        self.ports.reserved.update({w.id: (w.http_port, w.socks_port) for w in self.collection.windows})
        self.lock = threading.RLock()
        self.legacy_lock = threading.Lock()
        self.legacy_cleaned = False
        self.pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="outward-session")
        self.ping_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='outward-ping')
        self.traffic_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='outward-traffic')
        self.closed = threading.Event()
        if not self._proxy_recovered:
            self.pool.submit(self._recover_proxy_on_start)
        self.monitor = threading.Thread(target=self._monitor, name="outward-network", daemon=True)
        self.monitor.start()

    def _ensure_proxy_recovered(self):
        with self._proxy_recovery_lock:
            if not self._proxy_recovered:
                self.system_proxy_factory().recover()
                self._proxy_recovered = True

    def _recover_proxy_on_start(self):
        try:
            self._ensure_proxy_recovered()
        except Exception as exc:
            with self.lock:
                entry = self.entries['system']
                if entry.view.status == 'offline':
                    entry.view.status, entry.view.message = 'error', sanitize_connection_error(str(exc))
                    self._publish(entry)

    def _traffic_usage(self, connection):
        month, total = self.traffic.usage(connection.id)
        if connection.kind == 'system':
            _, proxy_total = self.traffic.usage('system-proxy')
            total = total + proxy_total if total is not None and proxy_total is not None else None
        return month, total

    def views(self) -> list[SessionView]:
        with self.lock:
            return [deepcopy(entry.view) for entry in self.entries.values()]

    def _publish(self, entry: _Entry) -> None:
        self.on_change(deepcopy(entry.view))

    def _save(self) -> None:
        self.store.save_connections(self.collection)

    def add_window(self, profile_id: str, *, fixed_ports=False, http_port=None, socks_port=None) -> SavedConnection:
        with self.lock:
            if profile_id not in self.profiles:
                raise ValueError("Выберите профиль")
            connection = self.collection.add_window(profile_id, self.settings)
            try:
                connection.fixed_ports = fixed_ports
                if http_port is not None:
                    connection.http_port = http_port
                if socks_port is not None:
                    connection.socks_port = socks_port
                connection.__post_init__()
                used = self.ports.owned_ports()
                if not fixed_ports:
                    suggestion = self.settings.http_port + 2 * (connection.number - 1)
                    first = min(65534, suggestion)
                    port = next((p for p in chain(range(first, 65535), range(1024, first))
                                 if p not in used and p + 1 not in used), None)
                    if port is None:
                        raise ValueError("Не удалось предложить свободную пару портов")
                    connection.http_port, connection.socks_port = port, port + 1
                elif {connection.http_port, connection.socks_port} & used:
                    raise ValueError("Эти порты закреплены за другим окном")
                self._save()
            except Exception:
                self.collection.windows.remove(connection)
                raise
            entry = _Entry(SessionView(connection))
            entry.view.traffic_month, entry.view.traffic_bytes = self.traffic.usage(connection.id)
            self.entries[connection.id] = entry
            self.ports.remember(connection.id, (connection.http_port, connection.socks_port))
            self._publish(entry)
            return connection

    def configure(self, connection_id: str, **changes) -> None:
        allowed = {"profile_id", "http_port", "socks_port", "fixed_ports", "launch_url", "auto_open_browser", "auto_connect", "system_mode"}
        if not changes.keys() <= allowed:
            raise ValueError("Неизвестные параметры подключения")
        with self.lock:
            entry = self.entries[connection_id]
            if 'system_mode' in changes and entry.view.connection.kind != 'system':
                raise ValueError('Режим доступен только для системного подключения')
            needs_restart = bool(changes.keys() & {"profile_id", "http_port", "socks_port", "fixed_ports", "system_mode"})
            if needs_restart and entry.view.status in {"preparing", "connecting", "stopping"}:
                raise ValueError("Дождитесь завершения операции")
            if needs_restart and entry.view.status in {"connected", "reconnecting"}:
                raise ValueError("Сначала отключите это подключение")
            if needs_restart and entry.manager is not None:
                raise ValueError("Сначала завершите остановку этого подключения")
            original = deepcopy(entry.view.connection)
            candidate = deepcopy(original)
            for key, value in changes.items():
                setattr(candidate, key, value)
            candidate.__post_init__()
            if needs_restart and candidate.kind == "window":
                others = self.ports.owned_ports(connection_id)
                if {candidate.http_port, candidate.socks_port} & others:
                    raise ValueError("Эти порты закреплены за другим окном")
            for key, value in changes.items():
                setattr(entry.view.connection, key, value)
            try:
                self._save()
            except Exception:
                for key in changes:
                    setattr(entry.view.connection, key, getattr(original, key))
                raise
            if candidate.kind == "window" and needs_restart:
                self.ports.remember(connection_id, (candidate.http_port, candidate.socks_port))
            if 'system_mode' in changes:
                # System proxy ports are automatic and reserved only while
                # starting/running. Merely choosing the mode must not steal an
                # offline window's fixed ports, including legacy defaults.
                self.ports.release(connection_id)
                entry.view.status, entry.view.message = 'offline', ''
                entry.view.traffic_month, entry.view.traffic_bytes = self._traffic_usage(candidate)
                entry.view.traffic_error = self.traffic.error
            self._publish(entry)

    def remove(self, connection_id: str) -> None:
        with self.lock:
            entry = self.entries[connection_id]
            if entry.view.connection.kind == "system":
                raise ValueError("Системный блок нельзя удалить")
            if entry.view.status not in {"offline", "error"} or entry.manager is not None:
                raise ValueError("Сначала отключите окно")
            previous = self.collection.windows
            self.collection.windows = [w for w in previous if w.id != connection_id]
            try:
                self._save()
            except Exception:
                self.collection.windows = previous
                raise
            del self.entries[connection_id]

    def start(self, connection_id: str, *, automatic=False) -> None:
        with self.lock:
            if self.closed.is_set():
                return
            entry = self.entries[connection_id]
            if entry.view.status not in {"offline", "error", "reconnecting"}:
                return
            if not automatic:
                entry.failures = 0
            if entry.manager is not None:
                self.stop(connection_id, restart=True)
                return
            entry.view.generation += 1
            generation = entry.view.generation
            entry.cancel = threading.Event()
            entry.view.status, entry.view.message = "preparing", "Проверяем профиль и сеть…"
            entry.view.runtime = None
            entry.view.latency, entry.view.latency_pending = None, False
            entry.ping_pending = False
            self._publish(entry)
            self.pool.submit(self._connect, entry, generation, entry.cancel, automatic)

    def _current(self, entry, generation, cancel) -> bool:
        return entry.view.generation == generation and not cancel.is_set() and not self.closed.is_set()

    def _connect(self, entry: _Entry, generation: int, cancel, automatic: bool) -> None:
        with entry.operation:
            manager = None
            try:
                with self.lock:
                    if not self._current(entry, generation, cancel):
                        return
                    connection = deepcopy(entry.view.connection)
                    profile = deepcopy(self.profiles.get(connection.profile_id))
                    settings = deepcopy(self.settings)
                if profile is None:
                    raise ValueError("Выберите существующий профиль подключения")
                if settings.stop_existing_sing_box:
                    with self.legacy_lock:
                        if not self.legacy_cleaned:
                            _, errors = stop_managed_sing_box_processes()
                            if errors:
                                raise OSError("Не удалось остановить старый подтвержденный сеанс Outward")
                            self.legacy_cleaned = True
                parsed = parse_connection(profile.link)
                if parsed.data.get("plugin") not in (None, "", "obfs-local", "v2ray-plugin"):
                    raise ValueError("Неизвестный плагин Shadowsocks")
                network = self.network_reader()
                if cancel.is_set():
                    raise InterruptedError("Подключение отменено")
                if connection.kind == 'system':
                    self._ensure_proxy_recovered()
                if _uses_tun(connection):
                    if self.vpn_factory:
                        manager = self.vpn_factory()
                    else:
                        from outward_app.core.vpn_client import VpnClient
                        manager = VpnClient()
                    with self.lock:
                        if not self._current(entry, generation, cancel):
                            raise InterruptedError("Подключение отменено")
                        entry.view.status, entry.view.message = "connecting", "Запускаем системное подключение…"
                        self._publish(entry)
                    manager.connect(profile, settings.custom_dns, cancel)
                    http, socks = 0, 0
                    latency = manager.latency
                else:
                    self.ports.update_browsers(self.browser_reader())
                    http, socks = self.ports.acquire(connection)
                    directory = session_dir(connection.id)
                    config = build_session_config(parsed, http_port=http, socks_port=socks,
                                                  custom_dns=settings.custom_dns, interface=network.interface)
                    manager = self.manager_factory(directory / "config.json", directory / "sing-box.log")
                    manager.traffic = TrafficCounter(config)
                    if connection.kind == 'system':
                        manager = SystemProxyManager(manager, self.system_proxy_factory())
                    write_config(config, directory / "config.json")
                    executable = find_sing_box()
                    manager.check_config(executable)
                    with self.lock:
                        if not self._current(entry, generation, cancel):
                            raise InterruptedError("Подключение отменено")
                        entry.view.status = 'connecting'
                        entry.view.message = ('Проверяем системный прокси…' if connection.kind == 'system'
                                              else 'Проверяем подключение через порты окна…')
                        self._publish(entry)
                    if cancel.is_set():
                        raise InterruptedError("Подключение отменено")
                    manager.start(executable)
                    manager.wait_for_ports([http, socks])
                    latency = wait_for_route(self.probe, http, cancel, manager.is_running)
                    if not manager.is_running():
                        raise OSError("Процесс прокси завершился до подтверждения подключения")
                    if connection.kind == 'system':
                        if cancel.is_set():
                            raise InterruptedError('Подключение отменено')
                        manager.activate(http)
                with self.lock:
                    if not self._current(entry, generation, cancel):
                        raise InterruptedError("Подключение отменено")
                    entry.manager = manager
                    entry.network = network.signature
                    entry.network_info = network
                    entry.view.runtime = RuntimeState(profile.id, profile.name, http, socks,
                        f"http://127.0.0.1:{http}" if http else "", f"socks5://127.0.0.1:{socks}" if socks else "",
                        parsed.server, parsed.port or 0, parsed.protocol, parsed.protocol_label,
                        connection_id=connection.id, country_code=profile.country_code)
                    entry.view.status, entry.view.message = "connected", ""
                    entry.view.connected_at = time.monotonic()
                    entry.view.latency_kind = 'https' if parsed.protocol == 'wireguard' else 'tcp'
                    entry.view.latency = latency if entry.view.latency_kind == 'https' else None
                    entry.view.latency_pending = entry.view.latency_kind == 'tcp'
                    entry.last_check, entry.failures = time.monotonic(), 0
                    if not _uses_tun(connection):
                        changed = (http, socks) != (connection.http_port, connection.socks_port)
                        entry.view.connection.http_port, entry.view.connection.socks_port = http, socks
                        if changed and connection.kind == 'window':
                            entry.view.message = "Выбраны свободные порты; используйте новые адреса этого окна."
                    self._save()
                    try:
                        self.store.mark_used(profile.id)
                    except OSError:
                        entry.view.message = "Подключено. Не удалось обновить историю использования профиля."
                    self._publish(entry)
                    self._queue_ping(entry)
            except Exception as exc:
                cleanup_error = ""
                if manager:
                    try:
                        self._sample_traffic(entry, manager)
                        manager.stop()
                    except Exception as cleanup:
                        cleanup_error = sanitize_connection_error(str(cleanup))
                if not cleanup_error and entry.view.connection.kind == "window":
                    self.ports.remember(entry.view.connection.id, (entry.view.connection.http_port, entry.view.connection.socks_port))
                elif not cleanup_error and entry.view.connection.kind == 'system':
                    self.ports.release(entry.view.connection.id)
                with self.lock:
                    if cleanup_error:
                        entry.manager = manager
                    if self._current(entry, generation, cancel):
                        if not cleanup_error:
                            entry.manager = None
                        entry.view.status = "error"
                        entry.view.message = sanitize_connection_error(str(exc)) + (" Не удалось освободить ресурсы: " + cleanup_error if cleanup_error else "")
                        entry.view.runtime = None
                        # A lost network can recover; malformed profiles and denied privileges need user action.
                        if automatic and isinstance(exc, OSError) and not cleanup_error and entry.failures < 5:
                            entry.view.status = "reconnecting"
                            entry.failures += 1
                            entry.retry_at = time.monotonic() + min(60, 2 ** entry.failures)
                        self._publish(entry)

    def stop(self, connection_id: str, *, restart=False, message='') -> None:
        with self.lock:
            entry = self.entries[connection_id]
            entry.cancel.set()
            entry.view.generation += 1
            generation = entry.view.generation
            entry.view.status, entry.view.message = "stopping", "Отключаем…"
            self._publish(entry)
            self.pool.submit(self._stop, entry, generation, restart, message)

    def _stop(self, entry, generation, restart, message=''):
        with entry.operation:
            error = ""
            if entry.manager:
                try:
                    self._sample_traffic(entry)
                    entry.manager.stop()
                    if _uses_tun(entry.view.connection):
                        self._sample_traffic(entry)
                except Exception as exc:
                    error = sanitize_connection_error(str(exc))
            with self.lock:
                if entry.view.generation != generation:
                    return
                if not error:
                    entry.manager = None
                entry.view.status = "error" if error else "offline"
                entry.view.message = error or message
                if not error:
                    entry.view.runtime = None
                    if entry.view.connection.kind == 'system':
                        self.ports.release(entry.view.connection.id)
                entry.view.latency = None
                entry.view.latency_pending = False
                entry.ping_pending = False
                self._publish(entry)
        if restart and not error and not self.closed.is_set():
            self.start(entry.view.connection.id, automatic=True)

    def _monitor(self):
        while not self.closed.wait(1):
            with self.lock:
                entries = list(self.entries.values())
                for entry in entries:
                    if entry.view.traffic_month != current_month():
                        entry.view.traffic_month, entry.view.traffic_bytes = self._traffic_usage(entry.view.connection)
                        self._publish(entry)
                    if entry.view.status == "reconnecting" and entry.manager is None and time.monotonic() >= entry.retry_at:
                        self.start(entry.view.connection.id, automatic=True)
                    elif entry.view.status == "connected" and not entry.health_pending:
                        if time.monotonic() - entry.last_check >= 20:
                            entry.health_pending = True
                            self.pool.submit(self._check, entry, entry.view.generation)
                    if entry.view.status == 'connected' and time.monotonic() - entry.last_ping >= 5:
                        self._queue_ping(entry)
                    if entry.view.status == 'connected' and not entry.traffic_pending:
                        entry.traffic_pending = True
                        self.traffic_pool.submit(self._measure_traffic, entry, entry.view.generation)

    def _sample_traffic(self, entry, manager=None):
        manager = manager if manager is not None else entry.manager
        if manager is None:
            return
        try:
            if _uses_tun(entry.view.connection):
                month, total = manager.traffic_usage()
                if month != current_month():
                    raise ValueError('Период статистики службы не совпадает с текущим месяцем')
                self.traffic.set_usage(entry.view.connection.id, month, total)
            else:
                counter = getattr(manager, 'traffic', None)
                if counter is None:
                    return
                key = 'system-proxy' if entry.view.connection.kind == 'system' else entry.view.connection.id
                self.traffic.record(key, counter.identity, counter.read())
            month, total = self._traffic_usage(entry.view.connection)
            with self.lock:
                entry.view.traffic_month, entry.view.traffic_bytes = month, total
                entry.view.traffic_error = ''
        except Exception as exc:
            # Accounting is informational and must never prevent process cleanup.
            with self.lock:
                entry.view.traffic_error = (sanitize_connection_error(str(exc)) if _uses_tun(entry.view.connection)
                                            else 'Статистика временно недоступна; показан последний сохранённый объём.')
                if _uses_tun(entry.view.connection):
                    entry.view.traffic_bytes = None

    def _measure_traffic(self, entry, generation):
        try:
            with entry.operation:
                with self.lock:
                    if entry.view.generation != generation or entry.view.status != 'connected':
                        return
                self._sample_traffic(entry)
                with self.lock:
                    if entry.view.generation == generation and entry.view.status == 'connected':
                        self._publish(entry)
        finally:
            with self.lock:
                entry.traffic_pending = False

    def _queue_ping(self, entry):
        with self.lock:
            if self.closed.is_set() or entry.view.status != 'connected' or entry.ping_pending or entry.view.latency_kind != 'tcp':
                return
            entry.ping_pending = True
            entry.last_ping = time.monotonic()
            self.ping_pool.submit(self._measure_ping, entry, entry.view.generation, entry.cancel)

    def _measure_ping(self, entry, generation, cancel):
        value = None
        try:
            with self.lock:
                if not self._current(entry, generation, cancel) or not entry.view.runtime:
                    return
                runtime, network = deepcopy(entry.view.runtime), entry.network_info
            value = self.latency_reader(runtime.server, runtime.server_port,
                                        getattr(network, 'interface_index', 0), cancel)
        except (OSError, ValueError):
            pass  # Latency is informational; a failed TCP sample must never reconnect a VPN.
        finally:
            with self.lock:
                if entry.view.generation == generation:
                    entry.ping_pending = False
                    if self._current(entry, generation, cancel) and entry.view.status == 'connected':
                        entry.view.latency, entry.view.latency_pending = value, False
                        self._publish(entry)

    def _check(self, entry, generation):
        try:
            with entry.operation:
                with self.lock:
                    if entry.view.generation != generation or entry.view.status != "connected":
                        return
                    manager, runtime = entry.manager, entry.view.runtime
                if isinstance(manager, SystemProxyManager) and not manager.lease.is_owned():
                    self.stop(entry.view.connection.id,
                              message='Настройки прокси Windows изменены. Системное подключение остановлено.')
                    return
                network = self.network_reader()
                if network.signature != entry.network:
                    self.stop(entry.view.connection.id, restart=True)
                    return
                if not manager.is_running():
                    raise OSError("Сетевой процесс остановлен")
                latency = self.probe(runtime.http_port, entry.cancel) if runtime.http_port else manager.heartbeat()
                with self.lock:
                    if entry.view.generation == generation:
                        if entry.failures:
                            entry.view.message = ''
                        entry.last_check, entry.failures = time.monotonic(), 0
                        if entry.view.latency_kind == 'https':
                            entry.view.latency = latency
                        self._publish(entry)
        except Exception as exc:
            with self.lock:
                if entry.view.generation != generation:
                    return
                entry.failures += 1
                entry.view.message = sanitize_connection_error(str(exc))
                entry.last_check = time.monotonic()
                if entry.failures >= 2 or (entry.manager and not entry.manager.is_running()):
                    self.stop(entry.view.connection.id, restart=True)
                else:
                    self._publish(entry)
        finally:
            with self.lock:
                entry.health_pending = False

    def close(self) -> None:
        with self.lock:
            self.closed.set()
            for entry in list(self.entries.values()):
                entry.cancel.set()
        # Wait for start/cancel cleanup before final owned-process shutdown.
        self.pool.shutdown(wait=True, cancel_futures=False)
        self.ping_pool.shutdown(wait=True, cancel_futures=True)
        self.traffic_pool.shutdown(wait=True, cancel_futures=True)
        errors = []
        for entry in list(self.entries.values()):
            if entry.manager:
                try:
                    self._sample_traffic(entry)
                    entry.manager.stop()
                    if _uses_tun(entry.view.connection):
                        self._sample_traffic(entry)
                    entry.manager = None
                except Exception as exc:
                    errors.append(sanitize_connection_error(str(exc)))
        if errors:
            raise OSError("; ".join(errors))

    def log_text(self, connection_id: str) -> str:
        entry = self.entries.get(connection_id)
        if not entry:
            return ""
        if _uses_tun(entry.view.connection):
            from outward_app.core.vpn_client import VpnClient
            try:
                return (entry.manager or VpnClient()).log_text()
            except OSError as exc:
                return entry.view.message or sanitize_connection_error(str(exc))
        path = session_dir(connection_id) / "sing-box.log"
        if not path.exists():
            return entry.view.message
        with path.open("rb") as source:
            source.seek(max(0, path.stat().st_size - 16000))
            return sanitize_connection_error(source.read().decode("utf-8", errors="replace"))
