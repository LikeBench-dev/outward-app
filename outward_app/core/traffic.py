"""Per-connection payload traffic, persisted by local calendar month."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import http.client
import json
from pathlib import Path
import secrets
import socket
import threading
from uuid import uuid4

from outward_app.core.storage import atomic_write_json


def current_month() -> str:
    return datetime.now().strftime('%Y-%m')


def format_traffic(value: int | None) -> str:
    if value is None:
        return '—'
    for unit in ('Б', 'КБ', 'МБ', 'ГБ', 'ТБ'):
        if value < 1000 or unit == 'ТБ':
            return (str(int(value)) if unit == 'Б' else f'{value:.1f}'.replace('.', ',')) + ' ' + unit
        value /= 1000


class TrafficCounter:
    """Authenticated, loopback-only Clash API. Never follows the OS/browser proxy."""
    def __init__(self, config: dict):
        inbound_ports = {inbound.get('listen_port') for inbound in config.get('inbounds', [])}
        while True:
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                self.port = listener.getsockname()[1]
            if self.port not in inbound_ports:
                break
        self.secret = secrets.token_urlsafe(32)
        self.identity = str(uuid4())
        config.setdefault('experimental', {})['clash_api'] = {
            'external_controller': f'127.0.0.1:{self.port}', 'secret': self.secret,
            'access_control_allow_origin': ['http://localhost'],
            'access_control_allow_private_network': False,
        }

    def read(self) -> int:
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=1)
        try:
            connection.request('GET', '/connections', headers={'Authorization': 'Bearer ' + self.secret})
            response = connection.getresponse()
            if response.status != 200:
                raise OSError('Счётчик трафика временно недоступен')
            data = json.loads(response.read(8 * 1024 * 1024))
            values = [data.get('uploadTotal'), data.get('downloadTotal')]
            if any(type(value) is not int or value < 0 for value in values):
                raise ValueError('Некорректный ответ счётчика трафика')
            return sum(values)
        except http.client.HTTPException as exc:
            raise OSError('Счётчик трафика временно недоступен') from exc
        finally:
            connection.close()


class TrafficLedger:
    """Checkpoints prevent double counting on polling, reconnect and reload.

    A new process starts at zero. Month rollover carries only the delta since
    the previous sample into the new month, never the old process's full total.
    The boundary precision is the sampling interval (normally one second).
    """
    def __init__(self, path: Path | None, month_reader=current_month):
        self.path, self.month_reader = path, month_reader
        self.lock = threading.RLock()
        self.data = {'version': 1, 'months': {}, 'checkpoints': {}}
        self.error = ''
        if path and path.exists():
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                if data.get('version') != 1 or not isinstance(data.get('months'), dict) or not isinstance(data.get('checkpoints'), dict):
                    raise ValueError('Invalid traffic ledger')
                for month in data['months'].values():
                    if not isinstance(month, dict) or any(type(v) is not int or v < 0 for v in month.values()):
                        raise ValueError('Invalid traffic totals')
                for checkpoint in data['checkpoints'].values():
                    if not isinstance(checkpoint, dict) or not isinstance(checkpoint.get('source'), str) or type(checkpoint.get('total')) is not int or checkpoint['total'] < 0:
                        raise ValueError('Invalid traffic checkpoint')
                self.data = data
            except (OSError, ValueError, TypeError, AttributeError):
                # Do not silently replace a user's unreadable history with zero.
                self.error = 'Не удалось прочитать сохранённую статистику трафика'

    def usage(self, connection_id: str) -> tuple[str, int | None]:
        with self.lock:
            month = self.month_reader()
            return month, None if self.error else self.data['months'].get(month, {}).get(connection_id, 0)

    def record(self, connection_id: str, source: str, total: int) -> tuple[str, int]:
        if type(total) is not int or total < 0:
            raise ValueError('Invalid traffic sample')
        with self.lock:
            if self.error:
                raise OSError(self.error)
            data = deepcopy(self.data)
            previous = data['checkpoints'].get(connection_id, {})
            baseline = previous.get('total', 0) if previous.get('source') == source else 0
            # A core may reset its statistics; count its new total once.
            delta = total - baseline if total >= baseline else total
            month = self.month_reader()
            bucket = data['months'].setdefault(month, {})
            bucket[connection_id] = bucket.get(connection_id, 0) + delta
            data['checkpoints'][connection_id] = {'source': source, 'total': total}
            if self.path and data != self.data:
                atomic_write_json(self.path, data)
            self.data = data
            return month, bucket[connection_id]

    def set_usage(self, connection_id: str, month: str, total: int) -> None:
        """Cache an absolute service-owned monthly total; never add it twice."""
        if type(total) is not int or total < 0 or month != self.month_reader():
            raise ValueError('Invalid monthly traffic total')
        with self.lock:
            if self.error:
                raise OSError(self.error)
            data = deepcopy(self.data)
            data['months'].setdefault(month, {})[connection_id] = total
            if self.path and data != self.data:
                atomic_write_json(self.path, data)
            self.data = data
