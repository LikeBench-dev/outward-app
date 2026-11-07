"""Graphite palettes shared by QSS, custom painters, rich text and Fluent."""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from outward_app.core.models import normalize_theme


THEME_COLORS = {
    "dark": {
        "canvas": "#101010", "sidebar": "#141414", "panel": "#1D1D1D",
        "raised": "#242424", "input": "#171717", "border": "#363636",
        "control_border": "#707070", "text": "#ECECEC", "muted": "#A8A8A8",
        "disabled_text": "#858585", "disabled_bg": "#252525",
        "selection": "#2A2A2A", "hover": "#2B2B2B", "pressed": "#303030",
        "accent": "#D5D5D5", "focus": "#ECECEC",
        "primary": "#E6E6E6", "primary_hover": "#FFFFFF", "primary_pressed": "#CCCCCC",
        "on_primary": "#101010", "selection_text_bg": "#454545", "selection_text": "#FFFFFF",
        "success": "#58D59B", "warning": "#E9B949", "error": "#FF8F8F",
        "success_surface": "#20352C",
        "danger_bg": "#B42318", "danger_hover": "#C93228", "danger_pressed": "#981B13",
        "on_danger": "#FFFFFF", "scrollbar": "#626262", "scrollbar_hover": "#858585",
        "overlay": "rgba(0, 0, 0, 150)",
    },
    "light": {
        "canvas": "#F5F5F4", "sidebar": "#EBEBE9", "panel": "#FFFFFF",
        "raised": "#F0F0EE", "input": "#FAFAFA", "border": "#D6D6D2",
        "control_border": "#85857F", "text": "#202020", "muted": "#62625E",
        "disabled_text": "#767670", "disabled_bg": "#E5E5E2",
        "selection": "#DEDEDA", "hover": "#E7E7E3", "pressed": "#D9D9D4",
        "accent": "#333333", "focus": "#333333",
        "primary": "#333333", "primary_hover": "#202020", "primary_pressed": "#101010",
        "on_primary": "#FFFFFF", "selection_text_bg": "#333333", "selection_text": "#FFFFFF",
        "success": "#167749", "warning": "#8A5A00", "error": "#B42318",
        "success_surface": "#E8F3EC",
        "danger_bg": "#B42318", "danger_hover": "#981B13", "danger_pressed": "#7F170F",
        "on_danger": "#FFFFFF", "scrollbar": "#85857F", "scrollbar_hover": "#62625E",
        "overlay": "rgba(0, 0, 0, 70)",
    },
}


def current_theme() -> str:
    app = QApplication.instance()
    manager = getattr(app, "_outward_theme_manager", None)
    return manager.name if manager is not None else "dark"


def theme_colors(name: str | None = None) -> dict[str, str]:
    return THEME_COLORS[normalize_theme(name if name is not None else current_theme())]


def theme_color(role: str) -> QColor:
    return QColor(theme_colors()[role])


def sync_fluent_theme(name: str = "dark") -> None:
    try:
        from qfluentwidgets import Theme, setTheme, setThemeColor
    except ImportError:
        return
    name = normalize_theme(name)
    setTheme(Theme.LIGHT if name == "light" else Theme.DARK)
    setThemeColor(THEME_COLORS[name]["accent"])


class ThemeManager(QObject):
    theme_changed = Signal(str)

    def __init__(self, app: QApplication):
        super().__init__(app)
        self.app = app
        self.name = "dark"
        self._applied = False

    def apply(self, name: str) -> None:
        name = normalize_theme(name)
        if self._applied and name == self.name:
            return
        self.name = name
        colors = theme_colors(name)
        sync_fluent_theme(name)
        palette = QPalette()
        roles = {
            "Window": "canvas", "WindowText": "text", "Base": "input",
            "AlternateBase": "raised", "Text": "text", "Button": "raised",
            "ButtonText": "text", "PlaceholderText": "muted",
            "Highlight": "selection_text_bg", "HighlightedText": "selection_text",
            "ToolTipBase": "raised", "ToolTipText": "text",
            "Link": "accent", "LinkVisited": "accent", "BrightText": "error",
            "Mid": "control_border", "Dark": "border", "Light": "raised",
        }
        for role, token in roles.items():
            palette.setColor(getattr(QPalette.ColorRole, role), QColor(colors[token]))
        for role in ("WindowText", "Text", "ButtonText", "PlaceholderText"):
            palette.setColor(QPalette.ColorGroup.Disabled, getattr(QPalette.ColorRole, role),
                             QColor(colors["disabled_text"]))
        self.app.setPalette(palette)
        hints = self.app.styleHints()
        if hasattr(hints, "setColorScheme"):
            hints.setColorScheme(Qt.ColorScheme.Light if name == "light" else Qt.ColorScheme.Dark)
        from outward_app.ui.styles import build_styles
        self.app.setStyleSheet(build_styles(name))
        self._applied = True
        self.theme_changed.emit(name)


def theme_manager() -> ThemeManager:
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("A QApplication is required to apply a theme")
    manager = getattr(app, "_outward_theme_manager", None)
    if manager is None:
        manager = ThemeManager(app)
        app._outward_theme_manager = manager
    return manager

