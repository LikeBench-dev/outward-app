import socket
import struct
import threading
import time
import unittest
from unittest.mock import Mock, patch

from outward_app.core.network import AddressCache, _headers, tcp_latency, wait_for_route


class NetworkTests(unittest.TestCase):
    def test_tcp_ping_excludes_dns_and_binds_the_physical_interface(self):
        events = []
        sock = Mock()
        sock.__enter__ = Mock(return_value=sock)
        sock.__exit__ = Mock(return_value=False)
        sock.connect.side_effect = lambda address: events.append('connect')
        def resolve(*args):
            events.append('dns')
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.0.2.1', 443))]
        stamps = iter([10.0, 10.024])
        def counter():
            events.append('clock')
            return next(stamps)
        with patch('outward_app.core.network._PING_ADDRESSES.resolve', side_effect=resolve), \
             patch('outward_app.core.network.socket.socket', return_value=sock), \
             patch('outward_app.core.network.time.perf_counter', side_effect=counter):
            value = tcp_latency('vpn.example', 443, 7)
        self.assertEqual(value, 24)
        self.assertEqual(events, ['dns', 'clock', 'connect', 'clock'])
        if __import__('os').name == 'nt':
            sock.setsockopt.assert_called_once_with(socket.IPPROTO_IP, 31, struct.pack('!I', 7))

    def test_real_loopback_tcp_ping_and_closed_port(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            self.assertIsInstance(tcp_latency('127.0.0.1', port), int)
        self.assertIsNone(tcp_latency('127.0.0.1', port, timeout=.2))

    def test_slow_dns_is_bounded_and_cancellable(self):
        release = threading.Event()
        done = threading.Event()
        cache = AddressCache()
        def resolve(*args, **kwargs):
            release.wait(2)
            done.set()
            return []
        try:
            with patch('outward_app.core.network.socket.getaddrinfo', side_effect=resolve):
                started = time.monotonic()
                self.assertEqual(cache.resolve('slow.example', 443, started + .1, threading.Event()), [])
                self.assertLess(time.monotonic() - started, .5)
                cancel = threading.Event()
                cancel.set()
                self.assertEqual(cache.resolve('slow.example', 443, time.monotonic() + 2, cancel), [])
                release.set()
                self.assertTrue(done.wait(1))
        finally:
            release.set()

    def test_startup_probe_retries_in_place_and_stops_on_cancel(self):
        cancel = threading.Event()
        probe = Mock(side_effect=[OSError('warming up'), 42])
        with patch.object(cancel, 'wait', return_value=False):
            self.assertEqual(wait_for_route(probe, 1080, cancel, lambda: True), 42)
        self.assertEqual(probe.call_count, 2)
        cancel.set()
        with self.assertRaises(InterruptedError):
            wait_for_route(probe, 1080, cancel, lambda: True)
        self.assertEqual(probe.call_count, 2)

    def test_dead_core_does_not_retry_route_checks(self):
        probe = Mock(side_effect=OSError('core stopped'))
        with self.assertRaises(OSError):
            wait_for_route(probe, 1080, threading.Event(), lambda: False)
        self.assertEqual(probe.call_count, 1)

    def test_slow_response_cannot_extend_the_probe_deadline(self):
        sock = Mock()
        sock.recv.return_value = b'a'
        with patch('outward_app.core.network.time.monotonic', side_effect=[0, 1, 13]):
            with self.assertRaises(TimeoutError):
                _headers(sock, deadline=12)
        self.assertEqual(sock.recv.call_count, 2)
