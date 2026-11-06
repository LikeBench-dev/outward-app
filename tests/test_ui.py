import os
import subprocess
import sys
from pathlib import Path
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
from PySide6.QtGui import QAccessible, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QApplication, QDialog, QMenu, QPushButton

from outward_app.core.models import AppSettings, ConnectionProfile, RuntimeState
from outward_app.ui import main_window as ui
from outward_app.ui.app import apply_fluent_theme
from outward_app.ui.dialogs import LaunchSitesDialog, ProfileDialog
from outward_app.ui.styles import APP_STYLE
from outward_app.ui.widgets import install_pointer_cursors


SHADOWSOCKS_LINK = 'ss://YWVzLTI1Ni1nY206c2VjcmV0@example.net:8388#Test'


class MemoryStore:
    def __init__(self):
        self.profiles = [ConnectionProfile.create(name='Рабочий профиль', link=SHADOWSOCKS_LINK)]

    def load_settings(self):
        return AppSettings()

    def load_profiles(self):
        return self.profiles

    def save_settings(self, settings):
        pass


class IdleManager:
    running = False

    def is_running(self):
        return self.running

    def stop(self):
        self.running = False


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        install_pointer_cursors(cls.app)
        # Qt's offscreen plugin needs explicit font loading on Windows.
        for filename in ('segoeui.ttf', 'segoeuib.ttf', 'consola.ttf'):
            font = Path('C:/Windows/Fonts') / filename
            if cls.app.platformName() == 'offscreen' and font.exists():
                QFontDatabase.addApplicationFont(str(font))
        apply_fluent_theme()
        cls.app.setStyleSheet(APP_STYLE)

    def track(self, widget):
        self.addCleanup(self.dispose, widget)
        return widget

    def dispose(self, widget):
        for timer in widget.findChildren(QTimer):
            timer.stop()
        widget.hide()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def window(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        for target, replacement in (
            ('JsonStore', MemoryStore), ('SingBoxManager', IdleManager), ('UpdateManager', Mock()),
        ):
            stack.enter_context(patch.object(ui, target, replacement))
        for method in ('_create_tray_icon', 'refresh_log', '_apply_windows_dark_title_bar',
                       '_start_ping_updates', '_sync_windows_startup'):
            stack.enter_context(patch.object(ui.MainWindow, method, lambda self: None))
        with patch.object(ui.QTimer, 'singleShot'):
            window = self.track(ui.MainWindow())
        return window

    def settle(self, widget):
        widget.show()
        for _ in range(4):
            self.app.processEvents()

    def assert_within(self, child, ancestor):
        position = child.mapTo(ancestor, child.rect().topLeft())
        self.assertGreaterEqual(position.x(), 0)
        self.assertLessEqual(position.x() + child.width(), ancestor.width())

    def test_small_window_controls_and_cards_fit_after_resize_and_tab_changes(self):
        window = self.window()
        for width, height in ((900, 560), (1100, 750), (900, 560)):
            window.resize(width, height)
            for tab in (1, 0, 2, 1):
                with self.subTest(size=(width, height), tab=tab):
                    window._set_tab_index(tab)
                    self.settle(window)
                    viewport = window.content_scroll.viewport()
                    self.assertLessEqual(window.content_scroll.widget().width(), viewport.width())
                    self.assert_within(window.connect_button, viewport)
                    self.assertGreater(window.connect_button.height(), 20)
                    if tab == 1:
                        for card in (window.general_settings_card, window.proxy_settings_card):
                            self.assert_within(card, viewport)
                        first = window.general_settings_card.geometry()
                        second = window.proxy_settings_card.geometry()
                        if width == 900:
                            self.assertGreater(second.top(), first.bottom())
                        else:
                            self.assertGreater(second.left(), first.right())
                        save = next(button for button in window.tabs.currentWidget().findChildren(QPushButton)
                                    if button.text() == 'Сохранить настройки')
                        window.content_scroll.ensureWidgetVisible(save)
                        self.settle(window)
                        position = save.mapTo(viewport, save.rect().topLeft())
                        self.assertGreaterEqual(position.y(), 0)
                        self.assertLessEqual(position.y() + save.height(), viewport.height())

    def test_selected_protocol_is_accurate_before_connection(self):
        window = self.window()
        self.assertEqual(window.protocol_label.text(), 'Shadowsocks')
        self.assertEqual(window.status_profile_value.text(), window.profiles[0].name)
        window.store.profiles.append(ConnectionProfile.create(name='Другой', link='vless://invalid'))
        window._load_profiles()
        window.profile_list.setCurrentRow(1)
        self.assertEqual(window.protocol_label.text(), 'VLESS')

    def test_active_profile_metadata_survives_selection_changes(self):
        window = self.window()
        window.store.profiles.append(ConnectionProfile.create(name='Другой', link='vless://invalid'))
        window._load_profiles()
        profile = window.profiles[0]
        window.manager.running = True
        state = RuntimeState(profile_id=profile.id, profile_name=profile.name,
                             http_port=18080, socks_port=18081,
                             http_proxy_url='http://127.0.0.1:18080', socks_proxy_url='socks5://127.0.0.1:18081',
                             protocol='shadowsocks', protocol_label='Shadowsocks')
        window._on_connected(state)
        window.profile_list.setCurrentRow(1)
        self.assertEqual(window.status_profile_value.text(), profile.name)
        self.assertEqual(window.protocol_label.text(), 'Shadowsocks')
        self.assertEqual(window.http_port_label.text(), '18080')
        self.assertIn('Подключено', window.status_title_label.text())
        self.assertTrue(window.status_caption_label.isHidden())

    def test_progress_and_safe_error_details_are_visible(self):
        window = self.window()
        self.settle(window)
        window._set_progress_message('Проверяем профиль подключения…')
        self.assertTrue(window.status_caption_label.isVisible())
        self.assertIn('Проверяем', window.status_caption_label.text())
        with patch.object(ui.QMessageBox, 'exec', return_value=0), patch.object(ui, 'append_log_entry') as log:
            window._on_connect_failed('Bad password: "password": "private-test-value" ss://secret@example.org')
        boxes = window.findChildren(ui.QMessageBox)
        details = boxes[-1].detailedText()
        self.assertNotIn('private-test-value', details)
        self.assertNotIn('ss://secret', details)
        self.assertIn('***', details)
        self.assertIn('Проверьте', boxes[-1].informativeText())
        self.assertIn('Не удалось', window.status_title_label.text())
        self.assertNotIn('private-test-value', log.call_args.args[0])

    def test_switch_supports_tab_space_native_accessibility_and_disabled_state(self):
        window = self.window()
        self.settle(window)
        switch = window.auto_open_check
        window.browser_combo.setFocus()
        QTest.keyClick(window.browser_combo, Qt.Key.Key_Tab)
        self.assertTrue(switch.hasFocus())
        self.assertTrue(switch.accessibleName())
        accessible = QAccessible.queryAccessibleInterface(switch)
        self.assertEqual(accessible.role(), QAccessible.Role.CheckBox)
        self.assertFalse(switch.isChecked())
        QTest.keyClick(switch, Qt.Key.Key_Space)
        self.assertTrue(switch.isChecked())
        self.assertTrue(accessible.state().checked)
        self.assertTrue(window.settings.auto_open_browser)
        switch.setEnabled(False)
        QTest.keyClick(switch, Qt.Key.Key_Space)
        self.assertTrue(switch.isChecked())

    def test_empty_profile_state_and_visible_row_menu(self):
        window = self.window()
        window.profiles[0].name = 'Очень длинное название профиля ' * 5
        window._load_profiles()
        window.resize(900, 560)
        self.settle(window)
        self.assertLessEqual(window.content_scroll.widget().width(), window.content_scroll.viewport().width())
        row = window.profile_list.itemWidget(window.profile_list.item(0))
        menu_button = row.findChild(QPushButton, 'profileMenuButton')
        self.assertTrue(menu_button.isVisible())
        self.assertTrue(menu_button.accessibleName())
        self.assert_within(menu_button, window.profile_list)
        with patch.object(window, '_profile_menu') as menu:
            menu_button.click()
        menu.assert_called_once()
        window.store.profiles = []
        window._load_profiles()
        self.settle(window)
        self.assertTrue(window.empty_profiles.isVisible())
        self.assertFalse(window.connect_button.isEnabled())
        self.assertEqual(window.protocol_label.text(), '—')

    def test_profile_protocol_detection_and_invalid_input_do_not_keep_stale_data(self):
        dialog = self.track(ProfileDialog())
        dialog.link_edit.setText(SHADOWSOCKS_LINK)
        self.assertTrue(dialog.validate_link(show_success=False))
        self.assertEqual(dialog.protocol_group.checkedButton().text(), 'SHADOWSOCKS')
        dialog.link_edit.setText('incorrect')
        with patch('outward_app.ui.dialogs.QMessageBox.warning') as warning:
            dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
        self.assertIsNone(dialog.parsed)
        self.assertTrue(dialog.summary.text())
        self.assertIn('vless://', dialog.summary.text())
        warning.assert_not_called()
        dialog.link_edit.setText(SHADOWSOCKS_LINK)
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.build_profile().protocol, 'shadowsocks')

    def test_done_commits_current_site_edit(self):
        dialog = self.track(LaunchSitesDialog(sites=['example.com', 'example.net']))
        dialog.site_edit.setText('changed.example.org')
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.build_sites(), ['changed.example.org', 'example.net'])

    def test_changing_site_selection_preserves_edits(self):
        dialog = self.track(LaunchSitesDialog(sites=['example.com', 'example.net']))
        dialog.site_edit.setText('changed.example.org')
        dialog.site_list.setCurrentRow(1)
        self.assertEqual(dialog.build_sites(), ['changed.example.org', 'example.net'])
        self.assertEqual(dialog.site_edit.text(), 'example.net')

    def test_duplicate_or_empty_site_does_not_close_dialog_or_lose_draft(self):
        dialog = self.track(LaunchSitesDialog(sites=['example.com', 'example.net']))
        for text in ('example.net', ''):
            with self.subTest(text=text), patch('outward_app.ui.dialogs.QMessageBox.warning'):
                dialog.site_edit.setText(text)
                dialog.accept()
                self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
                self.assertEqual(dialog.build_sites(), ['example.com', 'example.net'])
                dialog.site_list.setCurrentRow(1)
                self.assertEqual(dialog.site_list.currentRow(), 0)
                self.assertEqual(dialog.site_edit.text(), text)

    def test_adding_and_deleting_site_do_not_rename_other_entries(self):
        dialog = self.track(LaunchSitesDialog(sites=['example.com', 'example.net']))
        dialog.site_edit.setText('added.example.org')
        dialog.add_site()
        self.assertEqual(dialog.build_sites(), ['example.com', 'example.net', 'added.example.org'])
        dialog.site_edit.setText('unfinished.example.org')
        dialog.delete_site()
        self.assertEqual(dialog.build_sites(), ['example.com', 'example.net'])
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_default_window_has_no_outer_scroll_on_any_tab(self):
        window = self.window()
        window.resize(1100, 750)
        for tab in (1, 0, 2, 1):
            with self.subTest(tab=tab):
                window._set_tab_index(tab)
                self.settle(window)
                self.assertEqual(window.content_scroll.verticalScrollBar().maximum(), 0)
                viewport = window.content_scroll.viewport()
                footer = window.footer_label.mapTo(viewport, window.footer_label.rect().bottomRight())
                self.assertLessEqual(footer.y(), viewport.height())

    @unittest.skipUnless(sys.platform == 'win32', 'Native Windows Qt regression')
    def test_default_window_fits_native_windows_layout(self):
        script = '''
import sys
sys.path.insert(0, 'tests')
from test_ui import UiTests
from PySide6.QtCore import Qt
UiTests.setUpClass()
case = UiTests('test_default_window_has_no_outer_scroll_on_any_tab')
window = case.window()
window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
window.resize(1100, 750)
for tab in (1, 0, 2, 1):
    window._set_tab_index(tab)
    case.settle(window)
    case.assertEqual(window.size().toTuple(), (1100, 750))
    case.assertEqual(window.content_scroll.verticalScrollBar().maximum(), 0, f'tab {tab}')
    viewport = window.content_scroll.viewport()
    bottom = window.footer_label.mapTo(viewport, window.footer_label.rect().bottomRight())
    case.assertLessEqual(bottom.y(), viewport.height())
case.doCleanups()
'''
        environment = os.environ.copy()
        environment['QT_QPA_PLATFORM'] = 'windows'
        result = subprocess.run([sys.executable, '-X', 'utf8', '-c', script],
                                cwd=Path(__file__).resolve().parent.parent, env=environment,
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_protocol_list_shows_availability_and_detects_the_pasted_link(self):
        dialog = self.track(ProfileDialog())
        self.settle(dialog)
        self.assertEqual(set(dialog.protocol_buttons), {'vless', 'shadowsocks', 'wireguard', 'trojan', 'vmess'})
        for protocol, button in dialog.protocol_buttons.items():
            self.assertTrue(button.isVisible())
            self.assertEqual(button.isEnabled(), protocol in ('vless', 'shadowsocks'))
            self.assertTrue(button.toolTip())
            self.assertLessEqual(button.mapTo(dialog, button.rect().bottomRight()).x(), dialog.width() - 24)
        dialog.link_edit.setText(SHADOWSOCKS_LINK)
        dialog.validate_link(show_success=False)
        self.assertTrue(dialog.protocol_buttons['shadowsocks'].isChecked())

    def test_pointer_cursor_for_buttons_profile_items_and_menu_actions(self):
        window = self.window()
        self.settle(window)
        for button in window.findChildren(QAbstractButton):
            if button.isVisible() and button.isEnabled():
                self.assertEqual(button.cursor().shape(), Qt.CursorShape.PointingHandCursor)
        first = window.profile_list.visualItemRect(window.profile_list.item(0)).center()
        QTest.mouseMove(window.profile_list.viewport(), first)
        self.assertEqual(window.profile_list.viewport().cursor().shape(), Qt.CursorShape.PointingHandCursor)
        window.auto_open_check.setEnabled(False)
        self.assertEqual(window.auto_open_check.cursor().shape(), Qt.CursorShape.ArrowCursor)
        menu = self.track(QMenu())
        enabled = menu.addAction('Изменить')
        disabled = menu.addAction('Недоступно')
        disabled.setEnabled(False)
        self.settle(menu)
        QTest.mouseMove(menu, menu.actionGeometry(enabled).center())
        self.assertEqual(menu.cursor().shape(), Qt.CursorShape.PointingHandCursor)
        QTest.mouseMove(menu, menu.actionGeometry(disabled).center())
        self.assertEqual(menu.cursor().shape(), Qt.CursorShape.ArrowCursor)


if __name__ == '__main__':
    unittest.main()
