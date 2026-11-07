import os
import subprocess
import sys
import threading
from pathlib import Path
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QEvent, QThread, Qt, QTimer
from PySide6.QtGui import QAccessible, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QApplication, QDialog, QMenu, QPushButton

from outward_app.core.models import AppSettings, ConnectionCollection, ConnectionProfile, RuntimeState
from outward_app.core.countries import country_options
from outward_app.ui import main_window as ui
from outward_app.ui.app import apply_fluent_theme
from outward_app.ui.dialogs import LaunchSitesDialog, ProfileDialog
from outward_app.ui.country_flags import CountryFlagBadge, country_icon
from outward_app.core.sessions import SessionView
from outward_app.ui.connection_dialog import ConnectionDialog
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

    def load_connections(self, settings, profile_id):
        self.collection = ConnectionCollection()
        self.collection.system.profile_id = profile_id
        self.collection.add_window(profile_id, settings)
        return self.collection

    def save_connections(self, collection):
        self.collection = collection

    def mark_used(self, profile_id):
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
        if hasattr(widget, 'controller'):
            widget.controller.close()
        for timer in widget.findChildren(QTimer):
            timer.stop()
        widget.hide()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def window(self, *, launched_on_startup=False):
        stack = ExitStack()
        self.addCleanup(stack.close)
        for target, replacement in (
            ('JsonStore', MemoryStore), ('SingBoxManager', IdleManager), ('UpdateManager', Mock()),
        ):
            stack.enter_context(patch.object(ui, target, replacement))
        for method in ('_create_tray_icon', 'refresh_log', '_apply_windows_dark_title_bar',
                       '_sync_windows_startup'):
            stack.enter_context(patch.object(ui.MainWindow, method, lambda self: None))
        with patch.object(ui.QTimer, 'singleShot'):
            window = self.track(ui.MainWindow(launched_on_startup=launched_on_startup))
        return window

    def settle(self, widget):
        widget.show()
        for _ in range(4):
            self.app.processEvents()

    def test_autostart_reveals_independent_multi_connection_choices(self):
        sync_windows_startup = ui.MainWindow._sync_windows_startup
        window = self.window()
        window._set_route('settings')
        window._set_tab_index(1)
        self.settle(window)
        self.assertTrue(window.auto_connect_settings.isHidden())
        with patch.object(window.store, 'save_settings') as save:
            window.launch_on_startup_check.setFocus()
            QTest.keyClick(window.launch_on_startup_check, Qt.Key.Key_Space)
            self.assertTrue(window.settings.launch_on_startup)
            self.assertTrue(window.auto_connect_settings.isVisible())
            save.assert_called_once_with(window.settings)
        second = window.controller.add_window(window.profiles[0].id)
        self.assertEqual(window.auto_connect_list.count(), 3)
        for row in (0, 2):
            window.auto_connect_list.setCurrentRow(row)
            window.auto_connect_list.setFocus()
            QTest.keyClick(window.auto_connect_list, Qt.Key.Key_Space)
        self.assertTrue(window._view('system').connection.auto_connect)
        self.assertTrue(window._view(second.id).connection.auto_connect)
        first = window.controller.collection.windows[0]
        self.assertFalse(window._view(first.id).connection.auto_connect)
        window.launch_on_startup_check.setChecked(False)
        self.assertTrue(window.auto_connect_settings.isHidden())
        self.assertTrue(window._view(second.id).connection.auto_connect)
        window.launch_on_startup_check.setChecked(True)
        self.assertEqual(window.auto_connect_list.item(2).checkState(), Qt.CheckState.Checked)
        window.save_settings()
        self.assertTrue(window.settings.launch_on_startup)
        with patch.object(ui, 'set_launch_on_startup') as register:
            sync_windows_startup(window)
            register.assert_called_once_with(True)
        window.launch_on_startup_check.setChecked(False)
        with patch.object(ui, 'set_launch_on_startup') as register:
            sync_windows_startup(window)
            register.assert_called_once_with(False)

    def test_autoconnect_only_runs_selected_connections_after_windows_launch(self):
        window = self.window(launched_on_startup=True)
        second = window.controller.add_window(window.profiles[0].id)
        window.controller.configure('system', auto_connect=True)
        window.controller.configure(second.id, auto_connect=True)
        with patch.object(window, 'start_connection') as start:
            window._connect_on_startup()
            start.assert_not_called()
            window.settings.launch_on_startup = True
            window._launched_on_startup = False
            window._connect_on_startup()
            start.assert_not_called()
            window._launched_on_startup = True
            window._connect_on_startup()
            self.assertEqual([call.args[0] for call in start.call_args_list], ['system', second.id])
            self.assertTrue(all(call.kwargs == {'automatic': True} for call in start.call_args_list))
            window._connect_on_startup()
            self.assertEqual(start.call_count, 2)

    def test_launch_without_selection_and_unassigned_profiles_do_not_connect(self):
        window = self.window(launched_on_startup=True)
        window.settings.launch_on_startup = True
        with patch.object(window, 'start_connection') as start:
            window._connect_on_startup()
            start.assert_not_called()
            window.controller.configure('system', profile_id='', auto_connect=True)
            self.assertFalse(window.auto_connect_list.item(0).flags() & Qt.ItemFlag.ItemIsEnabled)
            window._launched_on_startup = True
            window._connect_on_startup()
            start.assert_not_called()

    def test_autoconnect_choices_refresh_and_failed_saves_restore_controls(self):
        window = self.window()
        window.launch_on_startup_check.setChecked(True)
        first = window.controller.collection.windows[0]
        with patch.object(window.controller, 'configure', side_effect=OSError('Save failed')):
            window.auto_connect_list.item(1).setCheckState(Qt.CheckState.Checked)
        self.assertFalse(window._view(first.id).connection.auto_connect)
        self.assertEqual(window.auto_connect_list.item(1).checkState(), Qt.CheckState.Unchecked)
        with patch.object(window.store, 'save_settings', side_effect=OSError('Save failed')), \
                patch.object(ui.QMessageBox, 'warning'):
            window.launch_on_startup_check.setChecked(False)
        self.assertTrue(window.settings.launch_on_startup)
        self.assertTrue(window.launch_on_startup_check.isChecked())
        self.assertFalse(window.auto_connect_settings.isHidden())
        window.profiles[0].name = 'Длинное имя профиля ' * 12
        window._sync_connections_profiles()
        self.assertIn(window.profiles[0].name, window.auto_connect_list.item(1).toolTip())
        window.controller.remove(first.id)
        window._set_route('settings')
        self.assertEqual(window.auto_connect_list.count(), 1)

    def test_autoconnect_list_stays_bounded_in_compact_settings(self):
        window = self.window()
        for _ in range(10):
            window.controller.add_window(window.profiles[0].id)
        window.profiles[0].name = 'Очень длинное название профиля ' * 8
        window._sync_connections_profiles()
        window.launch_on_startup_check.setChecked(True)
        window._set_route('settings')
        window._set_tab_index(1)
        for size in ((903, 650), (900, 560), (1400, 850)):
            window.resize(*size)
            self.settle(window)
            self.assertEqual(window.content_scroll.horizontalScrollBar().maximum(), 0)
            self.assertEqual(window.content_scroll.verticalScrollBar().maximum(), 0)
            self.assertLessEqual(window.auto_connect_list.height(), 120)
            self.assertGreater(window.auto_connect_list.verticalScrollBar().maximum(), 0)
            self.assertLessEqual(window.auto_connect_list.width(), window.general_settings_card.width() - 32)

    def test_background_results_stay_on_gui_thread_and_allow_retry(self):
        window = self.window()
        release = threading.Event()
        started = threading.Event()
        self.addCleanup(release.set)
        calls, results, heartbeats = [], [], []
        gui_thread = threading.get_ident()

        def work():
            calls.append(threading.get_ident())
            started.set()
            if not release.wait(3):
                raise TimeoutError('Test worker was not released')
            return '07:54:11 INFO журнал обновлён'

        def received(value, error):
            results.append((threading.get_ident(), value, error))
            window._render_log_text(value or error)

        window._background('system-log', work, received)
        self.assertTrue(started.wait(1))
        window._background('system-log', lambda: self.fail('Duplicate job'), received)
        QTimer.singleShot(0, lambda: heartbeats.append(True))
        self.app.processEvents()
        self.assertTrue(heartbeats)
        self.assertEqual(len(calls), 1)
        self.assertNotEqual(calls[0], gui_thread)
        self.assertFalse(results)
        release.set()
        for _ in range(200):
            QTest.qWait(5)
            if results:
                break
        self.assertEqual(results, [(gui_thread, '07:54:11 INFO журнал обновлён', '')])
        self.assertIn('журнал обновлён', window.log_view.toPlainText())

        def fail():
            raise OSError('ss://secret@example.net:8388')

        window._background('system-log', fail, received)
        for _ in range(200):
            QTest.qWait(5)
            if len(results) == 2:
                break
        self.assertEqual(len(results), 2)
        self.assertEqual(results[-1][0], gui_thread)
        self.assertIsNone(results[-1][1])
        self.assertNotIn('secret', results[-1][2])
        self.assertFalse(window._jobs)
        window._background_pool.shutdown(wait=True)

    def test_shutdown_waits_for_other_background_jobs(self):
        window = self.window()
        release = threading.Event()
        self.addCleanup(release.set)
        completed = []
        window._background('pending-log', lambda: release.wait(3),
                           lambda value, error: completed.append('log'))
        window._shutdown_connections(lambda: completed.append('closed'))
        for _ in range(200):
            QTest.qWait(5)
            if window._close_ready:
                break
        self.assertTrue(window._close_ready)
        self.assertNotIn('closed', completed)
        release.set()
        for _ in range(200):
            QTest.qWait(5)
            if 'closed' in completed:
                break
        self.assertEqual(completed, ['log', 'closed'])
        self.assertFalse(window._jobs)

    @unittest.skipUnless(sys.platform == 'win32', 'Native Windows Qt regression')
    def test_tray_exit_terminates_event_loop_after_hidden_window_cleanup(self):
        # Exercise Exit after the close button has hidden the window in the tray.
        # Isolate the real event loop so a surviving process fails by timeout.
        script = '''
import sys, threading
sys.path.insert(0, 'tests')
from unittest.mock import Mock
from test_ui import UiTests
from PySide6.QtCore import QTimer, Qt
UiTests.setUpClass()
case = UiTests('test_shutdown_waits_for_other_background_jobs')
window = case.window()
window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
window.tray_icon = Mock()
window.settings.minimize_to_tray = True
window.minimize_to_tray_check.setChecked(True)
window.show()
release, started = threading.Event(), threading.Event()
completed = []
def work():
    started.set()
    release.wait(5)
window._background('pending-log', work, lambda value, error: completed.append('log'))
assert started.wait(1)
def exit_from_tray():
    window.close()
    assert not window.isVisible()
    assert not window._closing
    window._quit_from_tray()
def release_work():
    assert window._closing
    assert not completed
    release.set()
QTimer.singleShot(0, exit_from_tray)
QTimer.singleShot(150, release_work)
QTimer.singleShot(3000, lambda: case.app.exit(92))
try:
    result = case.app.exec()
    assert result == 0, 'Qt event loop survived tray Exit'
    assert window.controller.closed.is_set()
    assert window._close_ready
    assert not window._jobs
    assert completed == ['log']
    window.tray_icon.hide.assert_called_once()
finally:
    release.set()
    case.doCleanups()
'''
        environment = os.environ.copy()
        environment['QT_QPA_PLATFORM'] = 'windows'
        result = subprocess.run([sys.executable, '-X', 'utf8', '-c', script],
                                cwd=Path(__file__).resolve().parent.parent, env=environment,
                                capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_update_workers_deliver_results_and_finish_on_gui_thread(self):
        window = self.window()
        manager = window.update_manager
        manager.check_for_update = Mock(return_value=ui.UpdateCheckResult('1.0', '1.0', False))
        window.check_for_updates(silent=True)
        self.assertEqual(window.update_check_thread.thread(), window.thread())
        for _ in range(200):
            QTest.qWait(5)
            if window.update_check_thread is None:
                break
        self.assertIsNone(window.update_check_thread)
        self.assertIn('1.0', window.update_status_label.text())
        self.assertTrue(window.update_button.isEnabled())

        release = ui.UpdateRelease('1.1', 'Update', '', '', 'setup.exe')
        path = Path('synthetic-installer.exe')
        def download(release, progress):
            progress(1, 2)
            return path
        manager.download_update = download
        window.download_update(release)
        self.assertEqual(window.update_download_thread.thread(), window.thread())
        for _ in range(200):
            QTest.qWait(5)
            if window.update_download_thread is None:
                break
        self.assertIsNone(window.update_download_thread)
        self.assertEqual(window.downloaded_update_installer, path)
        self.assertFalse(window.update_restart_button.isHidden())
        self.assertTrue(window.update_button.isEnabled())

    @unittest.skipUnless(sys.platform == 'win32', 'Native Windows Qt regression')
    def test_repeated_background_logs_and_update_cleanup_do_not_hang_native_qt(self):
        # Isolate the stress run: a Qt/GIL deadlock must fail by timeout instead
        # of wedging the entire suite. Real IPC/network and user data are mocked.
        script = '''
import sys, threading, time
sys.path.insert(0, 'tests')
from pathlib import Path
from test_ui import UiTests
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
UiTests.setUpClass()
case = UiTests('test_background_results_stay_on_gui_thread_and_allow_retry')
window = case.window()
window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
window._set_route('settings')
window._set_tab_index(0)
case.settle(window)
window._background_timer.setInterval(1)
window._log_connection = 'system'
gui = threading.get_ident()
received = []
def render(text, error):
    assert threading.get_ident() == gui
    assert not error, error
    window._system_log_received(text, error)
    received.append(text)
for index in range(1000):
    text = '\\n'.join(f'07:54:11 INFO строка {index}/{row}' for row in range(30))
    window._background('system-log', lambda text=text: text, render)
    deadline = time.monotonic() + 3
    while window._jobs:
        assert time.monotonic() < deadline, 'Background log result was not delivered'
        QTest.qWait(1)
    if index % 20 == 0:
        from outward_app.ui.main_window import UpdateCheckWorker, UpdateDownloadWorker
        from unittest.mock import Mock
        manager = Mock()
        manager.check_for_update.return_value = None
        manager.download_update.return_value = Path('synthetic-installer.exe')
        workers = [UpdateCheckWorker(manager, window), UpdateDownloadWorker(manager, None, window)]
        for worker in workers:
            assert worker.thread() == window.thread()
            worker.finished.connect(worker.deleteLater)
            worker.start()
        for worker in workers:
            assert worker.wait(2000)
        QTest.qWait(1)
assert len(received) == 1000
assert '999/29' in window.log_view.toPlainText()
window._background_pool.shutdown(wait=True)
case.doCleanups()
print('1000 background log refreshes and 100 update thread cleanups completed')
'''
        environment = os.environ.copy()
        environment['QT_QPA_PLATFORM'] = 'windows'
        result = subprocess.run([sys.executable, '-X', 'utf8', '-c', script],
                                cwd=Path(__file__).resolve().parent.parent, env=environment,
                                capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def assert_within(self, child, ancestor):
        position = child.mapTo(ancestor, child.rect().topLeft())
        self.assertGreaterEqual(position.x(), 0)
        self.assertLessEqual(position.x() + child.width(), ancestor.width())

    def test_small_window_controls_and_cards_fit_after_resize_and_tab_changes(self):
        window = self.window()
        window._set_route('settings')
        for width, height in ((900, 560), (1100, 750), (900, 560)):
            window.resize(width, height)
            for tab in (1, 0, 2, 1):
                with self.subTest(size=(width, height), tab=tab):
                    window._set_tab_index(tab)
                    self.settle(window)
                    viewport = window.content_scroll.viewport()
                    self.assertLessEqual(window.content_scroll.widget().width(), viewport.width())
                    self.assertFalse(window.dashboard.isVisible())
                    if tab == 1:
                        for card in (window.general_settings_card, window.proxy_settings_card):
                            self.assert_within(card, viewport)
                        first = window.general_settings_card.geometry()
                        second = window.proxy_settings_card.geometry()
                        if width == 900:
                            self.assertGreater(second.top(), first.bottom())
                        else:
                            self.assertGreater(second.left(), first.right())

    def test_selected_protocol_is_accurate_before_connection(self):
        window = self.window()
        card = next(iter(window.dashboard.cards.values()))
        self.assertIn('Shadowsocks', card.protocol.text())
        self.assertIn(window.profiles[0].name, window.status_profile_value.text())
        window.store.profiles.append(ConnectionProfile.create(name='Другой', link='vless://invalid'))
        window._load_profiles()
        window.profile_list.setCurrentRow(1)
        # Merely browsing the library must not reassign a saved connection.
        self.assertIn('Shadowsocks', card.protocol.text())

    def test_country_icons_render_for_every_picker_country_and_unknown(self):
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QIcon
        from PySide6.QtSvg import QSvgRenderer
        from outward_app.paths import asset_path

        unknown_image = country_icon('').pixmap(24, 18).toImage()
        for code, _name in country_options():
            with self.subTest(country=code):
                flag = asset_path(f'flags/{code.lower()}.svg')
                if flag.is_file():
                    self.assertTrue(QSvgRenderer(str(flag)).isValid())
                else:
                    # Qt also lists regions without a corresponding flag.
                    self.assertIn(code, {'EA', '150', '419', '001'})
                    self.assertEqual(country_icon(code).pixmap(24, 18).toImage(), unknown_image)
                for scale in (1.0, 1.25, 1.5, 2.0):
                    pixmap = country_icon(code).pixmap(QSize(24, 18), scale)
                    self.assertFalse(pixmap.isNull())
                    self.assertGreater(pixmap.toImage().pixelColor(pixmap.width() // 2, pixmap.height() // 2).alpha(), 0)
                icon = country_icon(code)
                for mode in (QIcon.Mode.Selected, QIcon.Mode.Active):
                    self.assertEqual(icon.pixmap(QSize(24, 18), mode).toImage(),
                                     icon.pixmap(QSize(24, 18)).toImage())
        self.assertFalse(country_icon('').pixmap(24, 18).isNull())
        self.assertEqual(country_icon('invalid').pixmap(24, 18).toImage(),
                         country_icon('').pixmap(24, 18).toImage())
        with patch('outward_app.ui.country_flags.asset_path',
                   side_effect=[Path('missing-flag.svg'), asset_path('flags/unknown.svg')]):
            self.assertEqual(country_icon('DE').pixmap(24, 18).toImage(),
                             unknown_image)

    def test_profile_country_badges_use_saved_and_guessed_countries(self):
        window = self.window()
        for name, saved, expected in (('Germany', 'US', 'US United States'),
                                      ('Germany', '', 'DE Germany'),
                                      ('Рабочий', '', 'Страна не определена')):
            profile = ConnectionProfile.create(name=name, link=SHADOWSOCKS_LINK, country_code=saved)
            row = self.track(window._profile_item_widget(profile))
            badge = row.findChild(CountryFlagBadge)
            self.assertEqual(badge.accessibleName(), expected)
            self.assertEqual(badge.toolTip(), expected)

    def test_country_picker_keeps_country_codes_when_saving_and_editing(self):
        profile = ConnectionProfile.create(name='Germany', link=SHADOWSOCKS_LINK, country_code='US')
        dialog = self.track(ProfileDialog(profile=profile))
        self.assertEqual(dialog.country_combo.currentData(), 'US')
        for index in range(dialog.country_combo.count()):
            self.assertFalse(dialog.country_combo.itemIcon(index).pixmap(24, 18).isNull())
        dialog.country_combo.setFocus()
        QTest.keyClick(dialog.country_combo, Qt.Key.Key_Home)
        self.assertEqual(dialog.country_combo.currentData(), '')
        QTest.keyClick(dialog.country_combo, Qt.Key.Key_Down)
        selected = dialog.country_combo.currentData()
        self.assertTrue(selected)
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.build_profile().country_code, selected)
        reopened = self.track(ProfileDialog(profile=profile))
        self.assertEqual(reopened.country_combo.currentData(), selected)

    def test_active_profile_metadata_survives_selection_changes(self):
        window = self.window()
        window.store.profiles.append(ConnectionProfile.create(name='Другой', link='vless://invalid'))
        window._load_profiles()
        profile = window.profiles[0]
        cid = window.controller.collection.windows[0].id
        state = RuntimeState(profile_id=profile.id, profile_name=profile.name,
                             http_port=18080, socks_port=18081,
                             http_proxy_url='http://127.0.0.1:18080', socks_proxy_url='socks5://127.0.0.1:18081',
                             protocol='shadowsocks', protocol_label='Shadowsocks')
        entry = window.controller.entries[cid]
        entry.view.status, entry.view.runtime = 'connected', state
        window._on_session_changed(entry.view)
        window.profile_list.setCurrentRow(1)
        card = window.dashboard.cards[cid]
        self.assertIn(profile.name, card.profile_button.text())
        self.assertIn('Shadowsocks', card.protocol.text())
        self.assertIn('18080', card.http.text())
        self.assertEqual(window.dashboard.system.title.text(), 'Системное подключение')

    def test_progress_and_safe_error_details_are_visible(self):
        window = self.window()
        self.settle(window)
        cid = window.controller.collection.windows[0].id
        entry = window.controller.entries[cid]
        entry.view.status, entry.view.message = 'preparing', 'Проверяем профиль подключения…'
        window._on_session_changed(entry.view)
        card = window.dashboard.cards[cid]
        self.assertFalse(card.message.isVisible())
        self.assertTrue(card.action_button.busy)
        self.assertTrue(card.action_button.timer.isActive())
        self.assertIn('Отменить', card.action_button.accessibleName())
        entry.view.status = 'error'
        entry.view.message = 'Bad password: "password": "private-test-value" ss://secret@example.org'
        window._on_session_changed(entry.view)
        self.assertFalse(card.message.isVisible())
        self.assertTrue(card.error_indicator.isVisible())
        self.assertNotIn('private-test-value', card.error_indicator.toolTip())
        self.assertNotIn('ss://secret', card.error_indicator.toolTip())
        self.assertIn('***', card.error_indicator.toolTip())
        self.assertEqual(card.title.text(), 'Окно №1')
        self.assertEqual(card.action_button.text(), '')
        self.assertIn('Повторить', card.action_button.accessibleName())
        self.assertFalse(card.action_button.timer.isActive())
        self.assertEqual(window.dashboard.system.title.text(), 'Системное подключение')

    def test_compact_window_flag_power_and_monthly_traffic_preserve_system_controls(self):
        window = self.window()
        self.settle(window)
        profile = window.profiles[0]
        profile.country_code = 'DE'
        cid = window.controller.collection.windows[0].id
        view = window._view(cid)
        card = window.dashboard.cards[cid]
        card.render(view, {profile.id: profile})
        self.assertEqual(card.width(), 260)
        self.assertLess(card.height(), 300)
        self.assertTrue(card.dot.isHidden())
        self.assertFalse(card.logo.colored)
        image = card.logo.pixmap().toImage()
        for y in range(image.height()):
            for x in range(image.width()):
                pixel = image.pixelColor(x, y)
                self.assertEqual(pixel.red(), pixel.green())
                self.assertEqual(pixel.green(), pixel.blue())
        self.assertEqual(card.action_button.text(), '')
        view.status, view.traffic_bytes = 'connected', 12_400_000_000
        view.runtime = RuntimeState(profile.id, profile.name, 18080, 18081, '', '', country_code='DE')
        card.render(view)
        self.assertTrue(card.logo.colored)
        self.assertTrue(card.action_button.connected)
        self.assertIn('12,4 ГБ', card.traffic.text())
        self.assertEqual(card.traffic.geometry().top(), card.protocol.geometry().top())
        self.assertGreater(card.traffic.geometry().top(), card.socks.geometry().top())
        self.assertGreater(card.action_button.geometry().right(), card.menu_button.geometry().right())
        profile.country_code = 'US'
        card.render(view, {profile.id: profile})
        self.assertEqual(card.logo.country_code, 'DE', 'An active session retains its profile flag')
        window.dashboard.system.render(window._view('system'))
        self.assertEqual(window.dashboard.system.action_button.text(), '')
        self.assertEqual(window.dashboard.system.action_button.accessibleName(), 'Подключить')
        self.assertIn('Трафик за текущий месяц:', window.dashboard.system.traffic.accessibleName())

    def test_window_power_button_keeps_keyboard_cancel_and_stop_states(self):
        from outward_app.ui.connection_card import ConnectionCard
        window = self.window()
        for cid in (window.controller.collection.windows[0].id, 'system'):
            view = window._view(cid)
            card = self.track(ConnectionCard(view, window.controller.profiles, ['example.com']))
            self.settle(card)
            actions = []
            card.action.connect(actions.append)
            for state in ('offline', 'preparing', 'connecting', 'reconnecting', 'connected', 'error'):
                view.status = state
                card.render(view)
                card.action_button.setFocus()
                QTest.keyClick(card.action_button, Qt.Key.Key_Space)
                self.assertEqual(actions[-1], view.connection.id)
                self.assertEqual(card.action_button.text(), '')
                self.assertEqual(card.action_button.busy, state in {'preparing', 'connecting', 'reconnecting'})
                self.assertEqual(card.action_button.connected, state == 'connected')
            view.status = 'stopping'
            card.render(view)
            self.assertFalse(card.action_button.isEnabled())
            self.assertTrue(card.action_button.busy)

    def test_three_compact_cards_fit_default_width_and_reflow_in_small_window(self):
        window = self.window()
        for _ in range(5):
            saved = window.controller.add_window(window.profiles[0].id)
            window.dashboard.insert(window._view(saved.id))
        for size, columns in (((1100, 750), 3), ((900, 560), 2), ((1100, 750), 3)):
            window.resize(*size)
            self.settle(window)
            cards = list(window.dashboard.cards.values())
            first_row = [card for card in cards if card.y() == cards[0].y()]
            self.assertEqual(len(first_row), columns)
            self.assertEqual(window.dashboard.scroll.horizontalScrollBar().maximum(), 0)
            for card in cards:
                self.assertLessEqual(card.height() - card.auto_group.geometry().bottom() - 1, 13)
                for control in (card.action_button, card.menu_button, card.protocol, card.traffic, card.open_browser, card.url, card.auto_group):
                    self.assert_within(control, card)
                self.assertGreaterEqual(card.protocol.height(), card.protocol.heightForWidth(card.protocol.width()))

    def test_power_glyph_is_centered_inside_its_frame(self):
        from outward_app.ui.connection_card import PowerButton
        from outward_app.ui.themes import theme_color
        button = self.track(PowerButton())
        button.set_state('offline')
        self.settle(button)
        image = button.grab().toImage()
        pixels = [(x, y) for y in range(image.height()) for x in range(image.width())
                  if image.pixelColor(x, y).name() == theme_color('muted').name()]
        self.assertTrue(pixels)
        for axis, length in ((0, image.width()), (1, image.height())):
            middle = (min(p[axis] for p in pixels) + max(p[axis] for p in pixels)) / 2
            self.assertAlmostEqual(middle, (length - 1) / 2, delta=1)

    def test_traffic_refresh_retains_browser_errors_and_pending_launch(self):
        window = self.window()
        self.settle(window)
        view = window._view(window.controller.collection.windows[0].id)
        view.status = 'connected'
        view.runtime = RuntimeState(window.profiles[0].id, 'Germany', 18080, 18081, '', '')
        card = window.dashboard.cards[view.connection.id]
        card.render(view)
        card.show_error('Chrome или Edge не найдены')
        view.traffic_bytes = 4321
        card.render(view)
        self.assertFalse(card.message.isVisible())
        self.assertTrue(card.error_indicator.isVisible())
        self.assertIn('не найдены', card.error_indicator.toolTip())
        card.clear_error()
        self.assertTrue(card.error_indicator.isHidden())
        self.assertEqual(card.error_indicator.toolTip(), '')
        card.set_browser_pending(True)
        card.render(view)
        self.assertFalse(card.open_browser.isEnabled())
        card.set_browser_pending(False)
        self.assertTrue(card.open_browser.isEnabled())
        card.show_error('Ошибка браузера')
        view.status = 'offline'
        card.render(view)
        self.assertFalse(card.message.isVisible())
        self.assertTrue(card.error_indicator.isHidden())

    def test_window_error_tooltip_keeps_card_compact_and_clears_on_retry(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QHelpEvent
        from PySide6.QtWidgets import QToolTip
        window = self.window()
        self.settle(window)
        view = window._view(window.controller.collection.windows[0].id)
        card = window.dashboard.cards[view.connection.id]
        resting_height = card.height()
        browser_top = card.open_browser.mapTo(card, QPoint()).y()
        view.status = 'error'
        view.message = 'Нет ответа через подключение. Проверьте сервер и DNS.\n' + 'ConnectionResetError, ' * 20 + '<test>'
        window._on_session_changed(view)
        self.settle(window)
        indicator = card.error_indicator
        self.assertTrue(indicator.isVisible())
        self.assertFalse(card.message.isVisible())
        self.assertEqual(card.message.text(), '')
        self.assertEqual(card.height(), resting_height)
        self.assertEqual(card.open_browser.mapTo(card, QPoint()).y(), browser_top)
        self.assertLessEqual(card.title.heightForWidth(card.title.width()), card.title.height())
        self.assert_within(indicator, card)
        self.assertIn('&lt;test&gt;', indicator.toolTip())
        self.assertIn('ConnectionResetError', indicator.accessibleDescription())
        self.app.sendEvent(indicator, QHelpEvent(QEvent.Type.ToolTip, indicator.rect().center(),
                                               indicator.mapToGlobal(indicator.rect().center())))
        self.assertTrue(QToolTip.isVisible())
        self.assertEqual(QToolTip.text(), indicator.toolTip())
        QToolTip.hideText()
        indicator.setFocus(Qt.FocusReason.TabFocusReason)
        self.app.processEvents()
        self.assertTrue(indicator.hasFocus())
        self.assertTrue(QToolTip.isVisible())
        card.action_button.setFocus()
        view.status, view.message = 'connecting', 'Проверяем подключение…'
        window._on_session_changed(view)
        self.assertTrue(indicator.isHidden())
        self.assertEqual(indicator.toolTip(), '')
        self.assertEqual(indicator.accessibleDescription(), '')

    def test_switch_supports_tab_space_native_accessibility_and_disabled_state(self):
        window = self.window()
        window._set_route('settings')
        window._set_tab_index(1)
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
        self.assertIn('Выбрать профиль', window.dashboard.system.profile_button.text())

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

    def test_caption_close_preserves_tray_and_connection_shutdown(self):
        window = self.window()
        self.settle(window)
        window.tray_icon = Mock()
        window.settings.minimize_to_tray = True
        with patch.object(window, 'save_settings') as save, patch.object(window, '_shutdown_connections') as shutdown:
            window.title_bar.close_button.click()
            self.assertFalse(window.isVisible())
            save.assert_called_once()
            shutdown.assert_not_called()
            window.restore_from_tray()
            self.assertTrue(window.isVisible())
            window.settings.minimize_to_tray = False
            window.title_bar.close_button.click()
            shutdown.assert_called_once_with(window.close)
            self.assertTrue(window.force_quit)
            self.assertTrue(window.isVisible())  # Wait for async connection cleanup.

    def test_default_window_has_no_outer_scroll_on_any_tab(self):
        window = self.window()
        self.settle(window)
        self.assertEqual(window.size().toTuple(), ui.DEFAULT_WINDOW_SIZE)
        self.assertEqual(window.centralWidget().height(), 650)
        self.assertEqual(window.content_scroll.verticalScrollBar().maximum(), 0)
        self.assertEqual(window.dashboard.scroll.verticalScrollBar().maximum(), 0)
        window._set_route('settings')
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
from test_ui import UiTests, ui
from PySide6.QtCore import Qt
UiTests.setUpClass()
case = UiTests('test_default_window_has_no_outer_scroll_on_any_tab')
window = case.window()
window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
case.settle(window)
case.assertEqual(window.size().toTuple(), ui.DEFAULT_WINDOW_SIZE)
case.assertEqual(window.centralWidget().height(), 650)
case.assertEqual(window.content_scroll.verticalScrollBar().maximum(), 0)
case.assertEqual(window.dashboard.scroll.verticalScrollBar().maximum(), 0)
window._set_route('settings')
for tab in (1, 0, 2, 1):
    window._set_tab_index(tab)
    case.settle(window)
    case.assertEqual(window.size().toTuple(), ui.DEFAULT_WINDOW_SIZE)
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
                expected = Qt.CursorShape.ArrowCursor if button.property('nativeCaptionButton') else Qt.CursorShape.PointingHandCursor
                self.assertEqual(button.cursor().shape(), expected)
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


    def test_existing_tabs_remain_accessible_by_click(self):
        window = self.window()
        self.settle(window)
        QTest.mouseClick(window.settings_button, Qt.MouseButton.LeftButton)
        for button, index in ((window.settings_tab_button, 1), (window.update_tab_button, 2),
                              (window.log_tab_button, 0)):
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            self.app.processEvents()
            self.assertEqual(window.tabs.currentIndex(), index)

    def test_settings_route_keeps_connection_cards_and_unsaved_fields(self):
        window = self.window()
        self.settle(window)
        first = next(iter(window.dashboard.cards.values()))
        self.assertEqual(window._route, 'home')
        self.assertFalse(window.log_view.isVisible())
        self.assertTrue(first.isVisible())
        self.assertGreater(window.settings_button.mapTo(window, window.settings_button.rect().topLeft()).y(),
                           window.add_button.mapTo(window, window.add_button.rect().bottomLeft()).y())
        QTest.mouseClick(window.settings_button, Qt.MouseButton.LeftButton)
        self.settle(window)
        self.assertEqual(window._route, 'settings')
        self.assertFalse(first.isVisible())
        window.dns_edit.setText('9.9.9.9')
        QTest.mouseClick(window.home_button, Qt.MouseButton.LeftButton)
        self.settle(window)
        self.assertEqual(window._route, 'home')
        self.assertIs(first, next(iter(window.dashboard.cards.values())))
        QTest.mouseClick(window.settings_button, Qt.MouseButton.LeftButton)
        self.assertEqual(window.dns_edit.text(), '9.9.9.9')

    def test_connection_log_opens_settings_and_selects_the_right_session(self):
        window = self.window()
        second = window.controller.add_window(window.profiles[0].id)
        window.show_connection_log(second.id)
        self.settle(window)
        self.assertEqual(window._route, 'settings')
        self.assertEqual(window.tabs.currentIndex(), 0)
        self.assertEqual(window.log_connection_combo.currentData(), second.id)
        window.log_connection_combo.setCurrentIndex(window.log_connection_combo.findData('system'))
        self.assertEqual(window._log_connection, 'system')

    def test_system_card_shows_protocol_without_the_extra_status_word(self):
        window = self.window()
        card = window.dashboard.system
        self.settle(window)
        self.assertTrue(card.status.isHidden())
        self.assertTrue(card.dot.isHidden())
        self.assertIn('Shadowsocks', card.protocol.text())
        view = window._view('system')
        view.status = 'connected'
        view.runtime = RuntimeState(window.profiles[0].id, 'Germany', 0, 0, '', '', protocol='vless', protocol_label='VLESS')
        card.render(view)
        self.assertIn('VLESS', card.protocol.text())
        self.assertEqual(card.action_button.accessibleDescription(), 'Подключено')
        self.assertTrue(card.action_button.property('connected'))
        self.assertTrue(card.dot.isHidden())
        self.assertTrue(card.status.isHidden())

    def test_ping_pending_failed_and_https_are_distinguishable(self):
        window = self.window()
        card = window.dashboard.system
        view = window._view('system')
        view.status, view.latency_pending = 'connected', True
        card.render(view)
        self.assertEqual(card.ping_label.text(), '…')
        self.assertEqual(card.ping_caption.text(), 'Задержка')
        view.latency_pending = False
        card.render(view)
        self.assertEqual(card.ping_label.text(), 'нет ответа')
        view.latency_kind, view.latency = 'https', 609
        card.render(view)
        self.assertEqual(card.ping_label.text(), '609 мс')
        self.assertEqual(card.ping_caption.text(), 'HTTPS')
        view.status = 'offline'
        card.render(view)
        self.assertEqual(card.ping_label.text(), '—')
        self.assertFalse(card.action_button.property('connected'))

    def test_windows_have_independent_auto_open_switches(self):
        window = self.window()
        first = window.controller.collection.windows[0]
        second = window.controller.add_window(window.profiles[0].id)
        second_card = window.dashboard.insert(window._view(second.id))
        window._wire_card(second_card)
        first_card = window.dashboard.cards[first.id]
        first_card.auto.setChecked(True)
        self.assertTrue(window._view(first.id).connection.auto_open_browser)
        self.assertFalse(window._view(second.id).connection.auto_open_browser)
        self.assertFalse(second_card.auto.isChecked())

    def test_new_window_dialog_fixed_ports_and_inline_validation(self):
        window = self.window()
        dialog = self.track(ConnectionDialog(window, 'Добавить окно', window.profiles, window.profiles[0].id,
                                            window.settings, switch_factory=window._make_switch))
        self.settle(dialog)
        self.assertFalse(dialog.http.isEnabled())
        QTest.mouseClick(dialog.fixed, Qt.MouseButton.LeftButton)
        self.assertTrue(dialog.http.isEnabled())
        dialog.http.setValue(20080)
        dialog.socks.setValue(20080)
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
        self.assertTrue(dialog.error.isVisible())
        dialog.socks.setValue(20081)
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.values()['socks_port'], 20081)

    def test_browser_action_uses_its_window_ports_despite_library_selection(self):
        window = self.window()
        second = window.controller.add_window(window.profiles[0].id)
        card = window.dashboard.insert(window._view(second.id))
        window._wire_card(card)
        ids = [window.controller.collection.windows[0].id, second.id]
        for index, cid in enumerate(ids):
            entry = window.controller.entries[cid]
            entry.view.status = 'connected'
            entry.view.runtime = RuntimeState(window.profiles[0].id, window.profiles[0].name,
                18080+index*1000, 18081+index*1000, '', '', connection_id=cid)
        def run_now(key, function, callback):
            callback(function(), '')
        with patch.object(window, '_background', side_effect=run_now), \
                patch('outward_app.ui.connections.open_url_with_proxy', return_value=True) as launch:
            for cid in ids:
                window.open_connection_browser(cid)
        self.assertEqual([call.args[0] for call in launch.call_args_list], [18081, 19081])
        self.assertEqual([call.kwargs['connection_id'] for call in launch.call_args_list], ids)

    def test_scrolling_many_windows_does_not_move_the_system_panel(self):
        window = self.window()
        for _ in range(29):
            saved = window.controller.add_window(window.profiles[0].id)
            card = window.dashboard.insert(window._view(saved.id))
            window._wire_card(card)
        for size in ((903, 650), (1100, 750), (900, 560)):
            window.resize(*size)
            self.settle(window)
            panel = window.dashboard.system
            self.assertGreater(window.dashboard.scroll.verticalScrollBar().maximum(), 0)
            before = panel.mapTo(window, panel.rect().topLeft()).y()
            window.dashboard.scroll.verticalScrollBar().setValue(window.dashboard.scroll.verticalScrollBar().maximum())
            self.settle(window)
            self.assertEqual(panel.mapTo(window, panel.rect().topLeft()).y(), before)
            self.assertEqual(window.content_scroll.verticalScrollBar().maximum(), 0)
            self.assertEqual(window.dashboard.scroll.horizontalScrollBar().maximum(), 0)
            self.assertFalse(hasattr(panel, 'open_browser'))
            self.assertFalse(hasattr(panel, 'http'))
            for card in window.dashboard.cards.values():
                self.assertTrue(card.status.isHidden())

if __name__ == '__main__':
    unittest.main()
