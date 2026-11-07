"""Compact Qt title bar backed by the Windows non-client window manager.

Keep WS_CAPTION/WS_THICKFRAME/WS_SYSMENU: Windows still owns dragging,
resizing, keyboard commands and snapping. Only the caption rendering is ours.
No translucent window or region mask is used, so DWM can draw its own shadow.
"""
from __future__ import annotations

from outward_app.ui.i18n import tr

import ctypes
from ctypes import wintypes
import sys

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPalette
from PySide6.QtWidgets import QAbstractButton, QApplication, QHBoxLayout, QMainWindow, QWidget


TITLE_BAR_HEIGHT = 32
DEFAULT_WINDOW_SIZE = (903, 650 + TITLE_BAR_HEIGHT)
MINIMUM_WINDOW_SIZE = (900, 560 + TITLE_BAR_HEIGHT)

# Win32 hit-test values.
HTCLIENT, HTCAPTION, HTSYSMENU, HTMAXBUTTON = 1, 2, 3, 9
HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT = 10, 11, 12, 13, 14
HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17


class CaptionButton(QAbstractButton):
    def __init__(self, kind: str, parent: QWidget):
        super().__init__(parent)
        self.kind = kind
        self.native_hover = False
        self._keyboard_focus = False
        self.setProperty('nativeCaptionButton', True)
        self.setFixedSize(46, TITLE_BAR_HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setMouseTracking(True)
        self.set_label({'minimize': tr('Свернуть'), 'maximize': tr('Развернуть'), 'close': tr('Закрыть')}[kind])

    def set_label(self, text: str) -> None:
        self.setAccessibleName(text)
        self.setToolTip(text)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self.window().palette().color(QPalette.ColorRole.WindowText)
        hover = self.underMouse() or self.native_hover
        if hover or self.isDown():
            background = QColor(color)
            background.setAlpha(36 if self.isDown() else 22)
            if self.kind == 'close':
                background = QColor('#c42b1c' if self.isDown() else '#e81123')
                color = QColor('white')
            painter.fillRect(self.rect(), background)
        if not self.window().isActiveWindow() and not hover:
            color.setAlpha(150)
        painter.setPen(QPen(color, 1.0))
        x, y = self.width() / 2, self.height() / 2
        if self.kind == 'minimize':
            painter.drawLine(QPoint(round(x - 5), round(y)), QPoint(round(x + 5), round(y)))
        elif self.kind == 'close':
            painter.drawLine(QPoint(round(x - 4), round(y - 4)), QPoint(round(x + 4), round(y + 4)))
            painter.drawLine(QPoint(round(x + 4), round(y - 4)), QPoint(round(x - 4), round(y + 4)))
        elif self.window().isMaximized():
            painter.drawPolyline([QPoint(round(x - 3), round(y - 5)), QPoint(round(x + 5), round(y - 5)),
                                  QPoint(round(x + 5), round(y + 3))])
            painter.drawRect(QRectF(x - 5, y - 3, 8, 8))
        else:
            painter.drawRect(QRectF(x - 5, y - 5, 10, 10))
        if self.hasFocus() and self._keyboard_focus:
            painter.setPen(QPen(color, 1, Qt.PenStyle.DotLine))
            painter.drawRect(self.rect().adjusted(4, 4, -5, -5))

    def focusInEvent(self, event) -> None:
        self._keyboard_focus = event.reason() in (Qt.FocusReason.TabFocusReason,
                                                 Qt.FocusReason.BacktabFocusReason,
                                                 Qt.FocusReason.ShortcutFocusReason)
        super().focusInEvent(event)

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)


class AppTitleBar(QWidget):
    def __init__(self, window: QMainWindow):
        super().__init__(window)
        self.setObjectName('appTitleBar')
        self.setFixedHeight(TITLE_BAR_HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch()
        self.minimize_button = CaptionButton('minimize', self)
        self.maximize_button = CaptionButton('maximize', self)
        self.close_button = CaptionButton('close', self)
        for button in self.buttons:
            layout.addWidget(button)
        self.minimize_button.clicked.connect(window.showMinimized)
        self.maximize_button.clicked.connect(self.toggle_maximized)
        # Use close(), including the application's existing tray/shutdown path.
        self.close_button.clicked.connect(window.close)
        window.windowTitleChanged.connect(self.update)
        window.windowIconChanged.connect(self.update)
        window.installEventFilter(self)

    @property
    def buttons(self):
        return (self.minimize_button, self.maximize_button, self.close_button)

    def toggle_maximized(self) -> None:
        window = self.window()
        window.showNormal() if window.isMaximized() else window.showMaximized()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.WindowStateChange:
            self.maximize_button.set_label(tr('Восстановить') if self.window().isMaximized() else tr('Развернуть'))
        if event.type() in (QEvent.Type.WindowStateChange, QEvent.Type.ActivationChange,
                            QEvent.Type.PaletteChange, QEvent.Type.StyleChange):
            self.update()
            for button in self.buttons:
                button.update()
        return super().eventFilter(obj, event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        # Read the app palette: the generic QWidget QSS background also overwrites
        # the window's Button role with the canvas color.
        palette = QApplication.palette()
        painter.fillRect(self.rect(), palette.color(QPalette.ColorRole.Button))
        text_color = palette.color(QPalette.ColorRole.WindowText)
        if not self.window().isActiveWindow():
            text_color.setAlpha(150)
        painter.setPen(text_color)
        icon = self.window().windowIcon()
        if not icon.isNull():
            icon.paint(painter, 12, 8, 16, 16)
        font = self.font()
        font.setPixelSize(12)
        font.setBold(False)
        painter.setFont(font)
        available = max(0, self.minimize_button.x() - 48)
        title = painter.fontMetrics().elidedText(self.window().windowTitle(), Qt.TextElideMode.ElideRight, available)
        painter.drawText(36, 0, available, self.height(), Qt.AlignmentFlag.AlignVCenter, title)
        divider = palette.color(QPalette.ColorRole.WindowText)
        divider.setAlpha(25)
        painter.setPen(divider)
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)

    def mousePressEvent(self, event) -> None:
        # Native Windows input is handled by HTCAPTION. This is the Qt fallback.
        if event.button() == Qt.MouseButton.LeftButton and self.window().windowHandle():
            self.window().windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()


class _Margins(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int) for name in ('left', 'right', 'top', 'bottom')]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('monitor', wintypes.RECT),
                ('work', wintypes.RECT), ('flags', wintypes.DWORD)]


class _AppBarData(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('hwnd', wintypes.HWND), ('callback', wintypes.UINT),
                ('edge', wintypes.UINT), ('rect', wintypes.RECT), ('param', wintypes.LPARAM)]


class _TrackMouseEvent(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('flags', wintypes.DWORD),
                ('hwnd', wintypes.HWND), ('hoverTime', wintypes.DWORD)]


class WindowsFrame:
    """Small, pointer-safe ctypes boundary; all coordinates here are physical pixels."""
    def __init__(self):
        self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        self.dwm = ctypes.WinDLL('dwmapi')
        self.shell = ctypes.WinDLL('shell32')
        signatures = [
            (self.user32, 'GetWindowLongW', ctypes.c_long, [wintypes.HWND, ctypes.c_int]),
            (self.user32, 'SetWindowLongW', ctypes.c_long, [wintypes.HWND, ctypes.c_int, ctypes.c_long]),
            (self.user32, 'SetWindowPos', wintypes.BOOL, [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]),
            (self.user32, 'ScreenToClient', wintypes.BOOL, [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]),
            (self.user32, 'GetClientRect', wintypes.BOOL, [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]),
            (self.user32, 'IsZoomed', wintypes.BOOL, [wintypes.HWND]),
            (self.user32, 'MonitorFromWindow', wintypes.HMONITOR, [wintypes.HWND, wintypes.DWORD]),
            (self.user32, 'GetMonitorInfoW', wintypes.BOOL, [wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo)]),
            (self.user32, 'TrackMouseEvent', wintypes.BOOL, [ctypes.POINTER(_TrackMouseEvent)]),
            (self.user32, 'SetCapture', wintypes.HWND, [wintypes.HWND]),
            (self.user32, 'ReleaseCapture', wintypes.BOOL, []),
            (self.dwm, 'DwmExtendFrameIntoClientArea', ctypes.c_long, [wintypes.HWND, ctypes.POINTER(_Margins)]),
            (self.dwm, 'DwmSetWindowAttribute', ctypes.c_long, [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]),
            (self.shell, 'SHAppBarMessage', ctypes.c_size_t, [wintypes.DWORD, ctypes.POINTER(_AppBarData)]),
        ]
        for library, name, result, args in signatures:
            function = getattr(library, name)
            function.restype, function.argtypes = result, args

    def install(self, hwnd: int) -> None:
        # Qt's frameless hint suppresses caption painting. Restore native capabilities.
        style = self.user32.GetWindowLongW(hwnd, -16)
        self.user32.SetWindowLongW(hwnd, -16, style | 0x00CF0000)  # WS_OVERLAPPEDWINDOW
        self.dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(_Margins(1, 1, 1, 1)))
        self.user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0037)  # FRAMECHANGED, no move/size/z/activate

    def attribute(self, hwnd: int, name: int, value: int) -> None:
        data = ctypes.c_int(value)
        self.dwm.DwmSetWindowAttribute(hwnd, name, ctypes.byref(data), ctypes.sizeof(data))

    def maximized_client(self, hwnd: int, rect: wintypes.RECT) -> None:
        monitor = self.user32.MonitorFromWindow(hwnd, 2)
        info = _MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        if not self.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return
        rect.left, rect.top, rect.right, rect.bottom = info.work.left, info.work.top, info.work.right, info.work.bottom
        # Leave the auto-hidden taskbar's activation strip reachable on this monitor.
        for edge in range(4):
            bar = _AppBarData()
            bar.cbSize, bar.edge, bar.rect = ctypes.sizeof(bar), edge, info.monitor
            if self.shell.SHAppBarMessage(11, ctypes.byref(bar)):  # ABM_GETAUTOHIDEBAREX
                if edge == 0 and rect.left == info.monitor.left:
                    rect.left += 2
                elif edge == 1 and rect.top == info.monitor.top:
                    rect.top += 2
                elif edge == 2 and rect.right == info.monitor.right:
                    rect.right -= 2
                elif edge == 3 and rect.bottom == info.monitor.bottom:
                    rect.bottom -= 2


class ChromeMainWindow(QMainWindow):
    def __init__(self, parent=None):
        self._windows_frame = None
        self._frame_hwnd = None
        self._native_max_pressed = False
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.title_bar = AppTitleBar(self)
        self.setMenuWidget(self.title_bar)
        if sys.platform == 'win32' and QApplication.platformName() == 'windows':
            self._windows_frame = WindowsFrame()
            self._ensure_native_frame()

    def _ensure_native_frame(self) -> None:
        if self._windows_frame:
            hwnd = int(self.winId())
            if hwnd != self._frame_hwnd:
                self._frame_hwnd = hwnd
                self._windows_frame.install(hwnd)
                self.sync_native_theme()

    def sync_native_theme(self) -> None:
        if self._windows_frame and self._frame_hwnd:
            dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
            self._windows_frame.attribute(self._frame_hwnd, 20, int(dark))
            self._windows_frame.attribute(self._frame_hwnd, 33, 2)  # DWM rounding is system-owned
            border = self.palette().color(QPalette.ColorRole.WindowText)
            background = self.palette().color(QPalette.ColorRole.Window)
            # A quiet native outline in both themes; COLORREF uses BGR byte order.
            blend = QColor.fromRgbF(*(background.getRgbF()[i] * .8 + border.getRgbF()[i] * .2 for i in range(3)))
            self._windows_frame.attribute(self._frame_hwnd, 34, blend.red() | blend.green() << 8 | blend.blue() << 16)

    def showEvent(self, event) -> None:
        self._ensure_native_frame()
        super().showEvent(event)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange):
            self.sync_native_theme()

    def _caption_hit(self, point: QPoint) -> int:
        """Qt logical client coordinates, after resize-edge handling."""
        bar = self.title_bar
        local = bar.mapFrom(self, point)
        if not bar.rect().contains(local):
            return HTCLIENT
        if bar.maximize_button.geometry().contains(local):
            return HTMAXBUTTON
        if any(button.geometry().contains(local) for button in bar.buttons):
            return HTCLIENT
        return HTSYSMENU if local.x() < 32 else HTCAPTION

    def _native_hit(self, msg) -> int:
        frame = self._windows_frame
        # Signed words are essential for monitors left/above the primary display.
        point = wintypes.POINT(ctypes.c_short(msg.lParam & 0xffff).value,
                               ctypes.c_short((msg.lParam >> 16) & 0xffff).value)
        frame.user32.ScreenToClient(msg.hWnd, ctypes.byref(point))
        rect = wintypes.RECT()
        frame.user32.GetClientRect(msg.hWnd, ctypes.byref(rect))
        scale = self.devicePixelRatioF()
        if not frame.user32.IsZoomed(msg.hWnd) and not self.isFullScreen():
            border = round(6 * scale)
            left, right = point.x < border, point.x >= rect.right - border
            top, bottom = point.y < border, point.y >= rect.bottom - border
            if top:
                return HTTOPLEFT if left else HTTOPRIGHT if right else HTTOP
            if bottom:
                return HTBOTTOMLEFT if left else HTBOTTOMRIGHT if right else HTBOTTOM
            if left or right:
                return HTLEFT if left else HTRIGHT
        return self._caption_hit(QPoint(round(point.x / scale), round(point.y / scale)))

    def nativeEvent(self, event_type, message):
        frame = self._windows_frame
        if not frame or not hasattr(self, 'title_bar'):
            return super().nativeEvent(event_type, message)
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == 0x0083:  # WM_NCCALCSIZE: full client area, native capabilities retained
            rect = wintypes.RECT.from_address(msg.lParam)  # rgrc[0] when wParam is TRUE
            if frame.user32.IsZoomed(msg.hWnd) and not self.isFullScreen():
                frame.maximized_client(msg.hWnd, rect)
            return True, 0
        if msg.message == 0x0084:  # WM_NCHITTEST
            return True, self._native_hit(msg)
        button = self.title_bar.maximize_button
        if msg.message == 0x00A0:  # WM_NCMOUSEMOVE: let Windows discover HTMAXBUTTON / Snap Layouts
            button.native_hover = msg.wParam == HTMAXBUTTON
            button.update()
            tracking = _TrackMouseEvent(ctypes.sizeof(_TrackMouseEvent), 0x12, msg.hWnd, 0)
            frame.user32.TrackMouseEvent(ctypes.byref(tracking))
        elif msg.message == 0x02A2:  # WM_NCMOUSELEAVE
            button.native_hover = False
            button.update()
        elif msg.message in (0x00A1, 0x00A3) and msg.wParam == HTMAXBUTTON:
            self._native_max_pressed = True  # WM_NCLBUTTONDOWN / DBLCLK
            button.setDown(True)
            frame.user32.SetCapture(msg.hWnd)
            return True, 0
        elif msg.message in (0x0202, 0x00A2) and self._native_max_pressed:
            self._native_max_pressed = False  # client/non-client button release
            button.setDown(False)
            frame.user32.ReleaseCapture()
            if msg.message == 0x0202:
                x = ctypes.c_short(msg.lParam & 0xffff).value / self.devicePixelRatioF()
                y = ctypes.c_short((msg.lParam >> 16) & 0xffff).value / self.devicePixelRatioF()
                hit = self._caption_hit(QPoint(round(x), round(y)))
            else:
                hit = self._native_hit(msg)
            if hit == HTMAXBUTTON:
                button.click()
            return True, 0
        elif msg.message == 0x0215:  # WM_CAPTURECHANGED
            self._native_max_pressed = False
            button.setDown(False)
        return super().nativeEvent(event_type, message)
