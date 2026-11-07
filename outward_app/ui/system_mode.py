"""Compact mode selector for the pinned system connection card."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget

from outward_app.ui.i18n import tr


class SystemModeSelector(QWidget):
    mode_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName(tr('Режим системного подключения'))
        self.setToolTip(tr('Режим можно изменить после отключения'))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.group = QButtonGroup(self)
        self.buttons = {}
        for mode, text in (('tun', 'TUN'), ('proxy', tr('Системный прокси'))):
            button = QPushButton(text)
            button.setObjectName('systemModeOption')
            button.setProperty('edge', 'left' if mode == 'tun' else 'right')
            button.setCheckable(True)
            button.setMinimumHeight(28)
            button.setAccessibleName(tr('Режим системного подключения') + ': ' + text)
            button.clicked.connect(lambda checked=False, value=mode: self.mode_selected.emit(value))
            self.group.addButton(button)
            self.buttons[mode] = button
            layout.addWidget(button)
        self.set_mode('tun')

    def set_mode(self, mode):
        self.buttons[mode].setChecked(True)
