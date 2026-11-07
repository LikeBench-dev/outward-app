"""Exercise the real Windows named pipe without installing a service or changing the network."""
import os
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from outward_app.core.vpn_install import user_sid
from outward_app.core.vpn_pipe import PipeServer, request


@unittest.skipUnless(os.name == 'nt', 'Windows named pipe integration')
class PipeTests(unittest.TestCase):
    def test_acl_pipe_roundtrip_and_server_identity(self):
        address = r'\\.\pipe\OutwardTest-' + uuid4().hex
        stop = threading.Event()
        received = []
        with patch('outward_app.core.vpn_pipe.PIPE_NAME', address):
            server = PipeServer(user_sid())
            def handle(payload, pid):
                received.append((payload, pid))
                return {'status': 'offline', 'marker': 'Ответ проверен'}
            def serve():
                while not stop.is_set():
                    server.serve_once(handle, stop)
                    stop.wait(.01)
            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            try:
                with patch('outward_app.core.vpn_pipe.service_pid', return_value=os.getpid()):
                    response = request({'command': 'status', 'lease': 'a'*36})
                self.assertEqual(response['marker'], 'Ответ проверен')
                self.assertEqual(received[0][1], os.getpid())
                self.assertEqual(received[0][0]['version'], 1)
                with patch('outward_app.core.vpn_pipe.service_pid', return_value=os.getpid()+1):
                    with self.assertRaisesRegex(OSError, 'владельца'):
                        request({'command': 'start', 'lease': 'a'*36})
                self.assertEqual(len(received), 1)
            finally:
                stop.set()
                thread.join(4)
                server.close()
                self.assertFalse(thread.is_alive())
