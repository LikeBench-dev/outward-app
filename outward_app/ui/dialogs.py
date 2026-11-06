from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from outward_app.core.connections import ParsedConnection, parse_connection, sanitize_connection_error
from outward_app.core.countries import country_options, guess_country_code, normalize_country_code
from outward_app.core.models import ConnectionProfile


class ProfileDialog(QDialog):
    def __init__(self, parent=None, profile: ConnectionProfile | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Изменить профиль" if profile else "Новый профиль")
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(460)
        self.profile = profile
        self.parsed: ParsedConnection | None = None
        self.country_options = [("Определить автоматически", "")] + [(f"{code} {name}", code) for code, name in country_options()]

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        panel = QFrame()
        panel.setObjectName("profileDialogPanel")
        root.addWidget(panel)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 24, 24, 22)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(12)
        badge = QLabel("+")
        badge.setObjectName("dialogBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Новый профиль" if profile is None else "Редактировать профиль")
        title.setObjectName("dialogTitle")
        close_button = QPushButton("×")
        close_button.setObjectName("iconButton")
        close_button.setFixedSize(24, 24)
        close_button.setAccessibleName('Закрыть диалог профиля')
        close_button.clicked.connect(self.reject)
        header.addWidget(badge)
        header.addWidget(title, 1)
        header.addWidget(close_button)
        layout.addLayout(header)

        protocol_label = QLabel("Протокол")
        protocol_label.setObjectName("fieldLabel")
        layout.addWidget(protocol_label)
        protocol_row = QHBoxLayout()
        protocol_row.setSpacing(8)
        self.protocol_group = QButtonGroup(self)
        self.protocol_buttons = {}
        for protocol, title, available in (
            ('vless', 'VLESS', True), ('shadowsocks', 'SHADOWSOCKS', True),
            ('wireguard', 'WIREGUARD', False), ('trojan', 'TROJAN', False), ('vmess', 'VMESS', False),
        ):
            button = QPushButton(title)
            button.setObjectName('protocolPill')
            button.setCheckable(True)
            button.setEnabled(available)
            if available:
                hint = 'Доступен. При вводе ссылки протокол определяется автоматически.'
            elif protocol == 'wireguard':
                hint = 'Добавление конфигурации WireGuard в этом диалоге пока недоступно.'
            else:
                hint = 'Этот протокол пока не поддерживается.'
            button.setToolTip(hint)
            button.setAccessibleName(title)
            button.setAccessibleDescription(hint)
            self.protocol_group.addButton(button)
            self.protocol_buttons[protocol] = button
            protocol_row.addWidget(button)
        self.protocol_buttons['vless'].setChecked(True)
        layout.addLayout(protocol_row)

        link_label = QLabel("Вставьте ссылку подключения")
        link_label.setObjectName("fieldLabel")
        layout.addWidget(link_label)

        link_frame = QFrame()
        link_frame.setObjectName("inputShell")
        link_layout = QHBoxLayout(link_frame)
        link_layout.setContentsMargins(0, 0, 6, 0)
        link_layout.setSpacing(8)
        self.link_edit = QLineEdit()
        self.link_edit.setObjectName("flatLineEdit")
        self.link_edit.setPlaceholderText("vless://… или ss://…")
        self.link_edit.setAccessibleName('Ссылка подключения')
        link_label.setBuddy(self.link_edit)
        self.link_frame = link_frame
        paste_button = QPushButton("⧉")
        paste_button.setObjectName("pasteButton")
        paste_button.setFixedSize(30, 30)
        paste_button.setToolTip('Вставить ссылку из буфера обмена')
        paste_button.setAccessibleName('Вставить ссылку из буфера обмена')
        paste_button.clicked.connect(self.paste_link)
        link_layout.addWidget(self.link_edit, 1)
        link_layout.addWidget(paste_button)
        layout.addWidget(link_frame)

        self.summary = QLabel('')
        self.summary.setObjectName('profileSummary')
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        self.summary.hide()
        layout.addWidget(self.summary)

        name_label = QLabel("Название профиля")
        name_label.setObjectName("fieldLabel")
        layout.addWidget(name_label)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("HomeServer")
        self.name_edit.setAccessibleName('Название профиля')
        name_label.setBuddy(self.name_edit)
        layout.addWidget(self.name_edit)

        country_label = QLabel("Страна подключения")
        country_label.setObjectName("fieldLabel")
        layout.addWidget(country_label)
        self.country_combo = QComboBox()
        self.country_combo.setAccessibleName('Страна подключения')
        country_label.setBuddy(self.country_combo)
        for label, code in self.country_options:
            self.country_combo.addItem(label, code)
        layout.addWidget(self.country_combo)

        actions = QHBoxLayout()
        actions.setSpacing(12)
        actions.addStretch(1)
        cancel_button = QPushButton("Отмена")
        cancel_button.setObjectName("ghostButton")
        submit_button = QPushButton("Сохранить" if profile else "Добавить")
        submit_button.setObjectName("primaryButton")
        cancel_button.clicked.connect(self.reject)
        submit_button.clicked.connect(self.accept)
        actions.addWidget(cancel_button)
        actions.addWidget(submit_button)
        layout.addLayout(actions)

        self.validation_timer = QTimer(self)
        self.validation_timer.setSingleShot(True)
        self.validation_timer.setInterval(300)
        self.validation_timer.timeout.connect(lambda: self.validate_link(show_success=False))
        self.link_edit.textChanged.connect(self._link_changed)

        if profile:
            self.name_edit.setText(profile.name)
            self.link_edit.setText(profile.link)
            self._set_country(profile.country_code or self._guess_country(profile.name, profile.remark, profile.server))
            self.validate_link(show_success=False)
        self.link_edit.setFocus()

    def _link_changed(self) -> None:
        self.parsed = None
        self._select_detected_protocol(None)
        self.summary.clear()
        self.summary.hide()
        self._set_link_error(False)
        if self.link_edit.text().strip():
            self.validation_timer.start()
        else:
            self.validation_timer.stop()

    def _select_detected_protocol(self, protocol: str | None) -> None:
        self.protocol_group.setExclusive(False)
        for key, button in self.protocol_buttons.items():
            button.setChecked(key == protocol)
        self.protocol_group.setExclusive(True)

    def _set_link_error(self, invalid: bool) -> None:
        self.link_frame.setProperty('invalid', 'true' if invalid else 'false')
        self.link_frame.style().unpolish(self.link_frame)
        self.link_frame.style().polish(self.link_frame)

    def paste_link(self) -> None:
        self.link_edit.setText(QApplication.clipboard().text().strip())

    def _set_country(self, code: str) -> None:
        index = self.country_combo.findData(normalize_country_code(code))
        self.country_combo.setCurrentIndex(index if index >= 0 else 0)

    def _guess_country(self, *parts: str) -> str:
        return guess_country_code(*parts)

    def validate_link(self, show_success: bool = True) -> bool:
        self.validation_timer.stop()
        link = self.link_edit.text().strip()
        self.parsed = None
        try:
            self.parsed = parse_connection(link)
        except Exception as exc:
            self._select_detected_protocol(None)
            if not link:
                reason = 'Вставьте ссылку подключения.'
            elif str(exc) == 'Unsupported connection profile format':
                reason = 'Формат не распознан. Используйте полную ссылку vless://… или ss://….'
            else:
                reason = 'Проверьте полную ссылку подключения: ' + sanitize_connection_error(str(exc))
            self.summary.setText(reason)
            self.summary.show()
            self._set_link_error(True)
            return False

        self._set_link_error(False)
        self._select_detected_protocol(self.parsed.protocol)
        remark = self.parsed.remark or "без описания"
        summary = [
            f"Протокол: {self.parsed.protocol_label}",
            f"Сервер: {self.parsed.server}:{self.parsed.port or '-'}",
        ]
        server_name = self.parsed.data.get("server_name")
        if server_name:
            summary.append(f"SNI: {server_name}")
        summary.append(f"Описание: {remark}")
        self.summary.setText("\n".join(summary))
        self.summary.show()
        guessed_country = self._guess_country(self.name_edit.text(), remark, self.parsed.server)
        if guessed_country and not self.country_combo.currentData():
            self._set_country(guessed_country)
        if show_success:
            QMessageBox.information(self, "Профиль", "Профиль выглядит корректным.")
        return True
    def accept(self) -> None:
        if not self.validate_link(show_success=False):
            self.link_edit.setFocus()
            return

        name = self.name_edit.text().strip()
        if not name:
            name = self.parsed.remark or self.parsed.server or "Connection"
        self.name_edit.setText(name)
        super().accept()

    def build_profile(self) -> ConnectionProfile:
        parsed = self.parsed or parse_connection(self.link_edit.text().strip())
        if self.profile:
            profile = self.profile
            profile.name = self.name_edit.text().strip()
            profile.link = self.link_edit.text().strip()
            profile.remark = parsed.remark or ""
            profile.server = parsed.server or ""
            profile.protocol = parsed.protocol
            profile.country_code = normalize_country_code(str(self.country_combo.currentData() or ""))
            return profile
        return ConnectionProfile.create(
            name=self.name_edit.text().strip(),
            link=self.link_edit.text().strip(),
            remark=parsed.remark or "",
            server=parsed.server or "",
            country_code=normalize_country_code(str(self.country_combo.currentData() or "")),
            protocol=parsed.protocol,
        )
class LaunchSitesDialog(QDialog):
    def __init__(self, parent=None, sites: list[str] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ресурсы для запуска")
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(440)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        panel = QFrame()
        panel.setObjectName("profileDialogPanel")
        root.addWidget(panel)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 24, 24, 22)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(12)
        badge = QLabel("+")
        badge.setObjectName("dialogBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Ресурсы запуска")
        title.setObjectName("dialogTitle")
        close_button = QPushButton("×")
        close_button.setObjectName("iconButton")
        close_button.setFixedSize(24, 24)
        close_button.setAccessibleName('Закрыть диалог ресурсов')
        close_button.clicked.connect(self.reject)
        header.addWidget(badge)
        header.addWidget(title, 1)
        header.addWidget(close_button)
        layout.addLayout(header)

        list_label = QLabel("Добавленные ресурсы")
        list_label.setObjectName("fieldLabel")
        layout.addWidget(list_label)

        self.site_list = QListWidget()
        self.site_list.setObjectName("launchSiteList")
        self.site_list.setMinimumHeight(150)
        layout.addWidget(self.site_list)

        edit_label = QLabel("Ссылка")
        edit_label.setObjectName("fieldLabel")
        layout.addWidget(edit_label)
        self.site_edit = QLineEdit()
        self.site_edit.setAccessibleName('Ссылка ресурса')
        edit_label.setBuddy(self.site_edit)
        self.site_edit.setPlaceholderText("example.com")
        layout.addWidget(self.site_edit)

        edit_actions = QHBoxLayout()
        edit_actions.setSpacing(10)
        add_button = QPushButton("Добавить")
        add_button.setObjectName("successButton")
        save_button = QPushButton("Сохранить ссылку")
        save_button.setObjectName("outlineButton")
        delete_button = QPushButton("Удалить")
        delete_button.setObjectName("dangerButton")
        add_button.clicked.connect(self.add_site)
        save_button.clicked.connect(self.update_site)
        delete_button.clicked.connect(self.delete_site)
        edit_actions.addWidget(add_button)
        edit_actions.addWidget(save_button)
        edit_actions.addWidget(delete_button)
        layout.addLayout(edit_actions)

        save_hint = QLabel('«Готово» сохранит изменения текущей ссылки.')
        save_hint.setObjectName('mutedLabel')
        save_hint.setWordWrap(True)
        layout.addWidget(save_hint)

        actions = QHBoxLayout()
        actions.setSpacing(12)
        actions.addStretch(1)
        cancel_button = QPushButton("Отмена")
        cancel_button.setObjectName("ghostButton")
        submit_button = QPushButton("Готово")
        submit_button.setObjectName("primaryButton")
        cancel_button.clicked.connect(self.reject)
        submit_button.clicked.connect(self.accept)
        actions.addWidget(cancel_button)
        actions.addWidget(submit_button)
        layout.addLayout(actions)

        for site in self._dedupe_sites(sites or ["example.com"]):
            self.site_list.addItem(site)
        self._editing_item = None
        self.site_list.currentRowChanged.connect(self._load_selected_site)
        if self.site_list.count() > 0:
            self.site_list.setCurrentRow(0)

    def _dedupe_sites(self, sites: list[str]) -> list[str]:
        cleaned = []
        for item in sites:
            site = str(item).strip()
            if site and site not in cleaned:
                cleaned.append(site)
        return cleaned or ["example.com"]

    def _sites(self) -> list[str]:
        return [self.site_list.item(index).text() for index in range(self.site_list.count())]

    def _load_selected_site(self, row: int) -> None:
        item = self.site_list.item(row)
        previous = self._editing_item
        if previous is not None and previous is not item and not self._apply_site_edit(previous):
            with QSignalBlocker(self.site_list):
                self.site_list.setCurrentItem(previous)
            return
        self._editing_item = item
        self.site_edit.setText(item.text() if item else "")

    def _select_site(self, row: int) -> None:
        with QSignalBlocker(self.site_list):
            self.site_list.setCurrentRow(row)
        self._editing_item = self.site_list.item(row)
        self.site_edit.setText(self._editing_item.text() if self._editing_item else '')

    def _apply_site_edit(self, item) -> bool:
        site = self._edited_site()
        if not site:
            QMessageBox.warning(self, 'Ресурсы', 'Введите ссылку ресурса или нажмите «Отмена».')
            self.site_edit.setFocus()
            return False
        if any(self.site_list.item(index) is not item and self.site_list.item(index).text() == site
               for index in range(self.site_list.count())):
            QMessageBox.warning(self, 'Ресурсы', 'Такая ссылка уже есть в списке.')
            self.site_edit.setFocus()
            return False
        item.setText(site)
        return True

    def _edited_site(self) -> str:
        return self.site_edit.text().strip()

    def add_site(self) -> None:
        site = self._edited_site()
        if not site:
            QMessageBox.warning(self, "Ресурсы", "Введите ссылку ресурса.")
            return
        sites = self._sites()
        if site in sites:
            self._select_site(sites.index(site))
            return
        self.site_list.addItem(site)
        self._select_site(self.site_list.count() - 1)

    def update_site(self) -> None:
        if self._editing_item is not None:
            self._apply_site_edit(self._editing_item)

    def delete_site(self) -> None:
        row = self.site_list.currentRow()
        if row < 0:
            return
        if self.site_list.count() == 1:
            QMessageBox.warning(self, "Ресурсы", "Оставьте хотя бы один ресурс в списке.")
            return
        with QSignalBlocker(self.site_list):
            item = self.site_list.takeItem(row)
        self._editing_item = None
        del item
        self._select_site(min(row, self.site_list.count() - 1))

    def accept(self) -> None:
        if not self._sites():
            QMessageBox.warning(self, "Ресурсы", "Добавьте хотя бы один ресурс.")
            return
        if self._editing_item is not None and not self._apply_site_edit(self._editing_item):
            return
        super().accept()

    def build_sites(self) -> list[str]:
        return self._sites()









