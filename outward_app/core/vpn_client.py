from __future__ import annotations

import time
from uuid import uuid4

from outward_app.core.vpn_pipe import request, service_status


class VpnSetupError(RuntimeError):
    """Requires user action, rather than an automatic network retry loop."""


class VpnClient:
    def __init__(self):
        self.lease = str(uuid4())
        self.connected = False
        self.latency = None
        self.started = False

    def connect(self, profile, dns, cancel):
        try:
            request({"command": "start", "lease": self.lease, "link": profile.link, "dns": dns})
        except OSError as exc:
            raise VpnSetupError(str(exc)) from exc
        self.started = True
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if cancel.wait(0.5):
                self.stop()
                raise InterruptedError("Подключение отменено")
            response = request({"command": "heartbeat", "lease": self.lease})
            if response["status"] == "error":
                error = OSError if response.get("retryable") else VpnSetupError
                raise error(response.get("message") or "Не удалось включить системный VPN")
            if response["status"] == "connected":
                self.connected = True
                self.latency = response.get("latency")
                return
        self.stop()
        raise TimeoutError("Истекло время подключения системного VPN")

    def stop(self):
        if not self.started:
            self.connected = False
            return
        try:
            try:
                request({"command": "stop", "lease": self.lease})
            except OSError:
                if service_status()[0] in (0, 1):
                    self.started = False
                    return
                raise
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                response = request({"command": "status", "lease": self.lease})
                if response["status"] == "offline":
                    self.started = False
                    return
                time.sleep(0.2)
            raise TimeoutError("Системное подключение еще отключается")
        finally:
            self.connected = False

    def is_running(self):
        return self.connected

    def heartbeat(self):
        response = request({"command": "heartbeat", "lease": self.lease})
        if response["status"] != "connected":
            self.connected = False
            raise OSError(response.get("message") or "Системное подключение остановлено")
        self.latency = response.get("latency")
        return self.latency

    def log_text(self):
        return request({"command": "log", "lease": self.lease}).get("log", "")

    def traffic_usage(self):
        response = request({'command': 'traffic', 'lease': self.lease})
        total, month = response.get('traffic_bytes'), response.get('traffic_month')
        if type(total) is not int or total < 0 or not isinstance(month, str):
            raise OSError(response.get('traffic_error') or 'Обновите службу системного VPN для учёта трафика')
        return month, total
