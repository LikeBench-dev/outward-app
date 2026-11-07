from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
import shutil
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from outward_app.core.browser import open_url_with_proxy
from outward_app.core.connections import parse_connection
from outward_app.core.models import AppSettings, ConnectionCollection, ConnectionProfile, SavedConnection
from outward_app.core.network import NetworkInfo
from outward_app.core.sessions import PortAllocator, SessionController
from outward_app.core.singbox import SingBoxManager, _install_managed_sing_box, build_session_config
from outward_app.core.storage import JsonStore
from outward_app.core.vpn_service import VpnBroker

LINK = 'ss://YWVzLTI1Ni1nY206c2VjcmV0@example.net:8388#Test'


class FakeManager:
    def __init__(self, config=None, log=None):
        self.config, self.log = config, log
        self.running = False
        self.stops = 0
        self.starts = 0

    def check_config(self, executable):
        pass

    def start(self, executable):
        self.starts += 1
        self.running = True

    def wait_for_ports(self, ports):
        self.ports = ports

    def is_running(self):
        return self.running

    def stop(self):
        self.stops += 1
        self.running = False


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('Timed out waiting for session transition')


class SessionTests(unittest.TestCase):
    def test_startup_failure_reports_safe_reason_without_an_unusable_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            log = path / 'core.log'
            log.write_text('FATAL[0000] start service: bad credentials {"password":"private-value"}\n', encoding='utf-8')
            manager = SingBoxManager(path / 'config.json', log)
            manager.process = Mock()
            manager.process.poll.return_value = 1
            with self.assertRaises(RuntimeError) as caught:
                manager.wait_for_port(18080)
            message = str(caught.exception)
            self.assertIn('bad credentials', message)
            self.assertNotIn('private-value', message)
            self.assertNotIn(directory, message)

    def test_simultaneous_windows_install_one_complete_runtime_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'bundled.exe'
            content = b'test-kernel' * 65536
            source.write_bytes(content)
            target = root / 'runtime' / 'sing-box.exe'
            with patch('outward_app.core.singbox.managed_sing_box_path', return_value=target), \
                    patch('outward_app.core.singbox.shutil.copy2', wraps=shutil.copy2) as copy:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    paths = list(pool.map(_install_managed_sing_box, [source] * 8))
            self.assertEqual(paths, [target] * 8)
            self.assertEqual(target.read_bytes(), content)
            self.assertEqual(copy.call_count, 1)

    def store(self, directory):
        return JsonStore(directory / 'profiles.json', directory / 'settings.json', directory / 'connections.json')

    def test_migration_is_idempotent_keeps_old_files_and_does_not_enable_system_vpn(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(Path(directory))
            settings = AppSettings(http_port=19200, socks_port=19201, auto_connect_on_startup=True,
                                   launch_url='example.net', auto_open_browser=True)
            profile = ConnectionProfile.create('Server', LINK)
            store.save_profiles([profile])
            store.save_settings(settings)
            old_profiles = store.profiles_file.read_bytes()
            migrated = store.load_connections(settings, profile.id)
            self.assertFalse(migrated.system.auto_connect)
            self.assertTrue(migrated.windows[0].auto_connect)
            self.assertTrue(migrated.windows[0].auto_open_browser)
            self.assertEqual(migrated.windows[0].legacy_browser_dir, 'chrome_proxy_profile_19201')
            self.assertEqual(store.load_connections(AppSettings(), '').to_dict(), migrated.to_dict())
            self.assertEqual(store.profiles_file.read_bytes(), old_profiles)
            self.assertEqual(store.profiles_file.with_name('profiles.json.pre-connections.bak').read_bytes(), old_profiles)

    def test_unknown_or_corrupt_schema_is_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(Path(directory))
            raw = '{"schema_version": 99}'
            store.connections_file.write_text(raw)
            with self.assertRaises(ValueError):
                store.load_connections(AppSettings(), '')
            self.assertEqual(store.connections_file.read_text(), raw)

    def test_collection_numbers_survive_delete_and_reloading(self):
        collection = ConnectionCollection()
        first = collection.add_window('p', AppSettings())
        second = collection.add_window('p', AppSettings())
        collection.windows.remove(first)
        loaded = ConnectionCollection.from_dict(collection.to_dict())
        third = loaded.add_window('p', AppSettings())
        self.assertEqual((second.number, third.number), (2, 3))

    def test_port_reservations_are_atomic_and_fixed_ports_never_move(self):
        allocator = PortAllocator(occupied=lambda port: False)
        windows = [SavedConnection(id=f'window-{n}', number=n+1) for n in range(12)]
        with ThreadPoolExecutor(max_workers=12) as pool:
            pairs = list(pool.map(allocator.acquire, windows))
        ports = [port for pair in pairs for port in pair]
        self.assertEqual(len(ports), len(set(ports)))
        fixed = SavedConnection(id='fixed', number=20, fixed_ports=True)
        with self.assertRaisesRegex(OSError, '27182'):
            allocator.acquire(fixed)
        allocator.release(windows[0].id)
        self.assertEqual(allocator.acquire(fixed), (27182, 27183))

    def test_live_browser_binding_cannot_be_reused_by_another_window(self):
        allocator = PortAllocator(occupied=lambda port: False)
        allocator.update_browsers({'deleted-window': 27183})
        pair = allocator.acquire(SavedConnection(id='new-window', number=1))
        self.assertNotIn(27183, pair)

    def test_auto_ports_can_wrap_after_the_top_port(self):
        allocator = PortAllocator(occupied=lambda port: port == 65535)
        pair = allocator.acquire(SavedConnection(id='window', number=1, http_port=65534, socks_port=65535))
        self.assertEqual(pair, (65534, 1024))

    def controller(self, directory, probe=lambda port, cancel: 17):
        store = self.store(directory)
        profile = ConnectionProfile.create('Server', LINK)
        store.save_profiles([profile])
        controller = SessionController(store, AppSettings(stop_existing_sing_box=False), [profile], manager_factory=FakeManager,
                                       network_reader=lambda: NetworkInfo('Ethernet', 'network-1'), probe=probe, browser_reader=lambda: {},
                                       latency_reader=lambda *args: 17)
        controller.ports = PortAllocator(occupied=lambda port: False)
        self.addCleanup(controller.close)
        return controller, profile

    def test_independent_processes_ports_configs_and_stop(self):
        with tempfile.TemporaryDirectory() as directory, patch('outward_app.core.sessions.find_sing_box', return_value='test.exe'), \
                patch('outward_app.core.sessions.session_dir', side_effect=lambda cid: Path(directory) / cid):
            controller, profile = self.controller(Path(directory))
            ids = [controller.collection.windows[0].id, controller.add_window(profile.id).id]
            for cid in ids:
                controller.start(cid)
            wait_for(lambda: all(controller.entries[cid].view.status == 'connected' for cid in ids))
            first, second = [controller.entries[cid] for cid in ids]
            self.assertIsNot(first.manager, second.manager)
            self.assertNotEqual(first.view.runtime.http_port, second.view.runtime.http_port)
            self.assertNotEqual(first.manager.config, second.manager.config)
            second_manager = second.manager
            controller.stop(ids[0])
            wait_for(lambda: first.view.status == 'offline')
            self.assertTrue(second_manager.running)
            self.assertEqual(second_manager.stops, 0)
            self.assertEqual(second.view.status, 'connected')
            controller.close()

    def test_traffic_sampling_and_final_stop_are_independent_of_counter_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            controller, _ = self.controller(Path(directory))
            entry = controller.entries[controller.collection.windows[0].id]
            manager = FakeManager()
            manager.running = True
            manager.traffic = Mock(identity='sample-process')
            manager.traffic.read.return_value = 123456
            entry.manager, entry.view.status = manager, 'connected'
            controller._measure_traffic(entry, entry.view.generation)
            self.assertEqual(entry.view.traffic_bytes, 123456)
            manager.traffic.read.return_value = 123999
            controller.stop(entry.view.connection.id)
            wait_for(lambda: entry.view.status == 'offline')
            self.assertEqual(entry.view.traffic_bytes, 123999)
            self.assertFalse(manager.running)
            manager.running = True
            entry.manager, entry.view.status = manager, 'connected'
            manager.traffic.read.side_effect = RuntimeError('bad counter')
            controller._measure_traffic(entry, entry.view.generation)
            self.assertTrue(manager.running)
            self.assertEqual(entry.view.status, 'connected')
            self.assertTrue(entry.view.traffic_error)
            controller.stop(entry.view.connection.id)
            wait_for(lambda: entry.view.status == 'offline')
            self.assertFalse(manager.running, 'A broken counter must not prevent disconnect')
            controller.close()

    def test_failed_save_keeps_connection_and_port_ownership_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            controller, profile = self.controller(Path(directory))
            connection = controller.collection.windows[0]
            original = deepcopy(connection)
            before = dict(controller.ports.reserved)
            with patch.object(controller.store, 'save_connections', side_effect=OSError('Disk full')):
                with self.assertRaises(OSError):
                    controller.configure(connection.id, http_port=31001, socks_port=31002, fixed_ports=True)
            self.assertEqual(connection, original)
            self.assertEqual(controller.ports.reserved, before)

    def test_system_ping_arrives_immediately_and_is_not_the_https_duration(self):
        class Vpn(FakeManager):
            latency = 609
            def connect(self, profile, dns, cancel): self.running = True
            def heartbeat(self): return self.latency
        with tempfile.TemporaryDirectory() as directory:
            controller, _ = self.controller(Path(directory))
            controller.vpn_factory = Vpn
            controller.latency_reader = Mock(return_value=37)
            controller.start('system')
            entry = controller.entries['system']
            wait_for(lambda: entry.view.latency == 37)
            self.assertEqual(entry.view.status, 'connected')
            self.assertFalse(entry.view.latency_pending)
            controller._check(entry, entry.view.generation)
            self.assertEqual(entry.view.latency, 37)
            self.assertEqual(entry.view.latency_kind, 'tcp')
            controller.close()

    def test_failed_ping_does_not_disconnect_a_healthy_window(self):
        with tempfile.TemporaryDirectory() as directory, patch('outward_app.core.sessions.find_sing_box', return_value='test.exe'), \
                patch('outward_app.core.sessions.session_dir', side_effect=lambda cid: Path(directory) / cid):
            controller, _ = self.controller(Path(directory))
            controller.latency_reader = lambda *args: None
            cid = controller.collection.windows[0].id
            controller.start(cid)
            entry = controller.entries[cid]
            wait_for(lambda: entry.view.status == 'connected' and not entry.view.latency_pending)
            self.assertIsNone(entry.view.latency)
            self.assertEqual(entry.manager.stops, 0)
            self.assertTrue(entry.manager.running)
            controller.close()

    def test_udp_system_keeps_the_initial_https_metric_without_tcp_ping(self):
        from test_core import WIREGUARD_CONFIG
        class Vpn(FakeManager):
            latency = 609
            def connect(self, profile, dns, cancel): self.running = True
        with tempfile.TemporaryDirectory() as directory:
            controller, profile = self.controller(Path(directory))
            controller.profiles[profile.id].link = WIREGUARD_CONFIG
            controller.vpn_factory = Vpn
            controller.latency_reader = Mock()
            controller.start('system')
            wait_for(lambda: controller.entries['system'].view.status == 'connected')
            self.assertEqual(controller.entries['system'].view.latency, 609)
            self.assertEqual(controller.entries['system'].view.latency_kind, 'https')
            controller.latency_reader.assert_not_called()
            controller.close()

    def test_cancelled_ping_does_not_publish_a_late_value(self):
        entered, release = threading.Event(), threading.Event()
        def late(*args):
            entered.set()
            release.wait(2)
            return 999
        with tempfile.TemporaryDirectory() as directory, patch('outward_app.core.sessions.find_sing_box', return_value='test.exe'), \
                patch('outward_app.core.sessions.session_dir', side_effect=lambda cid: Path(directory) / cid):
            controller, _ = self.controller(Path(directory))
            controller.latency_reader = late
            cid = controller.collection.windows[0].id
            controller.start(cid)
            self.assertTrue(entered.wait(2))
            controller.stop(cid)
            wait_for(lambda: controller.entries[cid].view.status == 'offline')
            release.set()
            controller.close()
            self.assertIsNone(controller.entries[cid].view.latency)

    def test_initial_probe_failure_does_not_restart_the_core(self):
        probe = Mock(side_effect=[OSError('warming up'), 24])
        with tempfile.TemporaryDirectory() as directory, patch('outward_app.core.sessions.find_sing_box', return_value='test.exe'), \
                patch('outward_app.core.sessions.session_dir', side_effect=lambda cid: Path(directory) / cid):
            controller, _ = self.controller(Path(directory), probe)
            cid = controller.collection.windows[0].id
            controller.start(cid)
            wait_for(lambda: controller.entries[cid].view.status == 'connected')
            self.assertEqual(probe.call_count, 2)
            self.assertEqual(controller.entries[cid].manager.starts, 1)
            controller.close()

    def test_system_probe_recovers_without_restart_then_requires_two_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            probe = Mock(side_effect=[OSError('temporary'), 35, OSError('down'), OSError('down')])
            broker = VpnBroker(Path(directory), Path('test.exe'), network_reader=lambda: NetworkInfo('Ethernet', 'n'),
                               probe=probe, route_check=lambda: True)
            broker.status, broker.network = 'connected', 'n'
            broker.manager = FakeManager()
            broker.manager.running = True
            for status in ['connected', 'connected', 'connected', 'error']:
                broker.last_probe = time.monotonic() - 21
                broker.tick()
                self.assertEqual(broker.status, status)
            self.assertEqual(broker.manager.stops, 0)
            self.assertTrue(broker.retryable)
            broker.stop()

    def test_cancelled_connect_cannot_publish_a_late_success(self):
        entered, release = threading.Event(), threading.Event()
        def probe(port, cancel):
            entered.set()
            release.wait(2)
            return 42  # Deliberately late success from a non-cooperative external call.
        with tempfile.TemporaryDirectory() as directory, patch('outward_app.core.sessions.find_sing_box', return_value='test.exe'), \
                patch('outward_app.core.sessions.session_dir', side_effect=lambda cid: Path(directory) / cid):
            controller, profile = self.controller(Path(directory), probe)
            cid = controller.collection.windows[0].id
            controller.start(cid)
            self.assertTrue(entered.wait(2))
            controller.stop(cid)
            release.set()
            wait_for(lambda: controller.entries[cid].view.status == 'offline')
            self.assertIsNone(controller.entries[cid].manager)
            self.assertEqual(controller.ports.reserved[cid], (27182, 27183))
            self.assertIsNone(controller.entries[cid].view.runtime)
            controller.close()

    def test_failed_connection_does_not_expose_credentials_or_stop_a_neighbor(self):
        def probe(port, cancel):
            if port == 27184:
                raise OSError('failure "password": "private-value" ss://secret@example.org')
            return 9
        with tempfile.TemporaryDirectory() as directory, patch('outward_app.core.sessions.find_sing_box', return_value='test.exe'), \
                patch('outward_app.core.sessions.session_dir', side_effect=lambda cid: Path(directory) / cid):
            controller, profile = self.controller(Path(directory), probe)
            one = controller.collection.windows[0].id
            two = controller.add_window(profile.id, fixed_ports=True, http_port=27184, socks_port=27185).id
            controller.start(one)
            wait_for(lambda: controller.entries[one].view.status == 'connected')
            controller.start(two)
            wait_for(lambda: controller.entries[two].view.status == 'error')
            self.assertEqual(controller.entries[one].view.status, 'connected')
            message = controller.entries[two].view.message
            self.assertNotIn('private-value', message)
            self.assertNotIn('ss://secret', message)
            controller.close()

    def test_tun_config_has_no_browser_or_user_proxy_ports_and_uses_bootstrap_dns(self):
        config = build_session_config(parse_connection(LINK), system=True, interface='Ethernet', custom_dns='1.1.1.1')
        self.assertEqual([item['type'] for item in config['inbounds']], ['tun'])
        self.assertEqual(config['route']['default_interface'], 'Ethernet')
        self.assertEqual(config['route']['default_domain_resolver'], 'bootstrap-dns')
        self.assertEqual(config['dns']['servers'][0]['detour'], 'proxy')
        bootstrap = next(server for server in config['dns']['servers'] if server['tag'] == 'bootstrap-dns')
        self.assertNotIn('detour', bootstrap)
        self.assertEqual(bootstrap['bind_interface'], 'Ethernet')
        self.assertNotIn('listen_port', config['inbounds'][0])

    def test_browser_profile_follows_connection_id_and_never_falls_back_direct(self):
        with tempfile.TemporaryDirectory() as directory, patch('outward_app.core.browser.app_data_dir', return_value=Path(directory)), \
                patch('outward_app.core.browser.find_proxy_browser', return_value='chrome.exe'), \
                patch('outward_app.core.browser._browser_profiles_in_use', return_value=set()), \
                patch('outward_app.core.browser.subprocess.Popen') as launch:
            open_url_with_proxy(18081, connection_id='window-a')
            first = launch.call_args.args[0]
            open_url_with_proxy(19081, connection_id='window-a')
            second = launch.call_args.args[0]
            self.assertEqual(next(a for a in first if a.startswith('--user-data-dir')), next(a for a in second if a.startswith('--user-data-dir')))
            self.assertIn('--proxy-server=socks5://127.0.0.1:19081', second)
            with patch('outward_app.core.browser.find_proxy_browser', return_value=None):
                self.assertFalse(open_url_with_proxy(18081, connection_id='window-a'))
            self.assertEqual(launch.call_count, 2)

    def test_changing_ports_does_not_silently_reuse_a_browser_with_old_proxy_flags(self):
        with tempfile.TemporaryDirectory() as directory, patch('outward_app.core.browser.app_data_dir', return_value=Path(directory)), \
                patch('outward_app.core.browser.find_proxy_browser', return_value='chrome.exe'), \
                patch('outward_app.core.browser.subprocess.Popen') as launch:
            open_url_with_proxy(18081, connection_id='window-a')
            profile_dir = str((Path(directory) / 'chrome_proxy_profile_window-a').resolve())
            with patch('outward_app.core.browser._browser_profiles_in_use', return_value={os.path.normcase(profile_dir)}):
                with self.assertRaisesRegex(OSError, 'закройте'):
                    open_url_with_proxy(19081, connection_id='window-a')
            self.assertEqual(launch.call_count, 1)

    def test_broker_rejects_another_owner_unknown_commands_and_external_plugins(self):
        with tempfile.TemporaryDirectory() as directory:
            broker = VpnBroker(Path(directory), Path('test.exe'))
            broker.lease, broker.pid = 'a' * 36, 7
            base = {'version': 1, 'lease': 'a' * 36}
            self.assertIn('другим', broker.dispatch({**base, 'command': 'stop'}, 8)['error'])
            self.assertIn('не поддерживается', broker.dispatch({**base, 'command': 'shell'}, 7)['error'])
            self.assertFalse(broker.cancel.is_set())
            self.assertIn('версия', broker.dispatch({**base, 'version': 100, 'command': 'start'}, 7)['error'])

    def test_broker_requires_os_tun_route_even_if_network_probe_succeeds(self):
        class DeadManager(FakeManager):
            def is_running(self):
                return False
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            broker = VpnBroker(Path(directory), Path('test.exe'), manager_factory=DeadManager,
                network_reader=lambda: NetworkInfo('Ethernet', 'n'), probe=lambda *args: calls.append(args), route_check=lambda: True)
            broker._start(parse_connection(LINK), '1.1.1.1', threading.Event())
            self.assertEqual(broker.status, 'error')
            self.assertFalse(calls)
            self.assertFalse((Path(directory) / 'config.json').exists())


if __name__ == '__main__':
    unittest.main()
