from __future__ import annotations

from PySide6.QtCore import Qt
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

from outward_app.core.connections import ParsedConnection, parse_connection
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
        self.country_options = [("Auto / Unknown", "")] + [(f"{code} {name}", code) for code, name in country_options()]

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
        protocol_widths = {"SHADOWSOCKS": 88, "WIREGUARD": 78}
        for text, enabled in (("VLESS", True), ("SHADOWSOCKS", True), ("WIREGUARD", False), ("TROJAN", False), ("VMESS", False)):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setObjectName("protocolPill")
            button.setEnabled(enabled)
            button.setMinimumWidth(protocol_widths.get(text, 58))
            if text == "VLESS":
                button.setChecked(True)
            self.protocol_group.addButton(button)
            protocol_row.addWidget(button)
        protocol_row.addStretch(1)
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
        self.link_edit.setPlaceholderText("vless://... or ss://...")
        paste_button = QPushButton("⧉")
        paste_button.setObjectName("pasteButton")
        paste_button.setFixedSize(30, 30)
        paste_button.clicked.connect(self.paste_link)
        link_layout.addWidget(self.link_edit, 1)
        link_layout.addWidget(paste_button)
        layout.addWidget(link_frame)

        name_label = QLabel("Название профиля")
        name_label.setObjectName("fieldLabel")
        layout.addWidget(name_label)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("HomeServer")
        layout.addWidget(self.name_edit)

        country_label = QLabel("Страна подключения")
        country_label.setObjectName("fieldLabel")
        layout.addWidget(country_label)
        self.country_combo = QComboBox()
        for label, code in self.country_options:
            self.country_combo.addItem(label, code)
        layout.addWidget(self.country_combo)

        self.summary = QLabel("")
        self.summary.setObjectName("profileSummary")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

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

        if profile:
            self.name_edit.setText(profile.name)
            self.link_edit.setText(profile.link)
            self._set_country(profile.country_code or self._guess_country(profile.name, profile.remark, profile.server))
            self.validate_link(show_success=False)

    def paste_link(self) -> None:
        self.link_edit.setText(QApplication.clipboard().text().strip())

    def _set_country(self, code: str) -> None:
        index = self.country_combo.findData(normalize_country_code(code))
        self.country_combo.setCurrentIndex(index if index >= 0 else 0)

    def _guess_country(self, *parts: str) -> str:
        return guess_country_code(*parts)

    def validate_link(self, show_success: bool = True) -> bool:
        link = self.link_edit.text().strip()
        try:
            self.parsed = parse_connection(link)
        except Exception as exc:
            self.summary.setText(f"Ошибка: {exc}")
            if show_success:
                QMessageBox.warning(self, "Профиль", str(exc))
            return False

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
        guessed_country = self._guess_country(self.name_edit.text(), remark, self.parsed.server)
        if guessed_country and not self.country_combo.currentData():
            self._set_country(guessed_country)
        if show_success:
            QMessageBox.information(self, "Профиль", "Профиль выглядит корректным.")
        return True
    def accept(self) -> None:
        if not self.validate_link(show_success=False):
            QMessageBox.warning(self, "Профиль", "Сначала исправьте профиль подключения.")
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
        self.site_edit.setText(item.text() if item else "")

    def _edited_site(self) -> str:
        return self.site_edit.text().strip()

    def add_site(self) -> None:
        site = self._edited_site()
        if not site:
            QMessageBox.warning(self, "Ресурсы", "Введите ссылку ресурса.")
            return
        sites = self._sites()
        if site in sites:
            self.site_list.setCurrentRow(sites.index(site))
            return
        self.site_list.addItem(site)
        self.site_list.setCurrentRow(self.site_list.count() - 1)

    def update_site(self) -> None:
        row = self.site_list.currentRow()
        site = self._edited_site()
        if row < 0 or not site:
            QMessageBox.warning(self, "Ресурсы", "Выберите ресурс и укажите ссылку.")
            return
        sites = self._sites()
        if site in sites and sites.index(site) != row:
            QMessageBox.warning(self, "Ресурсы", "Такая ссылка уже есть в списке.")
            return
        self.site_list.item(row).setText(site)

    def delete_site(self) -> None:
        row = self.site_list.currentRow()
        if row < 0:
            return
        if self.site_list.count() == 1:
            QMessageBox.warning(self, "Ресурсы", "Оставьте хотя бы один ресурс в списке.")
            return
        item = self.site_list.takeItem(row)
        del item
        self.site_list.setCurrentRow(min(row, self.site_list.count() - 1))

    def accept(self) -> None:
        if not self._sites():
            QMessageBox.warning(self, "Ресурсы", "Добавьте хотя бы один ресурс.")
            return
        super().accept()

    def build_sites(self) -> list[str]:
        return self._sites()









