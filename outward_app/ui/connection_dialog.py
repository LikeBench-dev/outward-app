from __future__ import annotations

from outward_app.ui.i18n import tr

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout
from outward_app.ui.connection_card import ResourceCombo


class ConnectionDialog(QDialog):
    def __init__(self, parent, title, profiles, selected_id, settings, connection=None, *, system=False, switch_factory=QCheckBox):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(460)
        self.system = system
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        panel = QFrame()
        panel.setObjectName("profileDialogPanel")
        root.addWidget(panel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 24, 24, 22)
        layout.setSpacing(14)
        heading = QLabel(title)
        heading.setWordWrap(True)
        heading.setObjectName("dialogTitle")
        layout.addWidget(heading)
        profile_label = QLabel(tr('Профиль подключения'))
        profile_label.setObjectName("fieldLabel")
        self.profile = ResourceCombo()
        self.profile.setStyleSheet('QComboBox { padding-right: 28px; }')
        self.profile.setAccessibleName(tr('Профиль подключения'))
        for item in profiles:
            self.profile.addItem(item.name, item.id)
        self.profile.setCurrentIndex(max(0, self.profile.findData(selected_id)))
        profile_label.setBuddy(self.profile)
        layout.addWidget(profile_label)
        layout.addWidget(self.profile)
        if not system:
            hint = QLabel(tr('У окна будут собственные HTTP- и SOCKS5-порты. Браузер запускается через SOCKS5 этого окна.'))
            hint.setObjectName("mutedLabel")
            hint.setWordWrap(True)
            layout.addWidget(hint)
            self.fixed = switch_factory()
            self.fixed.setAccessibleName(tr('Закрепить порты вручную'))
            self.fixed.setChecked(connection.fixed_ports if connection else False)
            fixed_row = QHBoxLayout()
            fixed_label = QLabel(tr('Закрепить порты вручную'))
            fixed_label.setBuddy(self.fixed)
            fixed_row.addWidget(fixed_label, 1)
            fixed_row.addWidget(self.fixed)
            layout.addLayout(fixed_row)
            ports = QGridLayout()
            self.http, self.socks = QSpinBox(), QSpinBox()
            for spin, name, value, column in ((self.http, "HTTP Port", connection.http_port if connection else settings.http_port, 0),
                                              (self.socks, "SOCKS5 Port", connection.socks_port if connection else settings.socks_port, 1)):
                spin.setRange(1024, 65535)
                spin.setValue(value)
                spin.setAccessibleName(name)
                label = QLabel(name)
                label.setObjectName("fieldLabel")
                label.setBuddy(spin)
                ports.addWidget(label, 0, column)
                ports.addWidget(spin, 1, column)
                spin.setEnabled(self.fixed.isChecked())
                self.fixed.toggled.connect(spin.setEnabled)
            layout.addLayout(ports)
            hint = QLabel(tr('В автоматическом режиме приложение выберет свободные порты. Закрепленный занятый порт не будет заменен.'))
            hint.setObjectName("mutedLabel")
            hint.setWordWrap(True)
            layout.addWidget(hint)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setObjectName("connectionMessage")
        self.error.hide()
        layout.addWidget(self.error)
        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton(tr('Отмена'))
        cancel.setObjectName("ghostButton")
        cancel.clicked.connect(self.reject)
        accept = QPushButton(tr('Сохранить') if connection or system else tr('Добавить окно'))
        accept.setObjectName("primaryButton")
        accept.clicked.connect(self.accept)
        actions.addWidget(cancel)
        actions.addWidget(accept)
        layout.addLayout(actions)

    def accept(self):
        if not self.profile.currentData():
            self.error.setText(tr('Добавьте и выберите профиль подключения.'))
            self.error.show()
            return
        if not self.system and self.http.value() == self.socks.value():
            self.error.setText(tr('HTTP и SOCKS5 должны использовать разные порты.'))
            self.error.show()
            return
        super().accept()

    def values(self):
        result = {"profile_id": self.profile.currentData()}
        if not self.system:
            result.update(http_port=self.http.value(), socks_port=self.socks.value(), fixed_ports=self.fixed.isChecked())
        return result
