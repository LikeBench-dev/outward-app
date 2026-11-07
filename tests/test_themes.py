"""Theme persistence and live switching use synthetic data and no connections."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox

from outward_app.core.models import AppSettings, RuntimeState
from outward_app.core.storage import JsonStore
from outward_app.ui.themes import current_theme, theme_colors, theme_manager
import test_ui as fixture


class ThemeStorageTests(unittest.TestCase):
    def test_missing_invalid_and_saved_themes_round_trip(self):
        for value in (None, "", "system", 123, [], {}):
            with self.subTest(value=value):
                self.assertEqual(AppSettings.from_dict({"theme": value}).theme, "dark")
        for name in ("light", "dark"):
            self.assertEqual(AppSettings.from_dict(AppSettings(theme=name).to_dict()).theme, name)
        self.assertEqual(AppSettings.from_dict({}).theme, "dark")

    def test_theme_write_preserves_disk_settings_and_unknown_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            store = JsonStore(path / "profiles.json", path / "settings.json")
            original = {"custom_dns": "9.9.9.9", "http_port": 18080, "future_setting": {"keep": True}}
            store.settings_file.write_text(json.dumps(original), encoding="utf-8")
            store.save_theme("light")
            self.assertEqual(json.loads(store.settings_file.read_text(encoding="utf-8")),
                             {**original, "theme": "light"})
            self.assertEqual(store.load_settings().theme, "light")
            store.save_settings(store.load_settings())
            self.assertEqual(store.load_settings().theme, "light")


class ThemeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.UiTests.setUpClass()
        cls.app = fixture.UiTests.app

    def setUp(self):
        theme_manager().apply("dark")
        self.case = fixture.UiTests("test_settings_route_keeps_connection_cards_and_unsaved_fields")
        self.addCleanup(theme_manager().apply, "dark")
        self.addCleanup(self.case.doCleanups)

    def window(self):
        window = self.case.window()
        window.store.save_theme = Mock()
        self.case.settle(window)
        return window

    def choose(self, window, name):
        window._set_route("settings")
        window._set_tab_index(1)
        self.case.settle(window)
        button = window.theme_selector.buttons[name]
        button.setFocus()
        QTest.keyClick(button, Qt.Key.Key_Space)
        self.app.processEvents()

    def test_switch_preserves_sessions_invalid_drafts_and_widget_identity(self):
        window = self.window()
        cid = window.controller.collection.windows[0].id
        card = window.dashboard.cards[cid]
        view = window.controller.entries[cid].view
        view.status = "connected"
        view.runtime = RuntimeState(window.profiles[0].id, "Germany", 18080, 18081, "", "")
        card.render(view)
        window.dns_edit.setText("9.9.9.9")
        window.socks_port_spin.setValue(window.http_port_spin.value())  # Deliberately invalid draft.
        with patch.object(window.controller, "configure") as configure, \
                patch.object(window, "_sync_windows_startup") as startup, \
                patch.object(window.store, "save_settings") as save:
            for name in ("light", "dark", "light"):
                self.choose(window, name)
                self.assertEqual(current_theme(), name)
                self.assertEqual(window.settings.theme, name)
                self.assertIs(window.dashboard.cards[cid], card)
                self.assertEqual(window._view(cid).status, "connected")
                self.assertEqual(window.dns_edit.text(), "9.9.9.9")
                self.assertEqual(window.socks_port_spin.value(), window.http_port_spin.value())
                self.assertTrue(card.open_browser.isEnabled())
            configure.assert_not_called()
            startup.assert_not_called()
            save.assert_not_called()
        self.assertEqual(window.store.save_theme.call_count, 3)
        self.assertEqual(window._route, "settings")
        self.assertEqual(window.tabs.currentIndex(), 1)

    def test_failed_save_restores_selector_and_keeps_previous_appearance(self):
        window = self.window()
        window.store.save_theme.side_effect = OSError("Disk unavailable")
        before = self.app.styleSheet()
        with patch.object(fixture.ui.QMessageBox, "warning") as warning:
            self.choose(window, "light")
        warning.assert_called_once()
        self.assertEqual(current_theme(), "dark")
        self.assertEqual(window.settings.theme, "dark")
        self.assertTrue(window.theme_selector.buttons["dark"].isChecked())
        self.assertEqual(self.app.styleSheet(), before)

    def test_saved_theme_applies_before_show_and_survives_general_save(self):
        with patch.object(fixture.MemoryStore, "load_settings", return_value=AppSettings(theme="light")):
            window = self.window()
        self.assertEqual(current_theme(), "light")
        self.assertTrue(window.theme_selector.buttons["light"].isChecked())
        with patch.object(window.store, "save_settings") as save:
            window.save_settings()
        self.assertEqual(save.call_args.args[0].theme, "light")
        self.assertEqual(window.settings.theme, "light")

    def test_existing_log_rethemes_without_losing_selection_or_scroll(self):
        window = self.window()
        window._set_route("settings")
        window._set_tab_index(0)
        self.case.settle(window)
        source = "\n".join(f"12:00:00 INFO line {number} <escaped>" for number in range(150))
        window._render_log_text(source)
        self.app.processEvents()
        cursor = window.log_view.textCursor()
        cursor.setPosition(10)
        cursor.setPosition(30, QTextCursor.MoveMode.KeepAnchor)
        window.log_view.setTextCursor(cursor)
        window.log_view.verticalScrollBar().setValue(50)
        selection = window.log_view.textCursor().selectedText()
        value = window.log_view.verticalScrollBar().value()
        window._remember_theme("light")
        self.app.processEvents()
        self.assertEqual(window.log_view.textCursor().selectedText(), selection)
        self.assertEqual(window.log_view.verticalScrollBar().value(), value)
        self.assertIn(theme_colors()["text"].lower(), window.log_view.toHtml().lower())
        self.assertIn("&lt;escaped&gt;", window._format_log_html(source))
        self.assertEqual(window._last_log_text, source)

    def test_new_widgets_and_title_bar_use_current_theme_with_plain_qt_fallback(self):
        with patch.dict("sys.modules", {"qfluentwidgets": None}), \
                patch.object(fixture.ui, "FluentComboBox", None):
            window = self.window()
            self.choose(window, "light")
            self.assertIsInstance(window.browser_combo, QComboBox)
            saved = window.controller.add_window(window.profiles[0].id)
            card = window.dashboard.insert(window._view(saved.id))
            dialog = self.case.track(fixture.ProfileDialog(window))
            self.case.settle(dialog)
            self.assertEqual(dialog.palette().color(QPalette.ColorRole.WindowText).name(), "#202020")
            self.assertEqual(card.palette().color(QPalette.ColorRole.WindowText).name(), "#202020")
            capture = window.title_bar.grab().toImage()
            self.assertEqual(capture.pixelColor(100, 4).name(),
                             self.app.palette().color(QPalette.ColorRole.Button).name())

    def test_both_themes_keep_controls_reachable_at_small_and_large_sizes(self):
        window = self.window()
        for name in ("light", "dark"):
            self.choose(window, name)
            window.launch_on_startup_check.setChecked(True)
            for size in ((900, 592), (903, 682), (1100, 782)):
                with self.subTest(theme=name, size=size):
                    window.resize(*size)
                    self.case.settle(window)
                    self.assertEqual(window.content_scroll.verticalScrollBar().maximum(), 0)
                    for button in window.theme_selector.buttons.values():
                        self.assertGreater(button.width(), 60)
                        self.assertLessEqual(button.geometry().right(), window.theme_selector.width())
                    self.assertEqual(window.legacy_scroll.horizontalScrollBar().maximum(), 0)


if __name__ == "__main__":
    unittest.main()

