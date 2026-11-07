"""Native Qt Graphite checks with in-memory profiles; never uses real app data."""
import argparse
import os
from pathlib import Path
import sys
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu
from test_ui import UiTests, ProfileDialog, LaunchSitesDialog, ConnectionDialog
from outward_app.ui.themes import theme_manager
from outward_app.ui.window_chrome import DEFAULT_WINDOW_SIZE, MINIMUM_WINDOW_SIZE
from outward_app.paths import asset_path


def capture(output: Path, screenshots: bool):
    UiTests.setUpClass()
    case = UiTests("test_settings_route_keeps_connection_cards_and_unsaved_fields")
    window = case.window()
    window.setWindowIcon(QIcon(str(asset_path("outward.ico"))))
    window.store.save_theme = Mock()
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, not screenshots)
    try:
        profile = window.profiles[0]
        profile.name, profile.country_code = "Germany", "DE"
        window._load_profiles()
        for view in window.controller.views():
            window.dashboard.update_view(view)
        for name in ("dark", "light"):
            window._remember_theme(name)
            window.resize(*DEFAULT_WINDOW_SIZE)
            window._set_route("home")
            case.settle(window)
            if screenshots:
                output.mkdir(parents=True, exist_ok=True)
                assert window.grab().save(str(output / f"graphite-{name}-home.png"))
            window._set_route("settings")
            window._set_tab_index(1)
            case.settle(window)
            if screenshots:
                assert window.grab().save(str(output / f"graphite-{name}-settings.png"))
            window.launch_on_startup_check.setChecked(True)
            for size in (MINIMUM_WINDOW_SIZE, DEFAULT_WINDOW_SIZE, (1100, 782)):
                window.resize(*size)
                for tab in (0, 1, 2):
                    window._set_tab_index(tab)
                    case.settle(window)
                    assert window.content_scroll.verticalScrollBar().maximum() == 0
                    assert window.legacy_scroll.horizontalScrollBar().maximum() == 0
                    footer = window.footer_label.mapTo(window.content_scroll.viewport(), window.footer_label.rect().bottomRight())
                    assert footer.y() <= window.content_scroll.viewport().height()
            window.launch_on_startup_check.setChecked(False)
            window.resize(*DEFAULT_WINDOW_SIZE)
            for dialog in (
                ProfileDialog(window),
                LaunchSitesDialog(window, ["example.com"]),
                ConnectionDialog(window, "Добавить окно", window.profiles, profile.id, window.settings,
                                 switch_factory=window._make_switch),
            ):
                dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, not screenshots)
                case.settle(dialog)
                if screenshots:
                    assert dialog.grab().save(str(output / f"graphite-{name}-{type(dialog).__name__}.png"))
                case.dispose(dialog)
            menu = QMenu(window)
            menu.addAction("Профиль и порты…")
            menu.addAction("Подробности / журнал")
            menu.addSeparator()
            menu.addAction("Удалить окно").setEnabled(False)
            menu.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, not screenshots)
            menu.popup(window.mapToGlobal(window.rect().center()))
            case.app.processEvents()
            if screenshots:
                assert menu.grab().save(str(output / f"graphite-{name}-menu.png"))
            menu.hide()
            menu.deleteLater()
        print("Graphite native check OK; scale:", window.devicePixelRatioF(),
              "; Qt platform:", case.app.platformName(), "; captures:", screenshots)
    finally:
        case.doCleanups()
        theme_manager().apply("dark")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "docs/validation/assets")
    parser.add_argument("--screenshots", action="store_true")
    args = parser.parse_args()
    capture(args.output, args.screenshots)

