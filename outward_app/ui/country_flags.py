from outward_app.ui.i18n import tr
"""Offline country icons shared by profile rows and the country picker."""

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QIcon, QPainter
from PySide6.QtWidgets import QLabel

from outward_app.core.countries import country_label, normalize_country_code
from outward_app.paths import asset_path


def country_icon(code: str = "") -> QIcon:
    code = normalize_country_code(code)
    flag = asset_path(f"flags/{code.lower()}.svg") if code else None
    if flag is None or not flag.is_file():
        flag = asset_path("flags/unknown.svg")
    icon = QIcon(str(flag))
    # Native Qt styles may tint generated selected/active icons. Flag colors
    # must remain recognizable while navigating the country picker.
    for mode in (QIcon.Mode.Selected, QIcon.Mode.Active):
        icon.addFile(str(flag), mode=mode)
    return icon


class CountryFlagBadge(QLabel):
    def __init__(self, code: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("profileCountryBadge")
        self.setFixedSize(28, 20)
        self._icon = country_icon(code)
        description = country_label(code) if normalize_country_code(code) else tr('Страна не определена')
        self.setToolTip(description)
        self.setAccessibleName(description)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        # QIcon paints at the current screen's device pixel ratio, including
        # when a window is moved between monitors with different scaling.
        self._icon.paint(painter, QRect(2, 1, 24, 18), Qt.AlignmentFlag.AlignCenter)
