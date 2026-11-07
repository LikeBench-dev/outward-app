"""Real sing-box / Windows job integration, loopback only. Never creates a TUN."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import ExitStack
import base64
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest

from outward_app.core.connections import parse_connection
from outward_app.core.singbox import SingBoxManager, build_session_config, write_config
from outward_app.core.traffic import TrafficCounter, TrafficLedger

KERNEL = Path(__file__).resolve().parents[1] / 'bin' / 'sing-box.exe'


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = b'outward-test-traffic' * 8192
        self.send_response(200)
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_HEAD(self):
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


@unittest.skipUnless(os.name == 'nt' and KERNEL.exists(), 'Requires bundled Windows sing-box')
class RuntimeTests(unittest.TestCase):
    def test_real_payload_totals_are_private_cumulative_and_isolated_per_process(self):
        import http.client
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory() as directory, ExitStack() as cleanup:
                path = Path(directory)
                ledger = TrafficLedger(path / 'traffic.json')
                running = []
                for index in range(2):
                    http_port = free_port()
                    config = {'inbounds': [{'type': 'http', 'listen': '127.0.0.1', 'listen_port': http_port}],
                              'outbounds': [{'type': 'direct', 'tag': 'proxy'}], 'route': {'final': 'proxy'}}
                    counter = TrafficCounter(config)
                    config_file = path / f'window-{index}.json'
                    write_config(config, config_file)
                    manager = SingBoxManager(config_file, path / f'window-{index}.log')
                    cleanup.callback(manager.stop)
                    manager.check_config(str(KERNEL))
                    manager.start(str(KERNEL))
                    manager.wait_for_ports([http_port, counter.port])
                    running.append((manager, counter, http_port))
                self.assertEqual(running[0][1].read(), 0)
                unauthorized = http.client.HTTPConnection('127.0.0.1', running[0][1].port, timeout=2)
                try:
                    unauthorized.request('GET', '/connections')
                    self.assertEqual(unauthorized.getresponse().status, 401)
                finally:
                    unauthorized.close()
                with socket.create_connection(('127.0.0.1', running[0][2]), timeout=3) as proxy:
                    proxy.sendall(f'GET http://127.0.0.1:{server.server_port}/ HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n'.encode())
                    received = bytearray()
                    while chunk := proxy.recv(65536):
                        received.extend(chunk)
                self.assertIn(b'outward-test-traffic', received)
                first = running[0][1]
                total = first.read()
                self.assertGreaterEqual(total, len(b'outward-test-traffic') * 8192)
                self.assertEqual(ledger.record('one', first.identity, total)[1], total)
                self.assertEqual(ledger.record('one', first.identity, first.read())[1], total)
                self.assertEqual(running[1][1].read(), 0)
                running[0][0].stop()
                self.assertEqual(running[1][1].read(), 0)
                self.assertEqual(TrafficLedger(path / 'traffic.json').usage('one')[1], total)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(2)

    def test_generated_window_config_starts_without_bootstrap_dns_detour_failure(self):
        # No user credentials, outbound traffic or TUN: startup validates DNS dialers even unused.
        public = base64.urlsafe_b64encode(bytes(range(1, 33))).decode().rstrip('=')
        links = ['ss://YWVzLTI1Ni1nY206c2VjcmV0@127.0.0.1:8388#Local',
                 f'vless://123e4567-e89b-12d3-a456-426614174000@127.0.0.1:443?security=reality&sni=example.com&pbk={public}&sid=abcd&type=tcp']
        for link in links:
            for dns in ('', '1.1.1.1'):
                with self.subTest(protocol=link.split(':')[0], dns=dns), tempfile.TemporaryDirectory() as directory:
                    http, socks = free_port(), free_port()
                    while socks == http:
                        socks = free_port()
                    path = Path(directory) / 'config.json'
                    write_config(build_session_config(parse_connection(link), http_port=http, socks_port=socks,
                                 custom_dns=dns), path)
                    manager = SingBoxManager(path, Path(directory) / 'core.log')
                    try:
                        manager.check_config(str(KERNEL))
                        manager.start(str(KERNEL))
                        manager.wait_for_ports([http, socks])
                        self.assertTrue(manager.is_running())
                    finally:
                        manager.stop()

    def test_generated_protocol_configs_are_accepted_by_pinned_kernel_in_both_modes(self):
        # Synthetic keys and reserved example hosts; check never opens a connection or TUN.
        key = base64.b64encode(bytes(range(1, 33))).decode()
        public = base64.urlsafe_b64encode(bytes(range(1, 33))).decode().rstrip('=')
        links = [
            'ss://YWVzLTI1Ni1nY206c2VjcmV0@example.net:8388#Test',
            f'vless://123e4567-e89b-12d3-a456-426614174000@example.com:443?security=reality&sni=example.com&pbk={public}&sid=abcd&type=tcp',
            f'[Interface]\nPrivateKey = {key}\nAddress = 10.2.0.2/32\nDNS = 1.1.1.1\n[Peer]\nPublicKey = {key}\nEndpoint = wg.example.net:51820\nAllowedIPs = 0.0.0.0/0, ::/0',
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            for link in links:
                parsed = parse_connection(link)
                for system in (False, True):
                    with self.subTest(protocol=parsed.protocol, system=system):
                        write_config(build_session_config(parsed, http_port=18080, socks_port=18081,
                                     system=system, interface='Ethernet', custom_dns='1.1.1.1'), path)
                        SingBoxManager(path, Path(directory) / 'check.log').check_config(str(KERNEL))

    def test_two_real_processes_http_and_socks_and_independent_stop(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        managers = []
        try:
            with ExitStack() as cleanup:
                directory = cleanup.enter_context(tempfile.TemporaryDirectory())
                ports = set()
                def allocate():
                    port = free_port()
                    while port in ports:
                        port = free_port()
                    ports.add(port)
                    return port
                for number in range(2):
                    http, socks = allocate(), allocate()
                    config = Path(directory) / f'window-{number}.json'
                    write_config({'inbounds': [
                        {'type': 'http', 'listen': '127.0.0.1', 'listen_port': http},
                        {'type': 'socks', 'listen': '127.0.0.1', 'listen_port': socks}],
                        'outbounds': [{'type': 'direct', 'tag': 'proxy'}], 'route': {'final': 'proxy'}}, config)
                    manager = SingBoxManager(config, Path(directory) / f'window-{number}.log')
                    cleanup.callback(manager.stop)
                    managers.append(manager)
                    manager.check_config(str(KERNEL))
                    manager.start(str(KERNEL))
                    manager.wait_for_ports([http, socks])
                    with socket.create_connection(('127.0.0.1', http), timeout=3) as proxy:
                        proxy.sendall(f'HEAD http://127.0.0.1:{server.server_port}/ HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n'.encode())
                        self.assertIn(b'204', proxy.recv(1024).split(b'\r\n', 1)[0])
                    with socket.create_connection(('127.0.0.1', socks), timeout=3) as proxy:
                        proxy.sendall(b'\x05\x01\x00')
                        self.assertEqual(proxy.recv(2), b'\x05\x00')
                        proxy.sendall(b'\x05\x01\x00\x01\x7f\x00\x00\x01' + server.server_port.to_bytes(2, 'big'))
                        self.assertEqual(proxy.recv(10)[:2], b'\x05\x00')
                        proxy.sendall(b'HEAD / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n')
                        self.assertIn(b'204', proxy.recv(1024).split(b'\r\n', 1)[0])
                first_process = managers[0].process
                managers[0].stop()
                self.assertEqual(first_process.returncode, 0, 'Owned core must receive a graceful shutdown signal')
                self.assertFalse(managers[0].is_running())
                self.assertTrue(managers[1].is_running())
                for manager in managers:
                    manager.stop()
                managers.clear()
        finally:
            for manager in managers:
                manager.stop()
            server.shutdown()
            server.server_close()
            thread.join(2)
