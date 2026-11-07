"""Proxy lifecycle tests use an in-memory Windows settings backend exclusively."""
import ctypes
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import test_sessions as fixtures
from outward_app.core.models import AppSettings, ConnectionCollection, SavedConnection
from outward_app.core.storage import atomic_write_json
from outward_app.core.system_proxy import (ProxySettings, SystemProxyLease, SystemProxyManager,
                                           WindowsProxySettings, process_identity, run_watchdog, _kernel)
from outward_app.core.traffic import current_month


class SettingsBackend:
    def __init__(self):
        self.current = ProxySettings(13, 'old-proxy:8080', '<local>;*.example.net', 'https://example.net/proxy.pac')
        self.writes = []
        self.fail = False
        self.fail_after_write = False

    def read(self):
        return self.current

    def write(self, settings):
        if self.fail:
            raise OSError('write denied')
        self.writes.append(settings)
        self.current = settings
        if self.fail_after_write:
            self.fail_after_write = False
            raise OSError('notification failed')


class ProxyLeaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(self.directory) / 'system-proxy.json'
        self.backend = SettingsBackend()
        self.original = self.backend.current
        self.lease = SystemProxyLease(self.path, self.backend, watchdog=False, identity_reader=lambda pid: 123)

    def test_restores_manual_pac_and_autodetect_settings_exactly(self):
        self.lease.acquire(31000)
        self.assertEqual(self.backend.current.flags, 3)
        self.assertEqual(self.backend.current.server, 'http=127.0.0.1:31000;https=127.0.0.1:31000')
        self.assertEqual(self.backend.current.pac_url, '')
        self.assertTrue(self.lease.is_owned())
        journal = json.loads(self.path.read_text())
        self.assertEqual(journal['original'], asdict(self.original))
        self.lease.release()
        self.assertEqual(self.backend.current, self.original)
        self.assertFalse(self.path.exists())
        self.lease.release()
        self.assertEqual(len(self.backend.writes), 2)

    def test_another_programs_changes_are_preserved(self):
        self.lease.acquire(31000)
        external = ProxySettings(9, '', '', '')
        self.backend.current = external
        self.assertFalse(self.lease.is_owned())
        self.lease.release()
        self.assertEqual(self.backend.current, external)
        self.assertFalse(self.path.exists())

    def test_recovery_restores_only_an_abandoned_owned_setting(self):
        self.lease.acquire(31000)
        recovery = SystemProxyLease(self.path, self.backend, watchdog=False, identity_reader=lambda pid: None)
        recovery.recover()
        self.assertEqual(self.backend.current, self.original)
        self.assertFalse(self.path.exists())

    def test_recovery_preserves_external_changes(self):
        self.lease.acquire(31000)
        self.backend.current = ProxySettings(1)
        SystemProxyLease(self.path, self.backend, watchdog=False, identity_reader=lambda pid: None).recover()
        self.assertEqual(self.backend.current, ProxySettings(1))
        self.assertEqual(len(self.backend.writes), 1)

    def test_live_owner_and_unreadable_journal_are_never_overwritten(self):
        self.lease.acquire(31000)
        before = self.path.read_bytes()
        with self.assertRaisesRegex(OSError, 'работающим'):
            SystemProxyLease(self.path, self.backend, watchdog=False, identity_reader=lambda pid: 123).recover()
        self.assertEqual(self.path.read_bytes(), before)
        self.path.write_text('{broken', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.lease.acquire(31001)
        self.assertEqual(len(self.backend.writes), 1)

    def test_disk_failure_never_changes_windows(self):
        with patch('outward_app.core.system_proxy.atomic_write_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.lease.acquire(31000)
        self.assertEqual(self.backend.current, self.original)
        self.assertEqual(self.backend.writes, [])

    def test_watchdog_failure_never_changes_windows(self):
        self.lease.watchdog = True
        with patch('outward_app.core.system_proxy.start_watchdog', side_effect=OSError('helper unavailable')):
            with self.assertRaises(OSError):
                self.lease.acquire(31000)
        self.lease.release()
        self.assertFalse(self.path.exists())
        self.assertEqual(self.backend.writes, [])

    def test_partial_apply_is_rolled_back(self):
        self.backend.fail_after_write = True
        with self.assertRaises(OSError):
            self.lease.acquire(31000)
        self.assertTrue(self.path.exists())
        self.lease.release()
        self.assertEqual(self.backend.current, self.original)

    def test_listener_stays_alive_until_restore_succeeds(self):
        core = fixtures.FakeManager()
        core.running = True
        manager = SystemProxyManager(core, self.lease)
        manager.activate(31000)
        self.backend.fail = True
        with self.assertRaises(OSError):
            manager.stop()
        self.assertTrue(core.running)
        self.assertTrue(self.path.exists())
        self.backend.fail = False
        manager.stop()
        self.assertEqual(self.backend.current, self.original)
        self.assertFalse(core.running)

    def test_invalid_port_and_watchdog_token_have_no_effect(self):
        for port in (0, 80, 65536, True, '31000'):
            with self.assertRaises(ValueError):
                self.lease.acquire(port)
        self.assertEqual(run_watchdog('invalid'), 1)
        self.assertEqual(self.backend.writes, [])

    @unittest.skipUnless(os.name == 'nt', 'Windows ABI')
    def test_native_snapshot_is_read_only_and_uses_correct_pointer_sizes(self):
        backend = WindowsProxySettings()
        snapshot = backend.read()  # No writes to real Windows settings in this suite.
        self.assertIsInstance(snapshot, ProxySettings)
        self.assertIsInstance(snapshot.server, str)
        self.assertIn(snapshot.flags, range(16))
        self.assertGreater(process_identity(os.getpid()), 0)
        self.assertEqual(ctypes.sizeof(backend.Option), 16 if ctypes.sizeof(ctypes.c_void_p) == 8 else 12)

    @unittest.skipUnless(os.name == 'nt', 'Windows ABI')
    def test_native_write_payload_and_notifications_with_fake_api(self):
        backend = WindowsProxySettings()
        seen = []
        def set_option(handle, flag, pointer, size):
            if flag == 75:
                options = ctypes.cast(pointer, ctypes.POINTER(backend.Options)).contents
                values = options.options
                seen.append((values[0].kind, values[0].value.number,
                             *[ctypes.wstring_at(values[i].value.string) for i in (1, 2, 3)]))
            else:
                seen.append(flag)
            return True
        backend.api = SimpleNamespace(InternetSetOptionW=set_option)
        backend.write(self.original)
        self.assertEqual(seen, [(1, self.original.flags, self.original.server,
                                self.original.bypass, self.original.pac_url), 39, 37])


@unittest.skipUnless(os.name == 'nt', 'Windows process handles and events')
class WatchdogTests(unittest.TestCase):
    def check_helper(self, stop_normally):
        """Exercise real process death/events with a file-backed fake proxy API."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            script = path / 'watcher.py'
            script.write_text('''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[3])
from outward_app.core import system_proxy as proxy
path = Path(sys.argv[1])
class Backend:
    def read(self):
        return proxy.ProxySettings.from_dict(json.loads(path.read_text())['applied'])
    def write(self, settings):
        (path.parent / 'restored.json').write_text(json.dumps(proxy.asdict(settings)))
lease_type = proxy.SystemProxyLease
proxy.SystemProxyLease = lambda **kwargs: lease_type(path, Backend(), watchdog=False)
raise SystemExit(proxy.run_watchdog(sys.argv[2]))
''', encoding='utf-8')
            token = uuid4().hex
            kernel = _kernel()
            ready = kernel.CreateEventW(None, True, False, 'Local\\OutwardProxyReady-' + token)
            stop = kernel.CreateEventW(None, True, False, 'Local\\OutwardProxyStop-' + token)
            owner = watcher = None
            try:
                owner = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                                         creationflags=subprocess.CREATE_NO_WINDOW)
                original = ProxySettings(9, 'old:8080', '<local>', '')
                atomic_write_json(path / 'system-proxy.json', {
                    'version': 1, 'pid': owner.pid, 'created': process_identity(owner.pid), 'token': token,
                    'original': asdict(original), 'applied': asdict(ProxySettings(3, 'fake-listener:31000')),
                })
                watcher = subprocess.Popen([sys.executable, str(script), str(path / 'system-proxy.json'),
                                            token, str(Path(__file__).resolve().parents[1])],
                                           creationflags=subprocess.CREATE_NO_WINDOW,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertEqual(kernel.WaitForSingleObject(ready, 5000), 0)
                if stop_normally:
                    kernel.SetEvent(stop)
                else:
                    owner.terminate()
                    owner.wait(timeout=5)
                output, error = watcher.communicate(timeout=5)
                self.assertEqual(watcher.returncode, 0, error.decode(errors='replace'))
                self.assertEqual((path / 'restored.json').exists(), not stop_normally)
                self.assertEqual((path / 'system-proxy.json').exists(), stop_normally)
                if not stop_normally:
                    self.assertEqual(json.loads((path / 'restored.json').read_text()), asdict(original))
            finally:
                kernel.SetEvent(stop)
                for process in (owner, watcher):
                    if process is not None:
                        if process.poll() is None:
                            process.terminate()
                        process.communicate(timeout=5)
                kernel.CloseHandle(ready)
                kernel.CloseHandle(stop)

    def test_parent_crash_restores_the_fake_backend(self):
        self.check_helper(False)

    def test_cooperative_stop_reaps_helper_without_restoring_twice(self):
        self.check_helper(True)


class FakeLease:
    def __init__(self):
        self.active = False
        self.owned = True
        self.acquire_hook = lambda: None
        self.releases = 0

    def acquire(self, port):
        self.port = port
        self.active = True
        self.acquire_hook()

    def release(self):
        self.active = False
        self.releases += 1

    def is_owned(self):
        return self.active and self.owned


class SystemProxySessionTests(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.case = fixtures.SessionTests()
        self.addCleanup(self.case.doCleanups)
        self.controller, self.profile = self.case.controller(directory)
        self.lease = FakeLease()
        self.controller.system_proxy_factory = lambda: self.lease
        self.controller.vpn_factory = Mock(side_effect=AssertionError('Proxy mode must not call VPN service'))
        self.enterContext(patch('outward_app.core.sessions.find_sing_box', return_value='test.exe'))
        self.enterContext(patch('outward_app.core.sessions.session_dir', side_effect=lambda cid: directory / cid))
        self.controller.configure('system', system_mode='proxy')
        self.entry = self.controller.entries['system']

    def start(self):
        self.controller.start('system')
        fixtures.wait_for(lambda: self.entry.view.status in {'connected', 'error'})
        self.assertEqual(self.entry.view.status, 'connected', self.entry.view.message)

    def test_proxy_and_window_have_independent_processes_ports_and_stop(self):
        window = self.controller.collection.windows[0]
        self.controller.start(window.id)
        self.start()
        fixtures.wait_for(lambda: self.controller.entries[window.id].view.status == 'connected')
        other = self.controller.entries[window.id]
        self.assertIsInstance(self.entry.manager, SystemProxyManager)
        self.assertNotEqual(self.entry.view.runtime.http_port, other.view.runtime.http_port)
        self.assertTrue(self.lease.active)
        self.assertEqual(self.lease.port, self.entry.view.runtime.http_port)
        config = json.loads(self.entry.manager.config.read_text())
        self.assertEqual([i['type'] for i in config['inbounds']], ['http', 'socks'])
        self.controller.stop('system')
        fixtures.wait_for(lambda: self.entry.view.status == 'offline')
        self.assertFalse(self.lease.active)
        self.assertTrue(other.manager.running)
        self.controller.vpn_factory.assert_not_called()

    def test_failed_readiness_never_enables_the_windows_proxy(self):
        self.controller.probe = Mock(side_effect=OSError('route unavailable'))
        self.controller.start('system')
        fixtures.wait_for(lambda: self.entry.view.status == 'error', timeout=5)
        self.assertFalse(self.lease.active)
        self.assertIsNone(self.entry.manager)
        self.assertNotIn('system', self.controller.ports.reserved)

    def test_selecting_proxy_does_not_reserve_a_fixed_windows_ports(self):
        window = self.controller.collection.windows[0]
        self.controller.configure(window.id, fixed_ports=True)
        self.controller.start(window.id)
        other = self.controller.entries[window.id]
        fixtures.wait_for(lambda: other.view.status in {'connected', 'error'})
        self.assertEqual(other.view.status, 'connected', other.view.message)
        self.assertEqual(other.view.runtime.http_port, window.http_port)
        self.start()
        self.assertNotEqual(self.entry.view.runtime.http_port, window.http_port)
        self.assertTrue(other.manager.running)

    def test_failure_and_cancellation_during_activation_restore_settings(self):
        def fail():
            raise OSError('apply failed')
        self.lease.acquire_hook = fail
        self.controller.start('system')
        fixtures.wait_for(lambda: self.entry.view.status == 'error')
        self.assertFalse(self.lease.active)
        self.lease.acquire_hook = lambda: self.controller.stop('system')
        self.controller.start('system')
        fixtures.wait_for(lambda: self.entry.view.status == 'offline')
        self.assertFalse(self.lease.active)
        self.assertIsNone(self.entry.manager)

    def test_active_mode_is_locked_and_persistence_failure_rolls_back(self):
        self.start()
        with self.assertRaises(ValueError):
            self.controller.configure('system', system_mode='tun')
        self.controller.stop('system')
        fixtures.wait_for(lambda: self.entry.view.status == 'offline')
        with patch.object(self.controller.store, 'save_connections', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.controller.configure('system', system_mode='tun')
        self.assertEqual(self.entry.view.connection.system_mode, 'proxy')

    def test_external_settings_change_stops_without_reconnect(self):
        self.start()
        core = self.entry.manager.manager
        self.lease.owned = False
        self.controller._check(self.entry, self.entry.view.generation)
        fixtures.wait_for(lambda: self.entry.view.status == 'offline')
        self.assertFalse(core.running)
        self.assertFalse(self.lease.active)
        self.assertIn('изменены', self.entry.view.message)

    def test_proxy_traffic_is_added_to_tun_total_and_survives_mode_changes(self):
        self.start()
        self.controller.traffic.set_usage('system', current_month(), 400)
        self.entry.manager.manager.traffic = Mock(identity='proxy-process')
        self.entry.manager.manager.traffic.read.return_value = 123
        self.controller._sample_traffic(self.entry)
        self.assertEqual(self.entry.view.traffic_bytes, 523)
        self.controller.stop('system')
        fixtures.wait_for(lambda: self.entry.view.status == 'offline')
        self.controller.configure('system', system_mode='tun')
        self.assertEqual(self.entry.view.traffic_bytes, 523)
        vpn = Mock()
        vpn.traffic_usage.return_value = (current_month(), 450)
        self.controller._sample_traffic(self.entry, vpn)
        self.assertEqual(self.entry.view.traffic_bytes, 573)

    def test_shutdown_releases_proxy(self):
        self.start()
        core = self.entry.manager.manager
        self.controller.close()
        self.assertFalse(self.lease.active)
        self.assertFalse(core.running)

    def test_default_migration_persistence_and_window_mode_validation(self):
        legacy = ConnectionCollection().to_dict()
        del legacy['system']['system_mode']
        self.assertEqual(ConnectionCollection.from_dict(legacy).system.system_mode, 'tun')
        loaded = self.controller.store.load_connections(AppSettings())
        self.assertEqual(loaded.system.system_mode, 'proxy')
        with self.assertRaises(ValueError):
            SavedConnection(id='window', number=1, system_mode='proxy')
        with self.assertRaises(ValueError):
            SavedConnection(id='system', kind='system', system_mode='unknown')


if __name__ == '__main__':
    unittest.main()
