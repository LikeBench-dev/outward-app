import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from outward_app.core.autostart import startup_command
from outward_app.core.models import AppSettings, ConnectionCollection
from outward_app.core.storage import JsonStore


class AutostartTests(unittest.TestCase):
    def test_windows_startup_commands_identify_automatic_launch(self):
        with patch.object(sys, 'frozen', False, create=True), patch.object(sys, 'executable', 'C:/Python/python.exe'):
            self.assertEqual(startup_command(), subprocess.list2cmdline(
                ['C:/Python/python.exe', '-m', 'outward_app', '--autostart']))
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', 'C:/Apps/Outward App.exe'):
            self.assertEqual(startup_command(), subprocess.list2cmdline(['C:/Apps/Outward App.exe', '--autostart']))

    def test_legacy_toggle_migrates_to_launch_and_initial_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = JsonStore(root / 'profiles.json', root / 'settings.json')
            store.settings_file.write_text(json.dumps({'auto_connect_on_startup': True}), encoding='utf-8')
            settings = store.load_settings()
            self.assertTrue(settings.launch_on_startup)
            collection = store.load_connections(settings, 'profile')
            self.assertTrue(collection.windows[0].auto_connect)
            self.assertFalse(collection.system.auto_connect)

    def test_existing_connection_choices_determine_legacy_launch_setting(self):
        for selected in ('none', 'system', 'second'):
            with self.subTest(selected=selected), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                store = JsonStore(root / 'profiles.json', root / 'settings.json')
                collection = ConnectionCollection()
                first = collection.add_window('first-profile', AppSettings())
                second = collection.add_window('second-profile', AppSettings())
                collection.system.auto_connect = selected == 'system'
                second.auto_connect = selected == 'second'
                store.save_connections(collection)
                # The previous UI could leave this old toggle out of sync with individual choices.
                store.settings_file.write_text(json.dumps({'auto_connect_on_startup': selected == 'none'}), encoding='utf-8')
                original = store.connections_file.read_bytes()
                settings = store.load_settings()
                self.assertEqual(settings.launch_on_startup, selected != 'none')
                store.save_settings(settings)
                self.assertEqual(store.load_settings().launch_on_startup, selected != 'none')
                self.assertEqual(store.connections_file.read_bytes(), original)
                self.assertFalse(first.auto_connect)

    def test_explicit_launch_setting_is_independent_of_saved_connection_choices(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                store = JsonStore(root / 'profiles.json', root / 'settings.json')
                collection = ConnectionCollection()
                connection = collection.add_window('profile', AppSettings())
                connection.auto_connect = not enabled
                store.save_connections(collection)
                store.save_settings(AppSettings(launch_on_startup=enabled, auto_connect_on_startup=True))
                self.assertEqual(store.load_settings().launch_on_startup, enabled)
                self.assertEqual(store.load_connections(store.load_settings()).windows[0].auto_connect, not enabled)


if __name__ == '__main__':
    unittest.main()
