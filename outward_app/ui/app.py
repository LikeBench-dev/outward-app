from __future__ import annotations

import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from outward_app.app_info import APP_NAME
from outward_app.core.singbox import rotate_logs_on_app_start
from outward_app.paths import asset_path
from outward_app.ui.main_window import MainWindow
from outward_app.ui.styles import APP_STYLE


SINGLE_INSTANCE_SERVER_NAME = "outward-app-single-instance"
SINGLE_INSTANCE_TIMEOUT_MS = 500


def notify_existing_instance(server_name: str = SINGLE_INSTANCE_SERVER_NAME) -> bool:
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if not socket.waitForConnected(SINGLE_INSTANCE_TIMEOUT_MS):
        socket.abort()
        return False
    socket.write(b"activate")
    socket.flush()
    socket.waitForBytesWritten(SINGLE_INSTANCE_TIMEOUT_MS)
    socket.disconnectFromServer()
    return True


class SingleInstanceServer(QObject):
    activation_requested = Signal()

    def __init__(self, server_name: str = SINGLE_INSTANCE_SERVER_NAME, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._on_new_connection)
        self._is_listening = self.server.listen(server_name)
        if not self._is_listening:
            QLocalServer.removeServer(server_name)
            self._is_listening = self.server.listen(server_name)

    @property
    def is_listening(self) -> bool:
        return self._is_listening

    def _on_new_connection(self) -> None:
        requested = False
        while self.server.hasPendingConnections():
            client = self.server.nextPendingConnection()
            if client is None:
                continue
            requested = True
            client.readAll()
            client.disconnectFromServer()
            client.deleteLater()
        if requested:
            self.activation_requested.emit()


def apply_fluent_theme() -> None:
    try:
        from qfluentwidgets import Theme, setTheme, setThemeColor
    except ImportError:
        return

    setTheme(Theme.DARK)
    setThemeColor("#a84fff")


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    if notify_existing_instance():
        return 0
    single_instance_server = SingleInstanceServer(parent=app)
    apply_fluent_theme()
    app.setStyleSheet(APP_STYLE)

    icon = QIcon(str(asset_path("outward.ico")))
    if not icon.isNull():
        app.setWindowIcon(icon)

    rotate_logs_on_app_start()
    window = MainWindow()
    if single_instance_server.is_listening:
        single_instance_server.activation_requested.connect(window.restore_from_tray)
    if not icon.isNull():
        window.setWindowIcon(icon)
    window.resize(1100, 750)
    window.show()
    return app.exec()
