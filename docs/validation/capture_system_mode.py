"""Native mode-selector checks using synthetic data and no network changes."""
import argparse
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
os.environ.setdefault('QT_QPA_PLATFORM', 'windows')

from PySide6.QtCore import Qt
from test_ui import MemoryStore, UiTests
from outward_app.core.models import AppSettings, RuntimeState
from outward_app.ui.i18n import set_language
from outward_app.ui.themes import theme_manager
from outward_app.ui.window_chrome import DEFAULT_WINDOW_SIZE, MINIMUM_WINDOW_SIZE


def capture(output, language):
    UiTests.setUpClass()
    case = UiTests()
    with patch.object(MemoryStore, 'load_settings', return_value=AppSettings(language=language)):
        window = case.window()
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    if output:
        output.mkdir(parents=True, exist_ok=True)
    try:
        profile = window.profiles[0]
        profile.name, profile.country_code = 'Germany', 'DE'
        set_language(language)
        for theme in ('dark', 'light'):
            theme_manager().apply(theme)
            for mode in ('tun', 'proxy'):
                window.controller.configure('system', system_mode=mode)
                for state in ('offline', 'connected', 'connecting', 'error'):
                    view = window._view('system')
                    view.status = state
                    if state == 'connected':
                        view.runtime = RuntimeState(profile.id, profile.name, 31000, 31001, '', '',
                                                    protocol='shadowsocks', protocol_label='Shadowsocks',
                                                    country_code='DE')
                        view.connected_at = time.monotonic() - 1104
                        view.latency, view.traffic_bytes = 42, 66_000_000
                    window.dashboard.update_view(view)
                    for size in (MINIMUM_WINDOW_SIZE, DEFAULT_WINDOW_SIZE, (1100, 782)):
                        window.resize(*size)
                        case.settle(window)
                        assert window.content_scroll.verticalScrollBar().maximum() == 0
                        assert window.dashboard.scroll.horizontalScrollBar().maximum() == 0
                        selector = window.dashboard.system.mode_selector
                        assert selector.buttons[mode].isChecked()
                        assert selector.isEnabled() == (state in {'offline', 'error'})
                        assert selector.width() >= selector.minimumSizeHint().width()
                        for button in selector.buttons.values():
                            assert button.width() >= button.minimumSizeHint().width()
                        if output and language == 'ru' and state == 'connected' and size == DEFAULT_WINDOW_SIZE:
                            assert window.dashboard.system.grab().save(str(output / f'system-mode-{theme}-{mode}.png'))
        print('System modes native check OK; scale:', window.devicePixelRatioF(),
              '; platform:', case.app.platformName())
    finally:
        case.doCleanups()
        set_language('ru')
        theme_manager().apply('dark')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    output = parser.parse_args().output
    for language in ('ru', 'en'):
        capture(output, language)
