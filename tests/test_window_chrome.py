"""Caption actions and real Windows messages, without connections or app data."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import unittest

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from outward_app.ui.window_chrome import (
    ChromeMainWindow, DEFAULT_WINDOW_SIZE, HTCAPTION, HTCLIENT, HTMAXBUTTON,
    HTSYSMENU, HTTOPLEFT, HTBOTTOMRIGHT, TITLE_BAR_HEIGHT,
)


class RecordingWindow(ChromeMainWindow):
    def __init__(self):
        super().__init__()
        self.close_requests = 0

    def closeEvent(self, event):
        self.close_requests += 1
        event.ignore()


class ChromeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def window(self, size=DEFAULT_WINDOW_SIZE):
        window = RecordingWindow()
        window.setWindowTitle('Outward App')
        window.resize(*size)
        window.setCentralWidget(QLabel('Content'))
        if self.app.platformName() != 'windows':
            window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.show()
        self.app.processEvents()
        self.addCleanup(self.dispose, window)
        return window

    def dispose(self, window):
        window.hide()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_caption_actions_and_keyboard_accessibility(self):
        window = self.window()
        bar = window.title_bar
        self.assertEqual(bar.height(), TITLE_BAR_HEIGHT)
        self.assertEqual(window.centralWidget().height(), 650)
        self.assertEqual(window.windowTitle(), 'Outward App')
        for button in bar.buttons:
            self.assertTrue(button.accessibleName())
            self.assertEqual(button.focusPolicy(), Qt.FocusPolicy.StrongFocus)
        QTest.mouseClick(bar.maximize_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertTrue(window.isMaximized())
        self.assertEqual(bar.maximize_button.accessibleName(), 'Восстановить')
        window.grab()  # Also exercise the restored-window vector glyph.
        bar.maximize_button.setFocus()
        QTest.keyClick(bar.maximize_button, Qt.Key.Key_Space)
        self.app.processEvents()
        self.assertFalse(window.isMaximized())
        self.assertEqual(bar.maximize_button.accessibleName(), 'Развернуть')
        QTest.mouseClick(bar.close_button, Qt.MouseButton.LeftButton)
        self.assertEqual(window.close_requests, 1)
        self.assertTrue(window.isVisible())  # Application close handler keeps control.
        QTest.mouseClick(bar.minimize_button, Qt.MouseButton.LeftButton)
        self.assertTrue(window.isMinimized())
        window.showNormal()
        self.assertEqual(window.size().toTuple(), DEFAULT_WINDOW_SIZE)

    def test_only_caption_and_maximize_regions_are_non_client(self):
        window = self.window()
        bar = window.title_bar
        self.assertEqual(window._caption_hit(QPoint(100, 16)), HTCAPTION)
        self.assertEqual(window._caption_hit(QPoint(20, 16)), HTSYSMENU)
        self.assertEqual(window._caption_hit(QPoint(100, 100)), HTCLIENT)
        self.assertEqual(window._caption_hit(bar.maximize_button.geometry().center()), HTMAXBUTTON)
        for button in (bar.minimize_button, bar.close_button):
            self.assertEqual(window._caption_hit(button.geometry().center()), HTCLIENT)

    def test_bar_uses_current_palette_in_both_themes(self):
        window = self.window()
        stylesheet = self.app.styleSheet()
        self.addCleanup(self.app.setStyleSheet, stylesheet)
        self.addCleanup(self.app.setPalette, self.app.palette())
        self.app.setStyleSheet('')
        # The application stylesheet need not know about the caption component.
        for background, foreground in (('#101010', '#ECECEC'), ('#F5F5F4', '#202020')):
            palette = QPalette()
            palette.setColor(QPalette.ColorRole.Window, QColor(background))
            palette.setColor(QPalette.ColorRole.Button, QColor(background))
            palette.setColor(QPalette.ColorRole.WindowText, QColor(foreground))
            self.app.setPalette(palette)
            window.setPalette(palette)
            self.app.processEvents()
            capture = window.title_bar.grab().toImage()
            self.assertEqual(capture.pixelColor(100, 4).name(), background.lower())

    @unittest.skipUnless(sys.platform == 'win32', 'Native Windows caption integration')
    def test_native_windows_messages_at_three_scales(self):
        if self.app.platformName() == 'windows':
            self.skipTest('Native subprocess already running')
        for scale in ('1', '1.25', '1.5'):
            with self.subTest(scale=scale):
                environment = os.environ.copy()
                environment.update(QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR=scale)
                result = subprocess.run(
                    [sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), '--native'],
                    cwd=Path(__file__).resolve().parent.parent, env=environment,
                    capture_output=True, text=True, encoding='utf-8', timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def native_checks():
    """Use actual HWND messages; no network or persistent settings."""
    ChromeTests.setUpClass()
    case = ChromeTests('test_only_caption_and_maximize_regions_are_non_client')
    # A hosted Windows desktop can be smaller than the app's default size at
    # 125/150% scaling. Leave room for native frame metrics so Windows does not
    # clamp the normal bounds when restoring; default app sizing is tested
    # separately by test_ui.py and the offscreen caption checks above.
    work = case.app.primaryScreen().availableGeometry()
    normal_size = (min(DEFAULT_WINDOW_SIZE[0], max(1, work.width() - 32)),
                   min(DEFAULT_WINDOW_SIZE[1], max(1, work.height() - 32)))
    window = case.window(size=normal_size)
    user32 = window._windows_frame.user32
    hwnd = int(window.winId())
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetSystemMenu.argtypes = [wintypes.HWND, wintypes.BOOL]
    user32.GetSystemMenu.restype = wintypes.HMENU
    scale = window.devicePixelRatioF()

    def packed(x, y):
        return (int(x) & 0xffff) | ((int(y) & 0xffff) << 16)

    def hit(x, y):
        point = wintypes.POINT(round(x * scale), round(y * scale))
        user32.ClientToScreen(hwnd, ctypes.byref(point))
        return user32.SendMessageW(hwnd, 0x0084, 0, packed(point.x, point.y))

    try:
        case.assertEqual(window.size().toTuple(), normal_size)
        style = user32.GetWindowLongW(hwnd, -16)
        case.assertEqual(style & 0x00CF0000, 0x00CF0000)
        case.assertTrue(user32.GetSystemMenu(hwnd, False))
        for position in ((100, 100), (-1200, -600)):
            user32.SetWindowPos(hwnd, None, *position, 0, 0, 0x0015)
            case.app.processEvents()
            case.assertEqual(hit(100, 16), HTCAPTION)
            case.assertEqual(hit(20, 16), HTSYSMENU)
            case.assertEqual(hit(100, 100), HTCLIENT)
            case.assertEqual(hit(1, 1), HTTOPLEFT)
            case.assertEqual(hit(window.width() - 1, window.height() - 1), HTBOTTOMRIGHT)
            center = window.title_bar.maximize_button.geometry().center()
            case.assertEqual(hit(center.x(), center.y()), HTMAXBUTTON)

        # Native maximize / restore (the same system commands as Win+Up / the system menu).
        user32.SendMessageW(hwnd, 0x0112, 0xF030, 0)
        case.app.processEvents()
        case.assertTrue(window.isMaximized())
        rect = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        origin = wintypes.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(origin))
        from outward_app.ui.window_chrome import _MonitorInfo
        info = _MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(info))
        case.assertGreaterEqual(origin.x, info.work.left)
        case.assertGreaterEqual(origin.y, info.work.top)
        case.assertLessEqual(origin.x + rect.right, info.work.right)
        case.assertLessEqual(origin.y + rect.bottom, info.work.bottom)
        case.assertEqual(hit(100, 1), HTCAPTION)  # No resize edge when maximized.
        user32.SendMessageW(hwnd, 0x0112, 0xF120, 0)
        case.app.processEvents()
        case.assertFalse(window.isMaximized())
        case.assertEqual(window.size().toTuple(), normal_size)

        caption = wintypes.POINT(round(120 * scale), round(16 * scale))
        user32.ClientToScreen(hwnd, ctypes.byref(caption))
        user32.SendMessageW(hwnd, 0x00A3, HTCAPTION, packed(caption.x, caption.y))
        case.app.processEvents()
        case.assertTrue(window.isMaximized())  # Native title-bar double-click.
        user32.SendMessageW(hwnd, 0x0112, 0xF120, 0)
        case.app.processEvents()
        case.assertEqual(window.size().toTuple(), normal_size)

        # Maximize gets non-client input for Snap, but activates our Qt action once.
        center = window.title_bar.maximize_button.geometry().center()
        point = wintypes.POINT(round(center.x() * scale), round(center.y() * scale))
        user32.ClientToScreen(hwnd, ctypes.byref(point))
        user32.SendMessageW(hwnd, 0x00A1, HTMAXBUTTON, packed(point.x, point.y))
        user32.SendMessageW(hwnd, 0x0202, 0, packed(100 * scale, 100 * scale))
        case.app.processEvents()
        case.assertFalse(window.isMaximized())  # Releasing outside cancels the button.
        user32.SendMessageW(hwnd, 0x00A1, HTMAXBUTTON, packed(point.x, point.y))
        user32.SendMessageW(hwnd, 0x0202, 0, packed(center.x() * scale, center.y() * scale))
        case.app.processEvents()
        case.assertTrue(window.isMaximized())
        # Native close must reach the existing Qt closeEvent (tray/cleanup policy).
        user32.SendMessageW(hwnd, 0x0112, 0xF060, 0)
        case.app.processEvents()
        case.assertEqual(window.close_requests, 1)
        print('Native caption OK, scale:', scale)
    finally:
        case.doCleanups()


if __name__ == '__main__':
    if '--native' in sys.argv:
        native_checks()
    else:
        unittest.main()
