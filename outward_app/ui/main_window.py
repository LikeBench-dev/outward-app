from __future__ import annotations
import ctypes
import socket
from pathlib import Path
import re
import subprocess
from datetime import datetime, timezone
from time import perf_counter
from html import escape
from PySide6.QtCore import QObject, QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QComboBox, QCompleter, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton, QTextEdit, QScrollArea, QSpinBox, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget
from outward_app.app_info import APP_NAME
from outward_app.core.autostart import set_launch_on_startup
from outward_app.core.browser import open_url_with_proxy
from outward_app.core.connections import parse_connection, protocol_label_for_link, sanitize_connection_error
from outward_app.core.countries import guess_country_code, normalize_country_code
from outward_app.core.models import AppSettings, ConnectionProfile, RuntimeState
from outward_app.core.singbox import SingBoxManager, append_log_entry, build_sing_box_config, choose_proxy_ports, find_sing_box, stop_managed_sing_box_processes, tail_log, write_config
from outward_app.core.storage import JsonStore
from outward_app.core.updater import UpdateCheckResult, UpdateManager, UpdateRelease
from outward_app.paths import asset_path
from outward_app.ui.dialogs import LaunchSitesDialog, ProfileDialog
from outward_app.version import get_app_version

try:
    from qfluentwidgets import ComboBox as FluentComboBox
except ImportError:
    FluentComboBox = None

class SwitchControl(QWidget):
    toggled = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._checked = False
        self.setFixedSize(44, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        checked = bool(checked)
        if self._checked == checked:
            return
        self._checked = checked
        self.update()
        self.toggled.emit(checked)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.setChecked(not self._checked)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(2, 2, 40, 20)
        if self._checked:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor('#9B59FF'))
            painter.drawRoundedRect(track, 10, 10)
            painter.setBrush(QColor('#ffffff'))
            painter.drawEllipse(QRectF(24, 4, 16, 16))
        else:
            painter.setPen(QPen(QColor('#64748B'), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(track, 10, 10)
            painter.setPen(QPen(QColor('#94A3B8'), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(9, 8, 8, 8))

class LoadingButton(QPushButton):
    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, parent)
        self._loading = False
        self._loading_angle = 0
        self._idle_text = text
        self._idle_icon = QIcon()
        self._idle_icon_size = self.iconSize()
        self._loading_timer = QTimer(self)
        self._loading_timer.setInterval(80)
        self._loading_timer.timeout.connect(self._advance_loading_icon)

    def set_loading(self, loading: bool, text: str | None = None) -> None:
        loading = bool(loading)
        if loading:
            if not self._loading:
                self._idle_text = self.text()
                self._idle_icon = self.icon()
                self._idle_icon_size = self.iconSize()
            self._loading = True
            self._loading_angle = 0
            if text is not None:
                self.setText(text)
            self.setIconSize(QSize(16, 16))
            self.setEnabled(False)
            self._advance_loading_icon()
            self._loading_timer.start()
            return

        if not self._loading:
            return
        self._loading_timer.stop()
        self._loading = False
        self.setText(self._idle_text)
        self.setIcon(self._idle_icon)
        self.setIconSize(self._idle_icon_size)

    def _advance_loading_icon(self) -> None:
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor('#ffffff') if self.objectName() == 'primaryButton' else QColor('#C4B5FD')
        pen = QPen(color, 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(QRectF(3, 3, 10, 10), self._loading_angle * 16, -270 * 16)
        painter.end()
        self.setIcon(QIcon(pixmap))
        self._loading_angle = (self._loading_angle - 30) % 360

class ConnectWorker(QObject):
    connected = Signal(object)
    failed = Signal(str)
    message = Signal(str)
    finished = Signal()

    def __init__(self, profile: ConnectionProfile, settings: AppSettings, manager: SingBoxManager, store: JsonStore) -> None:
        super().__init__()
        self.profile = profile
        self.settings = settings
        self.manager = manager
        self.store = store

    def run(self) -> None:
        try:
            self.message.emit('Проверяем профиль подключения...')
            connection = parse_connection(self.profile.link)
            if self.manager.is_running():
                self.message.emit('Останавливаем текущее подключение...')
                self.manager.stop()
            if self.settings.stop_existing_sing_box:
                stopped_pids, errors = stop_managed_sing_box_processes()
                if stopped_pids:
                    self.message.emit(f"Остановлены старые сеансы: {', '.join(stopped_pids)}")
                if errors:
                    raise RuntimeError('\n'.join(errors))
            http_port, socks_port = choose_proxy_ports(self.settings.http_port, self.settings.socks_port)
            if (http_port, socks_port) != (self.settings.http_port, self.settings.socks_port):
                port_message = (
                    f'Настроенные порты {self.settings.http_port}/{self.settings.socks_port} недоступны. '
                    f'Используем ближайшие свободные: HTTP {http_port}, SOCKS5 {socks_port}.'
                )
                self.message.emit(port_message)
                append_log_entry(port_message, 'INFO')
            else:
                self.message.emit(f'HTTP {http_port}, SOCKS5 {socks_port} готовы к запуску.')
            config = build_sing_box_config(connection, http_port, socks_port, self.settings.custom_dns)
            write_config(config)
            sing_box = find_sing_box()
            self.message.emit('Проверяем конфигурацию sing-box...')
            self.manager.check_config(sing_box)
            self.message.emit('Запускаем sing-box...')
            self.manager.start(sing_box)
            self.manager.wait_for_ports([http_port, socks_port])
            http_proxy_url = f'http://127.0.0.1:{http_port}'
            socks_proxy_url = f'socks5://127.0.0.1:{socks_port}'
            state = RuntimeState(profile_id=self.profile.id, profile_name=self.profile.name, http_port=http_port, socks_port=socks_port, http_proxy_url=http_proxy_url, socks_proxy_url=socks_proxy_url, server=connection.server, server_port=connection.port, protocol=connection.protocol, protocol_label=connection.protocol_label)
            self.store.mark_used(self.profile.id)
            if self.settings.auto_open_browser:
                opened_with_proxy = open_url_with_proxy(
                    socks_port,
                    self.settings.preferred_browser,
                    self.settings.launch_url,
                    self.settings.disable_browser_extensions,
                )
                if opened_with_proxy:
                    self.message.emit('Браузер открыт через proxy-профиль.')
                else:
                    self.message.emit('Открыт браузер по умолчанию. Proxy-настройки могут потребовать проверки.')
            self.connected.emit(state)
        except Exception as exc:
            self.failed.emit(sanitize_connection_error(str(exc)))
        finally:
            self.finished.emit()

class PingWorker(QObject):
    measured = Signal(int)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, host: str, port: int, timeout: float = 2.5) -> None:
        super().__init__()
        self.host = host
        self.port = int(port)
        self.timeout = timeout

    def run(self) -> None:
        started_at = perf_counter()
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout):
                elapsed_ms = max(1, round((perf_counter() - started_at) * 1000))
                self.measured.emit(elapsed_ms)
        except OSError as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()

class DisconnectWorker(QObject):
    failed = Signal(str)
    finished = Signal()

    def __init__(self, manager: SingBoxManager) -> None:
        super().__init__()
        self.manager = manager

    def run(self) -> None:
        try:
            self.manager.stop()
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()

class UpdateCheckWorker(QObject):
    checked = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, manager: UpdateManager) -> None:
        super().__init__()
        self.manager = manager

    def run(self) -> None:
        try:
            self.checked.emit(self.manager.check_for_update())
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()

class UpdateDownloadWorker(QObject):
    progress = Signal(int, int)
    downloaded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, manager: UpdateManager, release: UpdateRelease) -> None:
        super().__init__()
        self.manager = manager
        self.release = release

    def run(self) -> None:
        try:
            path = self.manager.download_update(self.release, self.progress.emit)
            self.downloaded.emit(path)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()

class MainWindow(QMainWindow):

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f'{APP_NAME} - Настройки')
        self.setMinimumSize(900, 560)
        self.store = JsonStore()
        self.settings = self.store.load_settings()
        self.manager = SingBoxManager()
        self.profiles: list[ConnectionProfile] = []
        self.runtime_state: RuntimeState | None = None
        self.connect_thread: QThread | None = None
        self.connect_worker: ConnectWorker | None = None
        self.disconnect_thread: QThread | None = None
        self.disconnect_worker: DisconnectWorker | None = None
        self.disconnect_error: str | None = None
        self.ping_thread: QThread | None = None
        self.ping_worker: PingWorker | None = None
        self.update_check_thread: QThread | None = None
        self.update_check_worker: UpdateCheckWorker | None = None
        self.update_download_thread: QThread | None = None
        self.update_download_worker: UpdateDownloadWorker | None = None
        self.update_manager = UpdateManager(get_app_version())
        self.available_update: UpdateRelease | None = None
        self.downloaded_update_installer: Path | None = None
        self.tray_icon: QSystemTrayIcon | None = None
        self.force_quit = False
        self.dark_title_applied = False
        self._last_log_text = ''
        self._build_ui()
        self._create_tray_icon()
        self._load_profiles()
        self._load_settings_to_ui()
        self._set_connected(False)
        self.log_timer = QTimer(self)
        self.log_timer.setInterval(1500)
        self.log_timer.timeout.connect(self.refresh_log)
        self.log_timer.start()
        self.session_timer = QTimer(self)
        self.session_timer.setInterval(1000)
        self.session_timer.timeout.connect(self._update_session_time)
        self.session_timer.start()
        self.ping_timer = QTimer(self)
        self.ping_timer.setInterval(10000)
        self.ping_timer.timeout.connect(self._request_ping_update)
        self.refresh_log()
        QTimer.singleShot(1200, self._check_updates_on_startup)
        QTimer.singleShot(1700, self._connect_on_startup)

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName('appRoot')
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        sidebar = QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(218)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(12, 16, 10, 12)
        side_layout.setSpacing(16)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        logo = QLabel()
        logo.setObjectName('sidebarLogo')
        pixmap = QPixmap(str(asset_path('outward.png')))
        if not pixmap.isNull():
            logo.setPixmap(pixmap.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFixedSize(32, 32)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        title = QLabel(APP_NAME)
        title.setObjectName('brandTitle')
        subtitle = QLabel('FLUENT PROXY')
        subtitle.setObjectName('brandSubtitle')
        brand_text.addWidget(title)
        brand_text.addWidget(subtitle)
        brand_row.addWidget(logo)
        brand_row.addLayout(brand_text, 1)
        side_layout.addLayout(brand_row)

        profile_title = QLabel('ПРОФИЛИ ПОДКЛЮЧЕНИЯ')
        profile_title.setObjectName('sectionTitle')
        side_layout.addWidget(profile_title)

        self.profile_list = QListWidget()
        self.profile_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.profile_list.customContextMenuRequested.connect(self._show_profile_context_menu)
        self.profile_list.currentItemChanged.connect(self._sync_profile_buttons)
        self.profile_list.itemDoubleClicked.connect(lambda _item: self.connect_profile())
        side_layout.addWidget(self.profile_list, 1)

        self.edit_button = QPushButton('Изменить', sidebar)
        self.delete_button = QPushButton('Удалить', sidebar)
        self.edit_button.hide()
        self.delete_button.hide()
        self.edit_button.clicked.connect(self.edit_profile)
        self.delete_button.clicked.connect(self.delete_profile)

        self.add_button = QPushButton('+  Новый профиль')
        self.add_button.setObjectName('sideAddButton')
        self.add_button.clicked.connect(self.add_profile)
        side_layout.addWidget(self.add_button)
        root.addWidget(sidebar)

        scroll = QScrollArea()
        scroll.setObjectName('contentScroll')
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        root.addWidget(scroll, 1)

        body = QWidget()
        body.setObjectName('content')
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(25, 24, 25, 20)
        body_layout.setSpacing(18)
        scroll.setWidget(body)

        status_panel = QFrame()
        status_panel.setObjectName('statusPanel')
        status_layout = QGridLayout(status_panel)
        status_layout.setContentsMargins(16, 14, 16, 14)
        status_layout.setHorizontalSpacing(14)
        status_layout.setVerticalSpacing(4)

        self.hero_logo = QLabel()
        self.hero_logo.setObjectName('heroLogo')
        if not pixmap.isNull():
            self.hero_logo.setPixmap(pixmap.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.hero_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero_logo.setFixedSize(48, 48)
        status_layout.addWidget(self.hero_logo, 0, 0, 2, 1)

        status_title_row = QHBoxLayout()
        status_title_row.setSpacing(7)
        self.status_dot = QLabel('●')
        self.status_dot.setObjectName('statusDot')
        self.status_title_label = QLabel('Подключение остановлено')
        self.status_title_label.setObjectName('statusTitle')
        status_title_row.addWidget(self.status_dot)
        status_title_row.addWidget(self.status_title_label)
        status_title_row.addStretch(1)
        status_layout.addLayout(status_title_row, 0, 1)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(22)
        self.status_caption_label = QLabel('')
        self.status_caption_label.setObjectName('mutedLabel')
        self.status_caption_label.hide()
        self.status_profile_value = self._make_status_metric(stats_row, 'Профиль:', '-')
        self.session_value = self._make_status_metric(stats_row, 'Сессия:', '00:00:00')
        self.latency_value = self._make_status_metric(stats_row, 'Ping:', '-')
        stats_row.addStretch(1)
        status_layout.addLayout(stats_row, 1, 1)

        status_actions = QHBoxLayout()
        status_actions.setSpacing(10)
        self.connect_button = LoadingButton('Подключить')
        self.connect_button.setObjectName('primaryButton')
        self.connect_button.setFixedWidth(156)
        self.disconnect_button = LoadingButton('Отключить')
        self.disconnect_button.setFixedWidth(150)
        self.disconnect_button.setObjectName('ghostButton')
        self.connect_button.clicked.connect(self.connect_profile)
        self.disconnect_button.clicked.connect(self.disconnect_profile)
        status_actions.addWidget(self.connect_button)
        status_actions.addWidget(self.disconnect_button)
        status_layout.addLayout(status_actions, 0, 2, 2, 1)
        status_layout.setColumnStretch(1, 1)
        body_layout.addWidget(status_panel)

        self.connection_tools = QFrame()
        self.connection_tools.setObjectName('connectionTools')
        connection_layout = QVBoxLayout(self.connection_tools)
        connection_layout.setContentsMargins(0, 0, 0, 0)
        connection_layout.setSpacing(14)

        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(14)
        http_card, self.http_port_label = self._metric_card('HTTP прокси порт', '-')
        socks_card, self.socks_port_label = self._metric_card('SOCKS5 прокси порт', '-')
        protocol_card, self.protocol_label = self._metric_card('Протокол туннелирования', 'VLESS')
        metrics_row.addWidget(http_card)
        metrics_row.addWidget(socks_card)
        metrics_row.addWidget(protocol_card)
        connection_layout.addLayout(metrics_row)

        launch_row = QHBoxLayout()
        launch_row.setSpacing(12)
        self.open_browser_button = QPushButton('Открыть браузер')
        self.open_browser_button.setObjectName('primaryButton')
        self.open_browser_button.clicked.connect(self.open_browser)
        self.open_browser_button.setFixedWidth(148)
        launch_target = QFrame()
        launch_target.setObjectName('launchTarget')
        launch_target_layout = QHBoxLayout(launch_target)
        launch_target_layout.setContentsMargins(12, 0, 10, 0)
        launch_target_layout.setSpacing(8)
        self.launch_favicon = QLabel()
        self.launch_favicon.setObjectName('launchFavicon')
        self.launch_favicon.setFixedSize(18, 18)
        self.launch_url_combo = self._make_combo_box()
        self.launch_url_combo.setObjectName('launchCombo')
        set_launch_editable = getattr(self.launch_url_combo, 'setEditable', None)
        if set_launch_editable is not None:
            set_launch_editable(False)
        self.launch_url_combo.currentTextChanged.connect(self._remember_launch_url)
        launch_hint = QLabel('Открыть после запуска')
        launch_hint.setObjectName('launchHint')
        launch_target_layout.addWidget(self.launch_favicon)
        launch_target_layout.addWidget(self.launch_url_combo, 1)
        launch_target_layout.addWidget(launch_hint)
        self.launch_auto_open_check = self._make_switch()
        self.launch_auto_open_check.hide()
        self._connect_switch(self.launch_auto_open_check, self._remember_auto_open_from_launch)
        self.launch_sites_button = QPushButton('+')
        self.launch_sites_button.setObjectName('launchManageButton')
        self.launch_sites_button.setFixedSize(34, 34)
        self.launch_sites_button.clicked.connect(self.manage_launch_sites)
        launch_row.addWidget(self.open_browser_button, 0)
        launch_row.addWidget(launch_target, 1)
        launch_row.addWidget(self.launch_sites_button, 0)
        connection_layout.addLayout(launch_row)

        pivot = QFrame()
        pivot.setObjectName('pivotTabs')
        pivot_layout = QHBoxLayout(pivot)
        pivot_layout.setContentsMargins(0, 0, 0, 0)
        pivot_layout.setSpacing(18)
        self.log_tab_button = QPushButton('Лог консоли')
        self.log_tab_button.setObjectName('pivotTab')
        self.log_tab_button.setCheckable(True)
        self.settings_tab_button = QPushButton('Настройки клиента')
        self.settings_tab_button.setObjectName('pivotTab')
        self.settings_tab_button.setCheckable(True)
        self.update_tab_button = QPushButton('Обновление')
        self.update_tab_button.setObjectName('pivotTab')
        self.update_tab_button.setCheckable(True)
        self.log_tab_button.clicked.connect(lambda: self._set_tab_index(0))
        self.settings_tab_button.clicked.connect(lambda: self._set_tab_index(1))
        self.update_tab_button.clicked.connect(lambda: self._set_tab_index(2))
        pivot_layout.addWidget(self.log_tab_button)
        pivot_layout.addWidget(self.settings_tab_button)
        pivot_layout.addWidget(self.update_tab_button)
        pivot_layout.addStretch(1)
        body_layout.addWidget(pivot)

        self.tabs = QStackedWidget()
        self.tabs.setObjectName('contentStack')
        self.log_tab_page = QWidget()
        self.log_tab_page.setObjectName('logsTabPage')
        log_tab_layout = QVBoxLayout(self.log_tab_page)
        log_tab_layout.setContentsMargins(0, 4, 0, 0)
        log_tab_layout.setSpacing(14)
        log_tab_layout.addWidget(self.connection_tools)
        self.log_view = QTextEdit()
        self.log_view.setObjectName('logConsole')
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(392)
        self.log_view.setPlaceholderText('Лог sing-box появится здесь после запуска.')
        log_tab_layout.addWidget(self.log_view)
        self.tabs.addWidget(self.log_tab_page)
        self.tabs.addWidget(self._build_settings_tab())
        self.tabs.addWidget(self._build_update_tab())
        body_layout.addWidget(self.tabs, 1)

        self.footer_label = QLabel(f'{APP_NAME} v{get_app_version()} · Windows 11 x64')
        self.footer_label.setObjectName('footerLabel')
        body_layout.addWidget(self.footer_label)
        self._set_tab_index(1)
    def _make_switch(self) -> QWidget:
        return SwitchControl()

    def _make_combo_box(self) -> QComboBox:
        if FluentComboBox is not None:
            return FluentComboBox()
        return QComboBox()

    def _connect_switch(self, switch: QWidget, slot) -> None:
        signal = getattr(switch, 'toggled', None)
        if signal is not None:
            signal.connect(slot)
            return
        signal = getattr(switch, 'checkedChanged', None)
        if signal is not None:
            signal.connect(slot)
            return
        switch.stateChanged.connect(slot)

    def _set_tab_index(self, index: int) -> None:
        self.tabs.setCurrentIndex(index)
        for button, selected in (
            (self.log_tab_button, index == 0),
            (self.settings_tab_button, index == 1),
            (self.update_tab_button, index == 2),
        ):
            button.setChecked(selected)
            button.setProperty('selected', 'true' if selected else 'false')
            button.style().unpolish(button)
            button.style().polish(button)

    def _sync_connection_controls_visibility(self, *_args) -> None:
        return

    def _set_launch_favicon(self, text: str) -> None:
        colors = {
            'example.com': '#5865f2',
        }
        color = colors.get(text.strip().lower(), '#5865f2')
        self.launch_favicon.setStyleSheet(f'background: {color}; border-radius: 9px;')

    def _launch_sites(self) -> list[str]:
        sites = []
        for index in range(self.launch_url_combo.count()):
            site = self.launch_url_combo.itemText(index).strip()
            if site and site not in sites:
                sites.append(site)
        return sites or ['example.com']

    def _current_launch_url(self) -> str:
        return self.launch_url_combo.currentText().strip() or 'example.com'

    def _sync_launch_sites_combo(self, selected: str | None = None) -> None:
        sites = []
        for site in self.settings.launch_sites:
            value = str(site).strip()
            if value and value not in sites:
                sites.append(value)
        selected = (selected or self.settings.launch_url or '').strip() or 'example.com'
        if selected not in sites:
            sites.insert(0, selected)
        self.launch_url_combo.blockSignals(True)
        self.launch_url_combo.clear()
        self.launch_url_combo.addItems(sites)
        self.launch_url_combo.setCurrentIndex(max(0, self.launch_url_combo.findText(selected)))
        self.launch_url_combo.blockSignals(False)
        self.settings.launch_sites = sites
        self.settings.launch_url = self._current_launch_url()
        self._set_launch_favicon(self.settings.launch_url)

    def manage_launch_sites(self) -> None:
        dialog = LaunchSitesDialog(self, self._launch_sites())
        if self._exec_profile_dialog(dialog):
            sites = dialog.build_sites()
            selected = self._current_launch_url()
            if selected not in sites:
                selected = sites[0]
            self.settings.launch_sites = sites
            self.settings.launch_url = selected
            self._sync_launch_sites_combo(selected)
            self.store.save_settings(self.settings)

    def _make_status_metric(self, layout: QHBoxLayout, title: str, value: str) -> QLabel:
        box = QHBoxLayout()
        box.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName('metricTitle')
        value_label = QLabel(value)
        value_label.setObjectName('statusMetricValue')
        box.addWidget(title_label)
        box.addWidget(value_label)
        layout.addLayout(box)
        return value_label
    def _metric_card(self, title: str, value: str) -> tuple[QFrame, QLabel]:
        card = QFrame()
        card.setObjectName('metricCard')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName('metricTitle')
        value_label = QLabel(value)
        value_label.setObjectName('metricValue')
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        return (card, value_label)

    def _build_settings_tab(self) -> QWidget:
        widget = QWidget()
        widget.setObjectName('settingsTabPage')
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 0)
        layout.setSpacing(18)

        cards = QHBoxLayout()
        cards.setSpacing(16)

        general = QFrame()
        general.setObjectName('settingsCard')
        general_layout = QGridLayout(general)
        general_layout.setContentsMargins(16, 16, 16, 16)
        general_layout.setHorizontalSpacing(18)
        general_layout.setVerticalSpacing(12)
        heading = QLabel('Общие настройки')
        heading.setObjectName('settingsHeading')
        general_layout.addWidget(heading, 0, 0, 1, 2)

        self.browser_combo = self._make_combo_box()
        self.browser_combo.addItem('Авто', 'auto')
        self.browser_combo.addItem('Chrome', 'chrome')
        self.browser_combo.addItem('Edge', 'edge')
        self.auto_open_check = self._make_switch()
        self._connect_switch(self.auto_open_check, self._remember_auto_open_from_settings)
        self.auto_connect_on_startup_check = self._make_switch()
        self._connect_switch(self.auto_connect_on_startup_check, self._remember_auto_connect_on_startup)
        self.disable_extensions_check = self._make_switch()
        self.stop_existing_check = self._make_switch()
        self.minimize_to_tray_check = self._make_switch()
        self.language_combo = self._make_combo_box()
        self.language_combo.addItem('Русский', 'ru')
        self.language_combo.addItem('English', 'en')

        self._add_setting_row(general_layout, 1, 'Браузер', 'Выберите браузер для запуска\nчерез прокси', self.browser_combo)
        self._add_setting_row(general_layout, 2, 'Запускать браузер после подключения', 'Открывать браузер сразу после подключения', self.auto_open_check)
        self._add_setting_row(general_layout, 3, 'Автоподключение при запуске', 'Запускать приложение вместе с Windows и подключаться', self.auto_connect_on_startup_check)
        self._add_setting_row(general_layout, 4, 'Отключать расширения браузера', 'Запускать Chrome/Edge без расширений', self.disable_extensions_check)
        self._add_setting_row(general_layout, 5, 'Сворачивать в трей', 'Закрывать окно в системную панель', self.minimize_to_tray_check)
        self._add_setting_row(general_layout, 6, 'Язык интерфейса', 'Смена локализации приложения', self.language_combo)
        cards.addWidget(general, 1)

        proxy = QFrame()
        proxy.setObjectName('settingsCard')
        proxy_layout = QGridLayout(proxy)
        proxy_layout.setContentsMargins(16, 16, 16, 16)
        proxy_layout.setHorizontalSpacing(12)
        proxy_layout.setVerticalSpacing(10)
        proxy_heading = QLabel('Сетевой прокси-сервер')
        proxy_heading.setObjectName('settingsHeadingAccent')
        proxy_layout.addWidget(proxy_heading, 0, 0, 1, 2)

        self.http_port_spin = QSpinBox()
        self.http_port_spin.setRange(1024, 65535)
        self.socks_port_spin = QSpinBox()
        self.socks_port_spin.setRange(1024, 65535)
        self.dns_edit = QLineEdit()
        self.dns_edit.setPlaceholderText('1.1.1.1, 8.8.8.8')

        proxy_layout.addLayout(self._field_caption('HTTP Port', 'Порт локального HTTP сервера'), 1, 0)
        proxy_layout.addLayout(self._field_caption('SOCKS5 Port', 'Порт локального SOCKS5 сервера'), 1, 1)
        proxy_layout.addWidget(self.http_port_spin, 2, 0)
        proxy_layout.addWidget(self.socks_port_spin, 2, 1)
        proxy_layout.addLayout(self._field_caption('Пользовательский DNS', 'DNS-серверы через запятую'), 3, 0, 1, 2)
        proxy_layout.addWidget(self.dns_edit, 4, 0, 1, 2)
        self._add_setting_row(proxy_layout, 5, 'Останавливать старые сеансы', 'Закрывать только сеансы, запущенные Outward App', self.stop_existing_check)
        proxy_layout.setRowStretch(6, 1)
        cards.addWidget(proxy, 1)
        layout.addLayout(cards)

        layout.addStretch(1)
        save_button = QPushButton('Сохранить настройки')
        save_button.setObjectName('primaryButtonWide')
        save_button.clicked.connect(self.save_settings)
        layout.addWidget(save_button)
        return widget

    def _build_update_tab(self) -> QWidget:
        widget = QWidget()
        widget.setObjectName('updateTabPage')
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 0)
        layout.setSpacing(18)

        update_panel = QFrame()
        update_panel.setObjectName('updatePanel')
        update_layout = QVBoxLayout(update_panel)
        update_layout.setContentsMargins(16, 14, 16, 14)
        update_layout.setSpacing(12)
        update_copy = QVBoxLayout()
        update_copy.setSpacing(2)
        update_title = QLabel('Обновление системы')
        update_title.setObjectName('settingLabel')
        self.update_status_label = QLabel(f'Текущая версия {APP_NAME}: {get_app_version()}. Проверка обновлений будет выполнена при запуске.')
        self.update_status_label.setObjectName('mutedLabel')
        self.update_status_label.setWordWrap(True)
        update_copy.addWidget(update_title)
        update_copy.addWidget(self.update_status_label)
        self.auto_update_check = self._make_switch()
        self._connect_switch(self.auto_update_check, self._remember_auto_update)
        auto_update_row = QVBoxLayout()
        auto_update_row.setSpacing(2)
        auto_update_title = QLabel('Автоматическое обновление приложения')
        auto_update_title.setObjectName('settingLabel')
        auto_update_hint = QLabel('Скачивать новую версию в фоне после проверки')
        auto_update_hint.setObjectName('mutedLabel')
        auto_update_hint.setWordWrap(True)
        auto_update_row.addWidget(auto_update_title)
        auto_update_row.addWidget(auto_update_hint)
        auto_update_setting = QHBoxLayout()
        auto_update_setting.setSpacing(12)
        auto_update_setting.addLayout(auto_update_row, 1)
        auto_update_setting.addWidget(self.auto_update_check, 0, Qt.AlignTop)
        self.update_button = QPushButton('Проверить обновления')
        self.update_button.setObjectName('outlineButton')
        self.update_button.clicked.connect(lambda: self.check_for_updates(silent=False))
        self.update_restart_button = QPushButton('Перезапустить и обновить')
        self.update_restart_button.setObjectName('successButton')
        self.update_restart_button.hide()
        self.update_restart_button.clicked.connect(self.install_downloaded_update)
        update_actions = QVBoxLayout()
        update_actions.setSpacing(8)
        update_actions.addWidget(self.update_button, 0, Qt.AlignLeft)
        update_actions.addWidget(self.update_restart_button, 0, Qt.AlignLeft)
        update_layout.addLayout(update_copy)
        update_layout.addLayout(auto_update_setting)
        update_layout.addLayout(update_actions)
        layout.addWidget(update_panel)
        layout.addStretch(1)
        return widget

    def _field_caption(self, title: str, hint: str) -> QVBoxLayout:
        labels = QVBoxLayout()
        labels.setSpacing(1)
        title_label = QLabel(title)
        title_label.setObjectName('settingLabel')
        hint_label = QLabel(hint)
        hint_label.setObjectName('mutedLabel')
        hint_label.setWordWrap(True)
        labels.addWidget(title_label)
        labels.addWidget(hint_label)
        return labels

    def _add_setting_row(self, layout: QGridLayout, row: int, title: str, hint: str, control: QWidget) -> None:
        labels = QVBoxLayout()
        labels.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName('settingLabel')
        labels.addWidget(title_label)
        if hint:
            hint_label = QLabel(hint)
            hint_label.setObjectName('mutedLabel')
            hint_label.setWordWrap(True)
            labels.addWidget(hint_label)
        layout.addLayout(labels, row, 0)
        layout.addWidget(control, row, 1)

    def _create_tray_icon(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = QIcon(str(asset_path('outward.ico')))
        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip(APP_NAME)
        menu = QMenu(self)
        show_action = QAction(f'Показать {APP_NAME}', self)
        quit_action = QAction('Выход', self)
        show_action.triggered.connect(self._restore_from_tray)
        quit_action.triggered.connect(self._quit_from_tray)
        menu.addAction(show_action)
        menu.addAction(quit_action)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(lambda reason: self._restore_from_tray() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray_icon.show()

    def _load_settings_to_ui(self) -> None:
        index = self.browser_combo.findData(self.settings.preferred_browser)
        self.browser_combo.setCurrentIndex(max(index, 0))
        self.http_port_spin.setValue(self.settings.http_port)
        self.socks_port_spin.setValue(self.settings.socks_port)
        self._sync_launch_sites_combo(self.settings.launch_url)
        self.launch_auto_open_check.setChecked(self.settings.auto_open_browser)
        self.auto_open_check.setChecked(self.settings.auto_open_browser)
        self.auto_connect_on_startup_check.setChecked(self.settings.auto_connect_on_startup)
        self.disable_extensions_check.setChecked(self.settings.disable_browser_extensions)
        self.stop_existing_check.setChecked(self.settings.stop_existing_sing_box)
        self.minimize_to_tray_check.setChecked(self.settings.minimize_to_tray)
        self.auto_update_check.setChecked(self.settings.auto_update_app)
        language_index = self.language_combo.findData(self.settings.language)
        self.language_combo.setCurrentIndex(max(language_index, 0))
        self.dns_edit.setText(self.settings.custom_dns)

    def save_settings(self) -> None:
        http_port = int(self.http_port_spin.value())
        socks_port = int(self.socks_port_spin.value())
        if http_port == socks_port:
            socks_port = min(65535, http_port + 1)
            self.socks_port_spin.setValue(socks_port)
            QMessageBox.information(self, APP_NAME, 'SOCKS5 порт должен отличаться от HTTP. Значение обновлено автоматически.')
        self.settings = AppSettings(
            preferred_browser=str(self.browser_combo.currentData()),
            http_port=http_port,
            socks_port=socks_port,
            launch_url=self._current_launch_url(),
            launch_sites=self._launch_sites(),
            auto_open_browser=self.auto_open_check.isChecked(),
            auto_connect_on_startup=self.auto_connect_on_startup_check.isChecked(),
            disable_browser_extensions=self.disable_extensions_check.isChecked(),
            stop_existing_sing_box=self.stop_existing_check.isChecked(),
            minimize_to_tray=self.minimize_to_tray_check.isChecked(),
            auto_update_app=self.auto_update_check.isChecked(),
            language=str(self.language_combo.currentData()),
            custom_dns=self.dns_edit.text().strip(),
        )
        self.store.save_settings(self.settings)
        self._sync_windows_startup()
        self.status_caption_label.setText('Настройки сохранены.')

    def _remember_launch_url(self, text: str) -> None:
        self.settings.launch_url = text.strip() or 'example.com'
        if self.settings.launch_url not in self.settings.launch_sites:
            self.settings.launch_sites.append(self.settings.launch_url)
        self._set_launch_favicon(self.settings.launch_url)

    def _remember_auto_open_from_launch(self, *_args) -> None:
        self._sync_auto_open_checkboxes(self.launch_auto_open_check.isChecked(), self.launch_auto_open_check)

    def _remember_auto_open_from_settings(self, *_args) -> None:
        self._sync_auto_open_checkboxes(self.auto_open_check.isChecked(), self.auto_open_check)

    def _sync_auto_open_checkboxes(self, checked: bool, source: QWidget) -> None:
        self.settings.auto_open_browser = checked
        for checkbox in (self.launch_auto_open_check, self.auto_open_check):
            if checkbox is source:
                continue
            checkbox.blockSignals(True)
            checkbox.setChecked(checked)
            checkbox.blockSignals(False)

    def _remember_auto_update(self, *_args) -> None:
        self.settings.auto_update_app = self.auto_update_check.isChecked()
        self.store.save_settings(self.settings)
        if self.settings.auto_update_app and self.available_update and not self.downloaded_update_installer:
            self.download_update(self.available_update)

    def _remember_auto_connect_on_startup(self, *_args) -> None:
        self.settings.auto_connect_on_startup = self.auto_connect_on_startup_check.isChecked()
        self.store.save_settings(self.settings)
        self._sync_windows_startup()

    def _sync_windows_startup(self) -> None:
        try:
            set_launch_on_startup(self.settings.auto_connect_on_startup)
        except Exception as exc:
            self.status_caption_label.setText('Не удалось обновить автозагрузку Windows.')
            QMessageBox.warning(self, APP_NAME, f'Не удалось обновить автозагрузку Windows.\n\n{exc}')

    def _connect_on_startup(self) -> None:
        if not self.settings.auto_connect_on_startup or self.runtime_state or self.connect_thread is not None:
            return
        if self.current_profile() is None:
            self.status_caption_label.setText('Автоподключение включено, но профиль не выбран.')
            return
        self.connect_profile()

    def _check_updates_on_startup(self) -> None:
        self.check_for_updates(silent=True)

    def check_for_updates(self, silent: bool = False) -> None:
        if self.update_check_thread is not None:
            return
        self._update_check_silent = silent
        self.update_button.setEnabled(False)
        self.update_restart_button.hide()
        self.update_status_label.setText('Проверяем обновления на GitHub...')
        self.update_check_thread = QThread(self)
        self.update_check_worker = UpdateCheckWorker(self.update_manager)
        self.update_check_worker.moveToThread(self.update_check_thread)
        self.update_check_thread.started.connect(self.update_check_worker.run)
        self.update_check_worker.checked.connect(self._on_update_checked)
        self.update_check_worker.failed.connect(self._on_update_check_failed)
        self.update_check_worker.finished.connect(self.update_check_thread.quit)
        self.update_check_worker.finished.connect(self.update_check_worker.deleteLater)
        self.update_check_thread.finished.connect(self._on_update_check_finished)
        self.update_check_thread.finished.connect(self.update_check_thread.deleteLater)
        self.update_check_thread.start()

    def _on_update_checked(self, result: object) -> None:
        if not isinstance(result, UpdateCheckResult):
            return
        self.available_update = result.release if result.update_available else None
        self.downloaded_update_installer = None
        if result.update_available and result.release:
            self.update_status_label.setText(f'Доступна версия {result.latest_version}. Текущая версия: {result.current_version}.')
            if self.settings.auto_update_app:
                self.download_update(result.release)
            elif not getattr(self, '_update_check_silent', False):
                QMessageBox.information(self, APP_NAME, f'Доступно обновление {result.latest_version}. Включите автоматическое обновление, чтобы скачать его в фоне.')
            return
        self.update_status_label.setText(f'Установлена последняя версия {result.current_version}.')
        if not getattr(self, '_update_check_silent', False):
            QMessageBox.information(self, APP_NAME, 'Установлена последняя версия приложения.')

    def _on_update_check_failed(self, message: str) -> None:
        self.update_status_label.setText('Не удалось проверить обновления. Проверьте подключение к GitHub.')
        if not getattr(self, '_update_check_silent', False):
            QMessageBox.warning(self, APP_NAME, f'Не удалось проверить обновления.\n\n{message}')

    def _on_update_check_finished(self) -> None:
        self.update_check_thread = None
        self.update_check_worker = None
        self.update_button.setEnabled(True)

    def download_update(self, release: UpdateRelease) -> None:
        if self.update_download_thread is not None:
            return
        self.update_button.setEnabled(False)
        self.update_status_label.setText(f'Скачиваем обновление {release.version}...')
        self.update_download_thread = QThread(self)
        self.update_download_worker = UpdateDownloadWorker(self.update_manager, release)
        self.update_download_worker.moveToThread(self.update_download_thread)
        self.update_download_thread.started.connect(self.update_download_worker.run)
        self.update_download_worker.progress.connect(self._on_update_download_progress)
        self.update_download_worker.downloaded.connect(self._on_update_downloaded)
        self.update_download_worker.failed.connect(self._on_update_download_failed)
        self.update_download_worker.finished.connect(self.update_download_thread.quit)
        self.update_download_worker.finished.connect(self.update_download_worker.deleteLater)
        self.update_download_thread.finished.connect(self._on_update_download_finished)
        self.update_download_thread.finished.connect(self.update_download_thread.deleteLater)
        self.update_download_thread.start()

    def _on_update_download_progress(self, downloaded: int, total: int) -> None:
        if total > 0:
            percent = int(downloaded * 100 / total)
            self.update_status_label.setText(f'Скачиваем обновление... {percent}%')
        else:
            megabytes = downloaded / (1024 * 1024)
            self.update_status_label.setText(f'Скачиваем обновление... {megabytes:.1f} МБ')

    def _on_update_downloaded(self, path: object) -> None:
        self.downloaded_update_installer = path if isinstance(path, Path) else Path(str(path))
        self.update_status_label.setText('Обновление загружено и готово к установке.')
        self.update_restart_button.show()

    def _on_update_download_failed(self, message: str) -> None:
        self.downloaded_update_installer = None
        self.update_status_label.setText('Не удалось скачать обновление.')
        QMessageBox.warning(self, APP_NAME, f'Не удалось скачать обновление.\n\n{message}')

    def _on_update_download_finished(self) -> None:
        self.update_download_thread = None
        self.update_download_worker = None
        self.update_button.setEnabled(True)

    def install_downloaded_update(self) -> None:
        installer = self.downloaded_update_installer
        if installer is None or not installer.exists():
            QMessageBox.warning(self, APP_NAME, 'Файл обновления не найден. Проверьте обновления еще раз.')
            return
        answer = QMessageBox.question(self, f'Обновить {APP_NAME}', 'Приложение закроется, установит обновление и запустится снова. Продолжить?')
        if answer != QMessageBox.Yes:
            return
        if self.manager.is_running():
            self.manager.stop()
        try:
            subprocess.Popen([str(installer), '/SILENT', '/NORESTART'], cwd=str(installer.parent), close_fds=True)
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f'Не удалось запустить установщик.\n\n{exc}')
            return
        self.force_quit = True
        app = QApplication.instance()
        if app is not None:
            app.quit()
        else:
            self.close()

    def _load_profiles(self) -> None:
        current = self.current_profile()
        current_id = current.id if current else None
        self.profiles = self.store.load_profiles()
        self.profile_list.clear()
        for profile in self.profiles:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, profile.id)
            item.setToolTip(profile.server or profile.name)
            item.setSizeHint(QSize(184, 48))
            self.profile_list.addItem(item)
            self.profile_list.setItemWidget(item, self._profile_item_widget(profile))
            if current_id and profile.id == current_id:
                self.profile_list.setCurrentItem(item)
        if self.profiles and self.profile_list.currentRow() < 0:
            self.profile_list.setCurrentRow(0)
        self._sync_profile_buttons()

    def _profile_item_widget(self, profile: ConnectionProfile) -> QWidget:
        row = QFrame()
        row.setObjectName('profileRow')
        row.setProperty('selected', 'false')
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(8)

        accent = QFrame()
        accent.setObjectName('profileAccent')
        accent.setFixedSize(3, 28)
        layout.addWidget(accent)

        flag = QLabel(self._profile_country_code(profile) or '··')
        flag.setObjectName('profileCountryBadge')
        flag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        flag.setFixedSize(28, 18)
        layout.addWidget(flag)

        copy = QVBoxLayout()
        copy.setSpacing(0)
        name = QLabel(profile.name)
        name.setObjectName('profileName')
        protocol = QLabel(protocol_label_for_link(profile.link))
        protocol.setObjectName('profileProtocol')
        copy.addWidget(name)
        copy.addWidget(protocol)
        layout.addLayout(copy, 1)
        return row

    def _refresh_profile_item_selection(self) -> None:
        for index in range(self.profile_list.count()):
            item = self.profile_list.item(index)
            widget = self.profile_list.itemWidget(item)
            if widget is None:
                continue
            widget.setProperty('selected', 'true' if item is self.profile_list.currentItem() else 'false')
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            for child in widget.findChildren(QWidget):
                child.style().unpolish(child)
                child.style().polish(child)

    def _profile_country_code(self, profile: ConnectionProfile) -> str:
        saved = normalize_country_code(profile.country_code)
        if saved:
            return saved
        return guess_country_code(profile.name, profile.remark, profile.server)
    def _show_profile_context_menu(self, position) -> None:
        item = self.profile_list.itemAt(position)
        if item is None:
            return
        self.profile_list.setCurrentItem(item)
        menu = QMenu(self)
        edit_action = QAction('Изменить', self)
        delete_action = QAction('Удалить', self)
        edit_action.triggered.connect(self.edit_profile)
        delete_action.triggered.connect(self.delete_profile)
        menu.addAction(edit_action)
        menu.addAction(delete_action)
        menu.exec(self.profile_list.mapToGlobal(position))
    def _sync_profile_buttons(self) -> None:
        has_profile = self.current_profile() is not None
        running = self.manager.is_running()
        busy = self.connect_thread is not None or self.disconnect_thread is not None
        self._refresh_profile_item_selection()
        self.edit_button.setEnabled(has_profile and not busy)
        self.delete_button.setEnabled(has_profile and not busy)
        self.connect_button.setEnabled(has_profile and (not running) and (not busy))
        self.disconnect_button.setEnabled(running and not busy)

    def current_profile(self) -> ConnectionProfile | None:
        item = self.profile_list.currentItem()
        if not item:
            return None
        profile_id = item.data(Qt.ItemDataRole.UserRole)
        for profile in self.profiles:
            if profile.id == profile_id:
                return profile
        return None

    def _exec_profile_dialog(self, dialog: ProfileDialog) -> int:
        overlay = QFrame(self.centralWidget())
        overlay.setObjectName('dialogOverlay')
        overlay.setGeometry(self.centralWidget().rect())
        overlay.show()
        overlay.raise_()
        dialog.adjustSize()
        center = self.mapToGlobal(self.rect().center())
        dialog.move(center.x() - dialog.width() // 2, center.y() - dialog.height() // 2)
        try:
            return dialog.exec()
        finally:
            overlay.deleteLater()

    def add_profile(self) -> None:
        dialog = ProfileDialog(self)
        if self._exec_profile_dialog(dialog):
            self.store.upsert_profile(dialog.build_profile())
            self._load_profiles()

    def edit_profile(self) -> None:
        profile = self.current_profile()
        if not profile:
            return
        dialog = ProfileDialog(self, profile=profile)
        if self._exec_profile_dialog(dialog):
            self.store.upsert_profile(dialog.build_profile())
            self._load_profiles()

    def delete_profile(self) -> None:
        profile = self.current_profile()
        if not profile:
            return
        answer = QMessageBox.question(self, 'Удалить профиль', f'Удалить профиль {profile.name}?')
        if answer == QMessageBox.Yes:
            self.store.delete_profile(profile.id)
            self._load_profiles()

    def connect_profile(self) -> None:
        if self.connect_thread is not None or self.disconnect_thread is not None:
            return
        profile = self.current_profile()
        if not profile:
            QMessageBox.information(self, APP_NAME, 'Сначала выберите профиль.')
            return
        self.save_settings()
        self.connect_button.setVisible(True)
        self.disconnect_button.setVisible(False)
        self.connect_button.set_loading(True, 'Подключение...')
        self.disconnect_button.setEnabled(False)
        self.status_caption_label.setText('Запуск подключения...')
        self.status_title_label.setText('Подключение запускается')
        self.status_dot.setProperty('connected', 'pending')
        self._refresh_status_dot()
        self.connect_thread = QThread(self)
        self.connect_worker = ConnectWorker(profile, self.settings, self.manager, self.store)
        self.connect_worker.moveToThread(self.connect_thread)
        self.connect_thread.started.connect(self.connect_worker.run)
        self.connect_worker.message.connect(self._set_progress_message)
        self.connect_worker.connected.connect(self._on_connected)
        self.connect_worker.failed.connect(self._on_connect_failed)
        self.connect_worker.finished.connect(self.connect_thread.quit)
        self.connect_worker.finished.connect(self.connect_worker.deleteLater)
        self.connect_thread.finished.connect(self._on_connect_finished)
        self.connect_thread.finished.connect(self.connect_thread.deleteLater)
        self.connect_thread.start()

    def _set_progress_message(self, message: str) -> None:
        self.status_caption_label.setText(message)

    def _on_connected(self, state: object) -> None:
        self.runtime_state = state if isinstance(state, RuntimeState) else None
        self._set_connected(True)
        if isinstance(state, RuntimeState):
            self.status_profile_value.setText(state.profile_name)
            self.http_port_label.setText(str(state.http_port))
            self.socks_port_label.setText(str(state.socks_port))
            self.protocol_label.setText(state.protocol_label)
            self.latency_value.setText('...')
            self._start_ping_updates()
            self.setWindowTitle(f'{APP_NAME} - Подключено к {state.profile_name}')
        self._set_tab_index(0)
        self._load_profiles()
        self.refresh_log()

    def _on_connect_failed(self, message: str) -> None:
        try:
            append_log_entry(message)
        except Exception:
            pass
        self.manager.stop()
        self._stop_ping_updates()
        self.runtime_state = None
        self._set_connected(False)
        self.status_caption_label.setText('Ошибка подключения')
        QMessageBox.critical(self, 'Ошибка подключения', 'Ошибка подключения')
        self.refresh_log()

    def _on_connect_finished(self) -> None:
        self.connect_button.set_loading(False)
        self.connect_thread = None
        self.connect_worker = None
        self._sync_profile_buttons()
        running = self.manager.is_running()
        self.disconnect_button.setVisible(running)
        self.disconnect_button.setEnabled(running)
        self.connect_button.setVisible(not running)

    def disconnect_profile(self) -> None:
        if self.connect_thread is not None or self.disconnect_thread is not None:
            return
        if not self.manager.is_running():
            self._stop_ping_updates()
            self.runtime_state = None
            self._set_connected(False)
            self.status_caption_label.setText('Подключение остановлено.')
            self.refresh_log()
            return
        self.disconnect_error = None
        self.disconnect_button.setVisible(True)
        self.disconnect_button.set_loading(True, 'Отключение...')
        self.connect_button.setEnabled(False)
        self.open_browser_button.setEnabled(False)
        self.status_caption_label.setText('Останавливаем подключение...')
        self.status_title_label.setText('Отключение proxy')
        self.status_dot.setProperty('connected', 'pending')
        self._refresh_status_dot()
        self.disconnect_thread = QThread(self)
        self.disconnect_worker = DisconnectWorker(self.manager)
        self.disconnect_worker.moveToThread(self.disconnect_thread)
        self.disconnect_thread.started.connect(self.disconnect_worker.run)
        self.disconnect_worker.failed.connect(self._on_disconnect_failed)
        self.disconnect_worker.finished.connect(self.disconnect_thread.quit)
        self.disconnect_worker.finished.connect(self.disconnect_worker.deleteLater)
        self.disconnect_thread.finished.connect(self._on_disconnect_finished)
        self.disconnect_thread.finished.connect(self.disconnect_thread.deleteLater)
        self.disconnect_thread.start()

    def _on_disconnect_failed(self, message: str) -> None:
        self.disconnect_error = message
        try:
            append_log_entry(message)
        except Exception:
            pass

    def _on_disconnect_finished(self) -> None:
        error = self.disconnect_error
        self.disconnect_button.set_loading(False)
        self.disconnect_thread = None
        self.disconnect_worker = None
        self.disconnect_error = None
        still_running = self.manager.is_running()
        if error and still_running:
            self._set_connected(True)
            self.status_caption_label.setText('Не удалось остановить подключение')
            QMessageBox.warning(self, APP_NAME, f'Не удалось остановить подключение.\n\n{error}')
        else:
            self._stop_ping_updates()
            self.runtime_state = None
            self._set_connected(False)
            self.status_caption_label.setText('Подключение остановлено.')
        self.refresh_log()
        self._sync_profile_buttons()

    def open_browser(self) -> None:
        if not self.runtime_state:
            QMessageBox.information(self, APP_NAME, 'Сначала подключите профиль.')
            return
        self.save_settings()
        open_url_with_proxy(
            self.runtime_state.socks_port,
            self.settings.preferred_browser,
            self.settings.launch_url,
            self.settings.disable_browser_extensions,
        )

    def _set_connected(self, connected: bool) -> None:
        self.status_dot.setProperty('connected', 'true' if connected else 'false')
        self._refresh_status_dot()
        self.status_title_label.setText('Подключено к proxy' if connected else 'Подключение остановлено')
        self.connect_button.setVisible(not connected)
        self.disconnect_button.setVisible(connected)
        busy = self.connect_thread is not None or self.disconnect_thread is not None
        self.disconnect_button.setEnabled(connected and not busy)
        self.open_browser_button.setEnabled(connected and not busy)
        self.connect_button.setEnabled((not connected) and self.current_profile() is not None and not busy)
        if not connected:
            self.setWindowTitle(f'{APP_NAME} - Настройки')
            self.status_profile_value.setText('-')
            self.session_value.setText('00:00:00')
            self.latency_value.setText('-')
            self.http_port_label.setText(str(self.settings.http_port))
            self.socks_port_label.setText(str(self.settings.socks_port))
            self.protocol_label.setText('VLESS')
            if not self.status_caption_label.text() or 'Подключ' not in self.status_caption_label.text():
                self.status_caption_label.setText('Клиент proxy находится в режиме ожидания')

    def _refresh_status_dot(self) -> None:
        self.status_dot.style().unpolish(self.status_dot)
        self.status_dot.style().polish(self.status_dot)

    def _update_session_time(self) -> None:
        if not self.runtime_state:
            return
        try:
            started_at = datetime.fromisoformat(self.runtime_state.started_at)
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            elapsed = datetime.now(timezone.utc) - started_at.astimezone(timezone.utc)
            total_seconds = max(0, int(elapsed.total_seconds()))
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            self.session_value.setText(f'{hours:02}:{minutes:02}:{seconds:02}')
        except ValueError:
            self.session_value.setText('00:00:00')

    def _start_ping_updates(self) -> None:
        self.ping_timer.start()
        self._request_ping_update()

    def _stop_ping_updates(self) -> None:
        self.ping_timer.stop()
        self.latency_value.setText('-')

    def _request_ping_update(self) -> None:
        state = self.runtime_state
        if state is None or not self.manager.is_running():
            self._stop_ping_updates()
            return
        if self.ping_thread is not None or not state.server or state.server_port <= 0:
            return
        self.ping_thread = QThread(self)
        self.ping_worker = PingWorker(state.server, state.server_port)
        self.ping_worker.moveToThread(self.ping_thread)
        self.ping_thread.started.connect(self.ping_worker.run)
        self.ping_worker.measured.connect(self._on_ping_measured)
        self.ping_worker.failed.connect(self._on_ping_failed)
        self.ping_worker.finished.connect(self.ping_thread.quit)
        self.ping_worker.finished.connect(self.ping_worker.deleteLater)
        self.ping_thread.finished.connect(self._on_ping_finished)
        self.ping_thread.finished.connect(self.ping_thread.deleteLater)
        self.ping_thread.start()

    def _on_ping_measured(self, elapsed_ms: int) -> None:
        if self.runtime_state is not None and self.manager.is_running():
            self.latency_value.setText(f'{elapsed_ms} мс')

    def _on_ping_failed(self, message: str) -> None:
        if self.runtime_state is not None and self.manager.is_running():
            self.latency_value.setText('нет ответа')

    def _on_ping_finished(self) -> None:
        self.ping_thread = None
        self.ping_worker = None

    def refresh_log(self) -> None:
        text = tail_log()
        if text != self._last_log_text:
            self._last_log_text = text
            self.log_view.setHtml(self._format_log_html(text))
            self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    def _format_log_html(self, text: str) -> str:
        rows = []
        for raw_line in text.splitlines():
            line = self._strip_ansi(raw_line).strip()
            if not line:
                continue
            time_value, level, message = self._parse_log_line(line)
            level_class = level.lower() if level else 'plain'
            time_html = f'<span class="time">{escape(time_value)}</span>' if time_value else '<span class="time">--:--:--</span>'
            level_html = f'<span class="level {level_class}">{escape(level)}</span>' if level else '<span class="level plain">LOG</span>'
            rows.append(f'<div>{time_html}<span class="gap">  </span>{level_html}<span class="gap">  </span><span>{escape(message)}</span></div>')
        body = ''.join(rows) or '<span class="time">Лог sing-box появится здесь после запуска.</span>'
        return f"""
        <html><head><style>
        body {{ background: #10101e; color: #9da4b8; font-family: 'Cascadia Mono', Consolas, monospace; font-size: 12px; }}
        div {{ white-space: pre-wrap; line-height: 1.35; }}
        .time {{ color: #64748B; }}
        .level {{ font-weight: 700; }}
        .info {{ color: #10B981; }}
        .warn, .warning {{ color: #F59E0B; }}
        .error {{ color: #EF4444; }}
        .debug, .trace, .plain {{ color: #94A3B8; }}
        </style></head><body>{body}</body></html>
        """

    def _strip_ansi(self, text: str) -> str:
        text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
        return re.sub(r'\[[0-9;]*m', '', text)

    def _parse_log_line(self, line: str) -> tuple[str, str, str]:
        pattern = re.compile(r'^(?:[+-]\d{4}\s+)?(?:\d{4}-\d{2}-\d{2}\s+)?(?P<time>\d{2}:\d{2}:\d{2})(?P<rest>.*)$')
        match = pattern.match(line)
        time_value = ''
        rest = line
        if match:
            time_value = match.group('time')
            rest = match.group('rest').strip()
        rest = re.sub(r'^\[[^\]]+\]\s*', '', rest)
        level_match = re.search(r'\b(INFO|WARN|WARNING|ERROR|DEBUG|TRACE)\b', rest, re.IGNORECASE)
        if not level_match:
            return time_value, '', rest
        level = level_match.group(1).upper()
        message = (rest[:level_match.start()] + rest[level_match.end():]).strip(' :-')
        return time_value, level, message or rest

    def restore_from_tray(self) -> None:
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def _restore_from_tray(self) -> None:
        self.restore_from_tray()

    def _quit_from_tray(self) -> None:
        self.force_quit = True
        if self.manager.is_running():
            self.manager.stop()
        if self.tray_icon:
            self.tray_icon.hide()
        if self.close():
            app = QApplication.instance()
            if app is not None:
                QTimer.singleShot(0, app.quit)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self.dark_title_applied:
            self._apply_windows_dark_title_bar()
            self.dark_title_applied = True

    def _apply_windows_dark_title_bar(self) -> None:
        try:
            hwnd = int(self.winId())
            value = ctypes.c_int(1)
            for attribute in (20, 19):
                result = ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value))
                if result == 0:
                    break
        except Exception:
            return

    def closeEvent(self, event) -> None:
        self.save_settings()
        if not self.force_quit and self.settings.minimize_to_tray and self.tray_icon:
            self.hide()
            self.tray_icon.showMessage(APP_NAME, 'Приложение свернуто в трей.', QSystemTrayIcon.MessageIcon.Information, 1800)
            event.ignore()
            return
        if self.manager.is_running():
            if not self.force_quit:
                answer = QMessageBox.question(self, f'Закрыть {APP_NAME}', 'Остановить sing-box и закрыть приложение?')
                if answer != QMessageBox.Yes:
                    event.ignore()
                    return
            self.manager.stop()
        if self.tray_icon:
            self.tray_icon.hide()
        event.accept()
