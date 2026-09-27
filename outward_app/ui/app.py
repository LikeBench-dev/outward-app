from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from outward_app.app_info import APP_NAME
from outward_app.core.singbox import rotate_logs_on_app_start
from outward_app.paths import asset_path
from outward_app.ui.main_window import MainWindow
from outward_app.ui.styles import APP_STYLE


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
    apply_fluent_theme()
    app.setStyleSheet(APP_STYLE)

    icon = QIcon(str(asset_path("outward.ico")))
    if not icon.isNull():
        app.setWindowIcon(icon)

    rotate_logs_on_app_start()
    window = MainWindow()
    if not icon.isNull():
        window.setWindowIcon(icon)
    window.resize(1100, 750)
    window.show()
    return app.exec()


