import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QTest

import test_ui as fixtures
from outward_app.ui.i18n import set_language


class SystemModeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.UiTests.setUpClass()

    def setUp(self):
        set_language('ru')
        self.case = fixtures.UiTests()
        self.addCleanup(self.case.doCleanups)
        self.window = self.case.window()
        self.card = self.window.dashboard.system
        self.selector = self.card.mode_selector
        self.case.settle(self.window)

    def test_click_and_keyboard_persist_mode_without_starting_a_session(self):
        with patch.object(self.window.controller, 'start') as start:
            QTest.mouseClick(self.selector.buttons['proxy'], Qt.MouseButton.LeftButton)
            self.assertEqual(self.window._view('system').connection.system_mode, 'proxy')
            self.assertTrue(self.selector.buttons['proxy'].isChecked())
            self.selector.buttons['tun'].setFocus()
            QTest.keyClick(self.selector.buttons['tun'], Qt.Key.Key_Space)
            self.assertEqual(self.window._view('system').connection.system_mode, 'tun')
            start.assert_not_called()
        accessible = QAccessible.queryAccessibleInterface(self.selector.buttons['tun'])
        self.assertTrue(accessible.state().checked)
        self.assertIn('TUN', accessible.text(QAccessible.Text.Name))

    def test_selector_is_locked_during_active_and_transitional_states(self):
        for state in ('preparing', 'connecting', 'connected', 'reconnecting', 'stopping'):
            view = self.window._view('system')
            view.status = state
            self.card.render(view)
            self.assertFalse(self.selector.isEnabled(), state)
            QTest.mouseClick(self.selector.buttons['proxy'], Qt.MouseButton.LeftButton)
            self.assertTrue(self.selector.buttons['tun'].isChecked())
        view.status = 'offline'
        self.card.render(view)
        self.assertTrue(self.selector.isEnabled())

    def test_failed_save_restores_previous_selection(self):
        with patch.object(self.window.store, 'save_connections', side_effect=OSError('disk full')):
            QTest.mouseClick(self.selector.buttons['proxy'], Qt.MouseButton.LeftButton)
        self.assertTrue(self.selector.buttons['tun'].isChecked())
        self.assertEqual(self.window._view('system').connection.system_mode, 'tun')
        self.assertIn('disk full', self.card.message.text())

    def test_proxy_mode_never_offers_or_starts_the_vpn_service(self):
        self.window._configure_connection('system', system_mode='proxy')
        with patch('outward_app.core.vpn_pipe.service_status') as status, \
                patch('outward_app.ui.connections.QMenu'):
            self.window.connection_menu('system')
            status.assert_not_called()
        self.window.controller.entries['system'].view.status = 'error'
        self.window.controller.entries['system'].view.message = 'служба недоступна'
        with patch.object(self.window, 'install_vpn_component') as install, \
                patch.object(self.window, 'start_connection') as start:
            self.window._connection_action('system')
            install.assert_not_called()
            start.assert_called_once_with('system')

    def test_switching_modes_keeps_profile_metrics_and_window_cards(self):
        before = self.window._view('system').connection.profile_id
        windows = tuple(self.window.dashboard.cards)
        self.window._configure_connection('system', system_mode='proxy')
        self.assertEqual(self.window._view('system').connection.profile_id, before)
        self.assertEqual(tuple(self.window.dashboard.cards), windows)
        self.assertTrue(self.card.dot.isHidden())
        self.assertTrue(self.card.status.isHidden())
        self.assertEqual(self.selector.layout().count(), 2)
        self.assertEqual(self.selector.buttons['proxy'].text(), 'Системный прокси')


if __name__ == '__main__':
    unittest.main()
