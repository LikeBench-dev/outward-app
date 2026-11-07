import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from outward_app.core.traffic import TrafficCounter, TrafficLedger, format_traffic
from outward_app.core.vpn_client import VpnClient
from outward_app.core.vpn_service import VpnBroker


class TrafficTests(unittest.TestCase):
    def test_month_totals_survive_reload_polling_reconnect_and_counter_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'traffic.json'
            month = ['2026-11']
            ledger = TrafficLedger(path, lambda: month[0])
            self.assertEqual(ledger.record('one', 'process-a', 100), ('2026-11', 100))
            self.assertEqual(ledger.record('one', 'process-a', 140)[1], 140)
            self.assertEqual(ledger.record('two', 'process-b', 999)[1], 999)
            ledger = TrafficLedger(path, lambda: month[0])
            self.assertEqual(ledger.record('one', 'process-a', 140)[1], 140)
            self.assertEqual(ledger.record('one', 'process-c', 20)[1], 160)
            self.assertEqual(ledger.record('one', 'process-c', 5)[1], 165)
            month[0] = '2026-12'
            self.assertEqual(ledger.usage('one')[1], 0)
            self.assertEqual(ledger.record('one', 'process-c', 35), ('2026-12', 30))
            self.assertEqual(ledger.usage('two')[1], 0)
            self.assertEqual(json.loads(path.read_text())['months']['2026-11']['one'], 165)

    def test_failed_write_can_retry_without_losing_or_duplicating_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = TrafficLedger(Path(directory) / 'traffic.json')
            ledger.record('one', 'a', 100)
            with patch('outward_app.core.traffic.atomic_write_json', side_effect=OSError('Disk full')):
                with self.assertRaises(OSError):
                    ledger.record('one', 'a', 150)
            self.assertEqual(ledger.usage('one')[1], 100)
            self.assertEqual(ledger.record('one', 'a', 180)[1], 180)

    def test_unreadable_history_is_not_overwritten_with_a_fake_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'traffic.json'
            path.write_text('{broken')
            ledger = TrafficLedger(path)
            self.assertIsNone(ledger.usage('one')[1])
            with self.assertRaises(OSError):
                ledger.record('one', 'a', 10)
            self.assertEqual(path.read_text(), '{broken')

    def test_system_total_is_cached_as_absolute_not_added_to_window_counters(self):
        ledger = TrafficLedger(None, lambda: '2026-11')
        ledger.record('one', 'a', 123)
        ledger.set_usage('system', '2026-11', 456)
        ledger.set_usage('system', '2026-11', 456)
        self.assertEqual(ledger.usage('system')[1], 456)
        self.assertEqual(ledger.usage('one')[1], 123)

    def test_service_traffic_query_is_owner_checked_and_survives_stop_and_restart(self):
        lease = '123e4567-e89b-12d3-a456-426614174000'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            broker = VpnBroker(path, path / 'test.exe')
            broker.traffic.record('system', 'a', 1024)
            broker.lease, broker.pid = lease, 12
            denied = broker.dispatch({'version': 1, 'command': 'traffic', 'lease': lease}, 13)
            self.assertIn('error', denied)
            reply = broker.dispatch({'version': 1, 'command': 'traffic', 'lease': lease}, 12)
            self.assertEqual(reply['traffic_bytes'], 1024)
            broker.stop()
            restarted = VpnBroker(path, path / 'test.exe')
            self.assertEqual(restarted.dispatch({'version': 1, 'command': 'traffic', 'lease': lease}, 12)['traffic_bytes'], 1024)
            with patch('outward_app.core.vpn_client.request', return_value=reply):
                self.assertEqual(VpnClient().traffic_usage(), (reply['traffic_month'], 1024))
            with patch('outward_app.core.vpn_client.request', return_value={'status': 'connected'}):
                with self.assertRaises(OSError):
                    VpnClient().traffic_usage()

    def test_display_and_private_api_configuration(self):
        self.assertEqual(format_traffic(None), '—')
        self.assertEqual(format_traffic(0), '0 Б')
        self.assertEqual(format_traffic(12_400_000_000), '12,4 ГБ')
        config = {}
        first, second = TrafficCounter(config), TrafficCounter({})
        api = config['experimental']['clash_api']
        self.assertTrue(api['external_controller'].startswith('127.0.0.1:'))
        self.assertNotEqual(first.secret, second.secret)
        self.assertGreaterEqual(len(api['secret']), 32)


if __name__ == '__main__':
    unittest.main()
