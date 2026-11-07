import ast
import json
import tempfile
import unittest
from pathlib import Path
from string import Formatter
from unittest.mock import Mock, patch

import test_ui as fixture
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox, QDialogButtonBox, QLabel, QMessageBox

from outward_app.core.models import AppSettings
from outward_app.core.storage import JsonStore
from outward_app.ui.i18n import ENGLISH, set_language, tr, traffic_text
from outward_app.ui.themes import theme_manager


class LanguageStorageTests(unittest.TestCase):
    def test_language_write_preserves_saved_settings_and_unknown_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'settings.json'
            original = {'theme': 'light', 'http_port': 18080, 'launch_on_startup': True, 'future': 'keep'}
            path.write_text(json.dumps(original), encoding='utf-8')
            store = JsonStore(root / 'profiles.json', path)
            store.save_language('en')
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), {**original, 'language': 'en'})
            self.assertEqual(store.load_settings().language, 'en')

    def test_legacy_and_invalid_language_use_russian(self):
        for value in (None, '', 'de', ['en'], 42):
            self.assertEqual(AppSettings.from_dict({'language': value}).language, 'ru')
        self.assertEqual(AppSettings.from_dict({}).language, 'ru')

    def test_catalog_covers_ui_strings_and_preserves_format_parameters(self):
        root = Path(__file__).resolve().parents[1] / 'outward_app/ui'
        for path in root.glob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'tr'
                        and node.args and isinstance(node.args[0], ast.Constant)):
                    source = node.args[0].value
                    if isinstance(source, str) and any('\u0400' <= c <= '\u04ff' for c in source):
                        self.assertIn(source, ENGLISH, f'{path.name}:{node.lineno}')
        for source, translated in ENGLISH.items():
            fields = lambda text: sorted((name, spec, conversion) for _, name, spec, conversion
                                         in Formatter().parse(text) if name is not None)
            self.assertEqual(fields(source), fields(translated), source)

    def test_translation_preserves_user_values_and_localizes_units(self):
        self.addCleanup(set_language, 'ru')
        set_language('en')
        name = 'Настройки {test} / private.example'
        self.assertEqual(tr('Удалить профиль {0}?', name), 'Delete profile ' + name + '?')
        self.assertEqual(tr('Unknown diagnostic {raw}'), 'Unknown diagnostic {raw}')
        self.assertEqual(traffic_text(1500), '1.5 KB')
        set_language('ru')
        self.assertEqual(traffic_text(1500), '1,5 КБ')


class LanguageUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.UiTests.setUpClass()
        cls.app = fixture.UiTests.app

    def setUp(self):
        self.case = fixture.UiTests('test_settings_route_keeps_connection_cards_and_unsaved_fields')
        self.addCleanup(set_language, 'ru')
        self.addCleanup(theme_manager().apply, 'dark')
        self.addCleanup(self.case.doCleanups)

    def window(self, language='ru'):
        with patch.object(fixture.MemoryStore, 'load_settings', return_value=AppSettings(language=language)):
            window = self.case.window()
        window.store.save_language = Mock()
        window._set_route('settings')
        window._set_tab_index(1)
        self.case.settle(window)
        return window

    def test_select_saves_without_applying_drafts_or_recreating_sessions(self):
        window = self.window()
        combo = window.language_combo
        self.assertIsInstance(combo, QComboBox)
        self.assertFalse(combo.isEditable())
        self.assertEqual([combo.itemText(i) for i in range(combo.count())], ['Русский', 'English'])
        cid = window.controller.collection.windows[0].id
        card = window.dashboard.cards[cid]
        window.controller.entries[cid].view.status = 'connected'
        window.dns_edit.setText('9.9.9.9')
        window.socks_port_spin.setValue(window.http_port_spin.value())
        with patch.object(window.store, 'save_settings') as save, \
                patch.object(window.controller, 'configure') as configure, \
                patch.object(window, '_sync_windows_startup') as startup:
            combo.setFocus()
            QTest.keyClick(combo, Qt.Key.Key_Down)
            self.app.processEvents()
            window.store.save_language.assert_called_once_with('en')
            save.assert_not_called()
            configure.assert_not_called()
            startup.assert_not_called()
        self.assertEqual(window.settings.language, 'en')
        self.assertEqual(window.settings_button.text(), 'Настройки')  # Applied at next launch.
        self.assertEqual(window.dns_edit.text(), '9.9.9.9')
        self.assertEqual(window.socks_port_spin.value(), window.http_port_spin.value())
        self.assertIs(window.dashboard.cards[cid], card)
        self.assertEqual(window._view(cid).status, 'connected')
        combo.setCurrentIndex(0)
        self.assertEqual(window.settings.language, 'ru')

    def test_failed_save_restores_choice(self):
        window = self.window()
        window.store.save_language.side_effect = OSError('Disk unavailable')
        with patch.object(fixture.ui.QMessageBox, 'warning') as warning:
            window.language_combo.setCurrentIndex(1)
        warning.assert_called_once()
        self.assertEqual(window.language_combo.currentData(), 'ru')
        self.assertEqual(window.settings.language, 'ru')

    def test_standard_dialog_buttons_follow_app_language(self):
        for language, expected in (
            ('ru', {'Yes': 'Да', 'No': 'Нет', 'Cancel': 'Отмена', 'Save': 'Сохранить', 'Close': 'Закрыть'}),
            ('en', {'Yes': 'Yes', 'No': 'No', 'Cancel': 'Cancel', 'Save': 'Save', 'Close': 'Close'}),
            ('ru', {'Yes': 'Да', 'No': 'Нет', 'Cancel': 'Отмена', 'Save': 'Сохранить', 'Close': 'Закрыть'}),
        ):
            set_language(language)
            buttons = self.case.track(QDialogButtonBox())
            for name, text in expected.items():
                with self.subTest(language=language, button=name):
                    button = buttons.addButton(getattr(QDialogButtonBox.StandardButton, name))
                    self.assertEqual(button.text().replace('&', ''), text)
                    self.assertEqual(buttons.standardButton(button), getattr(QDialogButtonBox.StandardButton, name))

    def test_service_confirmation_has_translated_buttons_and_no_still_cancels(self):
        window = self.window('ru')
        observed = []

        def dismiss():
            box = self.app.activeModalWidget()
            if isinstance(box, QMessageBox):
                observed.extend(box.button(button).text().replace('&', '')
                                for button in (QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No))
                QTest.mouseClick(box.button(QMessageBox.StandardButton.No), Qt.MouseButton.LeftButton)

        QTimer.singleShot(0, dismiss)
        # A failed dialog lookup must not leave the test blocked in a modal loop.
        timeout = QTimer(window)
        timeout.setSingleShot(True)
        timeout.timeout.connect(lambda: self.app.activeModalWidget().reject()
                                if isinstance(self.app.activeModalWidget(), QMessageBox) else None)
        timeout.start(3000)
        with patch.object(window, '_background') as background:
            window.install_vpn_component()
            background.assert_not_called()
        timeout.stop()
        self.assertEqual(observed, ['Да', 'Нет'])

    def test_english_startup_translates_existing_and_new_widgets(self):
        window = self.window('en')
        self.assertEqual(window.settings_button.text(), 'Settings')
        self.assertEqual(window.language_combo.currentData(), 'en')
        self.assertEqual(window.language_combo.accessibleName(), 'Language')
        self.assertIn('after restart', window.language_combo.accessibleDescription())
        self.assertEqual(window.title_bar.minimize_button.accessibleName(), 'Minimize')
        self.assertEqual(window.dashboard.system.action_button.accessibleDescription(), 'Off')
        self.assertEqual(window.profiles[0].name, 'Рабочий профиль')
        dialog = self.case.track(fixture.ProfileDialog(window))
        self.assertTrue(any(label.text() == 'New profile' for label in dialog.findChildren(QLabel)))
        with patch.object(window.store, 'save_settings') as save:
            window.save_settings()
        self.assertEqual(save.call_args.args[0].language, 'en')

    def test_select_fits_both_languages_themes_and_window_sizes(self):
        for language in ('ru', 'en'):
            window = self.window(language)
            for theme in ('dark', 'light'):
                theme_manager().apply(theme)
                for size in ((900, 592), (903, 682), (1100, 782)):
                    with self.subTest(language=language, theme=theme, size=size):
                        window.resize(*size)
                        self.case.settle(window)
                        combo = window.language_combo
                        self.assertEqual(window.content_scroll.verticalScrollBar().maximum(), 0)
                        self.assertEqual(window.legacy_scroll.horizontalScrollBar().maximum(), 0)
                        self.assertLessEqual(combo.geometry().right(), window.general_settings_card.width())
                        self.assertGreaterEqual(combo.width(), combo.fontMetrics().horizontalAdvance('Русский') + 40)


if __name__ == '__main__':
    unittest.main()
