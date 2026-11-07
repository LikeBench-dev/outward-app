from __future__ import annotations

from outward_app.ui.i18n import tr

import sys
import hashlib
import os

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from outward_app.app_info import APP_NAME
from outward_app.core.singbox import rotate_logs_on_app_start
from outward_app.paths import asset_path
from outward_app.ui.main_window import MainWindow
from outward_app.ui.themes import sync_fluent_theme, theme_manager
from outward_app.ui.widgets import install_pointer_cursors


SINGLE_INSTANCE_SERVER_NAME = "outward-app-single-instance"
SINGLE_INSTANCE_TIMEOUT_MS = 500


def instance_server_name() -> str:
    identity = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    return SINGLE_INSTANCE_SERVER_NAME + "-" + hashlib.sha256(identity.casefold().encode("utf-8")).hexdigest()[:16]


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
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
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


def apply_fluent_theme(name: str = "dark") -> None:
    sync_fluent_theme(name)


def run() -> int:
    app = QApplication(sys.argv)
    install_pointer_cursors(app)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    server_name = instance_server_name()
    if notify_existing_instance(server_name):
        return 0
    single_instance_server = SingleInstanceServer(server_name, parent=app)
    if not single_instance_server.is_listening:
        return 1
    theme_manager().apply("dark")

    icon = QIcon(str(asset_path("outward.ico")))
    if not icon.isNull():
        app.setWindowIcon(icon)

    rotate_logs_on_app_start()
    try:
        window = MainWindow(launched_on_startup="--autostart" in sys.argv)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        from outward_app.core.connections import sanitize_connection_error
        QMessageBox.critical(None, APP_NAME, tr('Не удалось прочитать данные приложения. Исходные файлы сохранены.\n\n') +
                             sanitize_connection_error(str(exc)))
        return 1
    if single_instance_server.is_listening:
        single_instance_server.activation_requested.connect(window.restore_from_tray)
    if not icon.isNull():
        window.setWindowIcon(icon)
    window.show()
    return app.exec()
