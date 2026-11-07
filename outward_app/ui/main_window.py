from __future__ import annotations
from pathlib import Path
import re
import subprocess
from datetime import datetime, timezone
from time import perf_counter
from html import escape
from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QPainter, QPalette, QPen, QPixmap, QTextCursor
from PySide6.QtNetwork import QTcpSocket
from PySide6.QtWidgets import QApplication, QBoxLayout, QCheckBox, QComboBox, QCompleter, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton, QTextEdit, QScrollArea, QSizePolicy, QSpinBox, QSystemTrayIcon, QVBoxLayout, QWidget
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
from outward_app.ui.country_flags import CountryFlagBadge
from outward_app.ui.widgets import CurrentPageStack, ElidedLabel, MenuButton, SelectCombo, StatusCaption, ThemeSelector
from outward_app.ui.themes import theme_color, theme_colors, theme_manager
from outward_app.ui.connections import ConnectionsUi
from outward_app.ui.window_chrome import ChromeMainWindow, DEFAULT_WINDOW_SIZE, MINIMUM_WINDOW_SIZE
from outward_app.version import get_app_version
from outward_app.ui.i18n import set_language, tr

try:
    from qfluentwidgets import ComboBox as FluentComboBox
except ImportError:
    FluentComboBox = None

class SwitchControl(QCheckBox):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(44, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def hitButton(self, position) -> bool:
        return self.rect().contains(position)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.45)
        track = QRectF(2, 2, 40, 20)
        if self.isChecked():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme_color('primary'))
            painter.drawRoundedRect(track, 10, 10)
            painter.setBrush(theme_color('on_primary'))
            painter.drawEllipse(QRectF(24, 4, 16, 16))
        else:
            painter.setPen(QPen(theme_color('control_border'), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(track, 10, 10)
            painter.setPen(QPen(theme_color('muted'), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(9, 8, 8, 8))
        if self.hasFocus():
            painter.setPen(QPen(theme_color('focus'), 1, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(0.5, 0.5, 43, 23), 5, 5)

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
        color = self.palette().color(QPalette.ColorRole.ButtonText)
        pen = QPen(color, 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(QRectF(3, 3, 10, 10), self._loading_angle * 16, -270 * 16)
        painter.end()
        self.setIcon(QIcon(pixmap))
        self._loading_angle = (self._loading_angle - 30) % 360




class UpdateCheckWorker(QThread):
    checked = Signal(object)
    failed = Signal(str)

    def __init__(self, manager: UpdateManager, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager

    def run(self) -> None:
        try:
            self.checked.emit(self.manager.check_for_update())
        except Exception as exc:
            self.failed.emit(str(exc))

class UpdateDownloadWorker(QThread):
    progress = Signal(int, int)
    downloaded = Signal(object)
    failed = Signal(str)

    def __init__(self, manager: UpdateManager, release: UpdateRelease, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.release = release

    def run(self) -> None:
        try:
            path = self.manager.download_update(self.release, self.progress.emit)
            self.downloaded.emit(path)
        except Exception as exc:
            self.failed.emit(str(exc))

class MainWindow(ConnectionsUi, ChromeMainWindow):

    def __init__(self, *, launched_on_startup: bool = False) -> None:
        store = JsonStore()
        settings = store.load_settings()
        set_language(settings.language)
        super().__init__()
        self._launched_on_startup = launched_on_startup
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(*MINIMUM_WINDOW_SIZE)
        self.resize(*DEFAULT_WINDOW_SIZE)
        self.store = store
        self.settings = settings
        theme_manager().apply(self.settings.theme)
        self.profiles = self.store.load_profiles()
        self._init_connections()
        self.connect_thread = None
        self.disconnect_thread = None
        self.update_check_thread = None
        self.update_check_worker = None
        self.update_download_thread = None
        self.update_download_worker = None
        self.update_manager = UpdateManager(get_app_version())
        self.available_update = None
        self.downloaded_update_installer = None
        self.tray_icon = None
        self.force_quit = False
        self.dark_title_applied = False
        self._last_log_text = ''
        self._build_ui()
        self._create_tray_icon()
        self._load_profiles()
        self._load_settings_to_ui()
        theme_manager().theme_changed.connect(self._on_theme_changed)
        self._sync_windows_startup()
        self.log_timer = QTimer(self)
        self.log_timer.setInterval(1500)
        self.log_timer.timeout.connect(self.refresh_log)
        self.log_timer.start()
        self.session_timer = QTimer(self)
        self.session_timer.setInterval(1000)
        self.session_timer.timeout.connect(self.dashboard.tick)
        self.session_timer.start()
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

        profile_title = QLabel(tr('ПРОФИЛИ ПОДКЛЮЧЕНИЯ'))
        profile_title.setObjectName('sectionTitle')
        side_layout.addWidget(profile_title)

        self.empty_profiles = QFrame()
        self.empty_profiles.setObjectName('emptyProfiles')
        empty_layout = QVBoxLayout(self.empty_profiles)
        empty_layout.setContentsMargins(4, 12, 4, 0)
        empty_title = QLabel(tr('Пока нет профилей'))
        empty_title.setObjectName('settingLabel')
        empty_title.setWordWrap(True)
        empty_hint = QLabel(tr('Добавьте ссылку подключения, чтобы начать.'))
        empty_hint.setObjectName('mutedLabel')
        empty_hint.setWordWrap(True)
        empty_add = QPushButton(tr('Добавить профиль'))
        empty_add.setObjectName('primaryButton')
        empty_add.clicked.connect(self.add_profile)
        empty_layout.addWidget(empty_title)
        empty_layout.addWidget(empty_hint)
        empty_layout.addWidget(empty_add)
        empty_layout.addStretch(1)
        side_layout.addWidget(self.empty_profiles, 1)

        self.profile_list = QListWidget()
        self.profile_list.setAccessibleName(tr('Профили подключения'))
        self.profile_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.profile_list.customContextMenuRequested.connect(self._show_profile_context_menu)
        self.profile_list.currentItemChanged.connect(self._sync_profile_buttons)
        self.profile_list.itemDoubleClicked.connect(lambda _item: self.connect_profile())
        side_layout.addWidget(self.profile_list, 1)

        self.edit_button = QPushButton(tr('Изменить'), sidebar)
        self.delete_button = QPushButton(tr('Удалить'), sidebar)
        self.edit_button.hide()
        self.delete_button.hide()
        self.edit_button.clicked.connect(self.edit_profile)
        self.delete_button.clicked.connect(self.delete_profile)

        self.add_button = QPushButton(tr('+  Новый профиль'))
        self.add_button.setObjectName('sideAddButton')
        self.add_button.clicked.connect(self.add_profile)
        bottom_actions = QVBoxLayout()
        bottom_actions.setSpacing(8)
        bottom_actions.addWidget(self.add_button)
        self.settings_button = QPushButton(tr('Настройки'))
        self.settings_button.setObjectName('sideSettingsButton')
        self.settings_button.setCheckable(True)
        self.settings_button.setAccessibleName(tr('Настройки приложения'))
        self.settings_button.clicked.connect(lambda: self._set_route('home' if self._route == 'settings' else 'settings'))
        bottom_actions.addWidget(self.settings_button)
        side_layout.addLayout(bottom_actions)
        root.addWidget(sidebar)

        scroll = QScrollArea()
        self.content_scroll = scroll
        scroll.setObjectName('contentScroll')
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(scroll, 1)

        body = QWidget()
        body.setObjectName('content')
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(25, 24, 25, 20)
        body_layout.setSpacing(18)
        scroll.setWidget(body)

        self.routes = CurrentPageStack()
        self.routes.setObjectName('appRoutes')
        body_layout.addWidget(self.routes, 1)
        self.home_page = self._build_connections()
        self.routes.addWidget(self.home_page)
        self.settings_page = QWidget()
        self.settings_page.setObjectName('settingsRoute')
        self.routes.addWidget(self.settings_page)
        settings_layout = QVBoxLayout(self.settings_page)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(14)
        heading = QHBoxLayout()
        title = QLabel(tr('Настройки'))
        title.setObjectName('statusTitle')
        heading.addWidget(title)
        heading.addStretch(1)
        self.home_button = QPushButton(tr('На главную'))
        self.home_button.setObjectName('ghostButton')
        self.home_button.clicked.connect(lambda: self._set_route('home'))
        heading.addWidget(self.home_button)
        settings_layout.addLayout(heading)
        self.launch_url_combo = QComboBox(body)
        self.launch_url_combo.hide()
        self.launch_auto_open_check = self._make_switch()
        self.launch_auto_open_check.setParent(body)
        self.launch_auto_open_check.hide()
        self.launch_favicon = QLabel(body)
        self.launch_favicon.hide()

        pivot = QFrame()
        pivot.setObjectName('pivotTabs')
        pivot_layout = QHBoxLayout(pivot)
        pivot_layout.setContentsMargins(0, 0, 0, 0)
        pivot_layout.setSpacing(18)
        self.log_tab_button = QPushButton(tr('Лог консоли'))
        self.log_tab_button.setObjectName('pivotTab')
        self.log_tab_button.setCheckable(True)
        self.settings_tab_button = QPushButton(tr('Настройки клиента'))
        self.settings_tab_button.setObjectName('pivotTab')
        self.settings_tab_button.setCheckable(True)
        self.update_tab_button = QPushButton(tr('Обновление'))
        self.update_tab_button.setObjectName('pivotTab')
        self.update_tab_button.setCheckable(True)
        self.log_tab_button.clicked.connect(lambda: self._set_tab_index(0))
        self.settings_tab_button.clicked.connect(lambda: self._set_tab_index(1))
        self.update_tab_button.clicked.connect(lambda: self._set_tab_index(2))
        pivot_layout.addWidget(self.log_tab_button)
        pivot_layout.addWidget(self.settings_tab_button)
        pivot_layout.addWidget(self.update_tab_button)
        pivot_layout.addStretch(1)
        settings_layout.addWidget(pivot)

        self.tabs = CurrentPageStack()
        self.tabs.setObjectName('contentStack')
        self.log_tab_page = QWidget()
        self.log_tab_page.setObjectName('logsTabPage')
        log_tab_layout = QVBoxLayout(self.log_tab_page)
        log_tab_layout.setContentsMargins(0, 4, 0, 0)
        log_tab_layout.setSpacing(14)
        log_source = QHBoxLayout()
        log_label = QLabel(tr('Подключение'))
        self.log_connection_combo = self._make_combo_box()
        self.log_connection_combo.setAccessibleName(tr('Подключение для журнала'))
        self.log_connection_combo.setMinimumWidth(0)
        self.log_connection_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        log_label.setBuddy(self.log_connection_combo)
        log_source.addWidget(log_label)
        log_source.addWidget(self.log_connection_combo, 1)
        self.log_connection_combo.currentIndexChanged.connect(self._log_connection_selected)
        log_tab_layout.addLayout(log_source)
        self.log_view = QTextEdit()
        self.log_view.setObjectName('logConsole')
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(100)
        self.log_view.setPlaceholderText(tr('Лог sing-box появится здесь после запуска.'))
        log_tab_layout.addWidget(self.log_view, 1)
        self.tabs.addWidget(self.log_tab_page)
        self.tabs.addWidget(self._build_settings_tab())
        self.tabs.addWidget(self._build_update_tab())
        self.legacy_scroll = QScrollArea()
        self.legacy_scroll.setObjectName('legacyToolsScroll')
        self.legacy_scroll.setWidgetResizable(True)
        self.legacy_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.legacy_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.legacy_scroll.setMinimumHeight(100)
        self.legacy_scroll.setWidget(self.tabs)
        settings_layout.addWidget(self.legacy_scroll, 1)
        self._refresh_log_connections()

        self.footer_label = QLabel(f'{APP_NAME} v{get_app_version()} · Windows 11 x64')
        self.footer_label.setObjectName('footerLabel')
        body_layout.addWidget(self.footer_label)
        self._set_tab_index(1)
        self._set_route('home')
        self._compact_layout = None
        scroll.viewport().installEventFilter(self)
        self._update_responsive_layout(scroll.viewport().width())


    def eventFilter(self, watched, event) -> bool:
        if (hasattr(self, '_compact_layout') and watched is self.content_scroll.viewport()
                and event.type() == QEvent.Type.Resize):
            self._update_responsive_layout(event.size().width())
        return super().eventFilter(watched, event)

    def _update_responsive_layout(self, viewport_width: int) -> None:
        compact = viewport_width - 50 < 760
        if self._compact_layout == compact:
            return
        self._compact_layout = compact
        self.settings_cards.setDirection(QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight)
        for index in range(2):
            self.settings_cards.setStretch(index, 0 if compact else 1)
        self.tabs.updateGeometry()


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

    def _set_route(self, route: str) -> None:
        if route not in {'home', 'settings'}:
            raise ValueError(tr('Неизвестная страница'))
        self._route = route
        self.routes.setCurrentIndex(0 if route == 'home' else 1)
        self.settings_button.setChecked(route == 'settings')
        self.settings_button.setProperty('selected', 'true' if route == 'settings' else 'false')
        self.settings_button.style().unpolish(self.settings_button)
        self.settings_button.style().polish(self.settings_button)
        self.content_scroll.verticalScrollBar().setValue(0)
        if route == 'settings':
            self._refresh_log_connections()
            self._refresh_auto_connect_list()
        self.routes.updateGeometry()

    def _refresh_log_connections(self):
        self.log_connection_combo.blockSignals(True)
        self.log_connection_combo.clear()
        views = self.controller.views()
        for view in views:
            profile = self.controller.profiles.get(view.connection.profile_id)
            name = tr('Системное подключение') if view.connection.kind == 'system' else tr('Окно №{0}', view.connection.number)
            self.log_connection_combo.addItem(name + (f' — {profile.name}' if profile else ''), userData=view.connection.id)
        index = self.log_connection_combo.findData(self._log_connection)
        self.log_connection_combo.setCurrentIndex(max(index, 0))
        self._log_connection = str(self.log_connection_combo.currentData())
        self.log_connection_combo.blockSignals(False)

    def _log_connection_selected(self, _index):
        self._log_connection = str(self.log_connection_combo.currentData())
        self.refresh_log()

    def _sync_connection_controls_visibility(self, *_args) -> None:
        return

    def _set_launch_favicon(self, text: str) -> None:
        color = theme_colors()['accent']
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
        value_label = ElidedLabel(value) if title == tr('Профиль:') else QLabel(value)
        value_label.setObjectName('statusMetricValue')
        if title == tr('Профиль:'):
            value_label.setMinimumWidth(90)
            value_label.setMaximumWidth(140)
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
        title_label.setWordWrap(True)
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
        self.settings_cards = cards
        cards.setSpacing(16)

        general = QFrame()
        self.general_settings_card = general
        general.setObjectName('settingsCard')
        general_layout = QGridLayout(general)
        general_layout.setContentsMargins(16, 16, 16, 16)
        general_layout.setHorizontalSpacing(18)
        general_layout.setVerticalSpacing(12)
        general_layout.setColumnStretch(0, 1)
        heading = QLabel(tr('Общие настройки'))
        heading.setObjectName('settingsHeading')
        general_layout.addWidget(heading, 0, 0, 1, 2)

        self.theme_selector = ThemeSelector()
        self.theme_selector.theme_selected.connect(self._remember_theme)
        self.browser_combo = self._make_combo_box()
        self.browser_combo.setFixedWidth(110)
        self.browser_combo.addItem(tr('Авто'), 'auto')
        self.browser_combo.addItem('Chrome', 'chrome')
        self.browser_combo.addItem('Edge', 'edge')
        self.auto_open_check = self._make_switch()
        self._connect_switch(self.auto_open_check, self._remember_auto_open_from_settings)
        self.launch_on_startup_check = self._make_switch()
        self._connect_switch(self.launch_on_startup_check, self._remember_launch_on_startup)
        self.disable_extensions_check = self._make_switch()
        self.stop_existing_check = self._make_switch()
        self.minimize_to_tray_check = self._make_switch()
        self.language_combo = SelectCombo()
        self.language_combo.setObjectName('languageCombo')
        self.language_combo.setFixedWidth(132)
        self.language_combo.addItem('Русский', 'ru')
        self.language_combo.addItem('English', 'en')
        self.language_combo.currentIndexChanged.connect(self._remember_language)

        self._add_setting_row(general_layout, 1, tr('Тема интерфейса'), tr('Применяется сразу и сохраняется автоматически'), self.theme_selector)
        self._add_setting_row(general_layout, 2, tr('Язык интерфейса'), tr('Сохраняется сразу. Применится после перезапуска.'), self.language_combo)
        self._add_setting_row(general_layout, 3, tr('Браузер'), tr('Выберите браузер для запуска\nчерез прокси'), self.browser_combo)
        self._add_setting_row(general_layout, 4, tr('Запускать браузер после подключения'), tr('Открывать браузер сразу после подключения'), self.auto_open_check)
        self._add_setting_row(general_layout, 5, tr('Автозапуск'), tr('Запускать приложение при входе в Windows'), self.launch_on_startup_check)
        self.auto_connect_settings = QWidget()
        self.auto_connect_settings.setObjectName('autoConnectSettings')
        auto_connect_layout = QVBoxLayout(self.auto_connect_settings)
        auto_connect_layout.setContentsMargins(0, 0, 0, 0)
        auto_connect_layout.setSpacing(8)
        auto_connect_layout.addLayout(self._field_caption(tr('Автоподключение'), tr('Выберите подключения для автозапуска с Windows')))
        self.auto_connect_list = QListWidget()
        self.auto_connect_list.setObjectName('autoConnectList')
        self.auto_connect_list.setAccessibleName(tr('Автоподключение'))
        self.auto_connect_list.setAccessibleDescription(tr('Отметьте подключения для автоматического запуска с Windows. Пробел меняет выбор.'))
        self.auto_connect_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.auto_connect_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.auto_connect_list.itemChanged.connect(self._remember_auto_connect_selection)
        auto_connect_layout.addWidget(self.auto_connect_list)
        general_layout.addWidget(self.auto_connect_settings, 6, 0, 1, 2)
        self.auto_connect_settings.hide()
        self._refresh_auto_connect_list()
        self._add_setting_row(general_layout, 7, tr('Отключать расширения браузера'), tr('Запускать Chrome/Edge без расширений'), self.disable_extensions_check)
        self._add_setting_row(general_layout, 8, tr('Сворачивать в трей'), tr('Закрывать окно в системную панель'), self.minimize_to_tray_check)
        cards.addWidget(general, 1)

        proxy = QFrame()
        self.proxy_settings_card = proxy
        proxy.setObjectName('settingsCard')
        proxy_layout = QGridLayout(proxy)
        proxy_layout.setContentsMargins(16, 16, 16, 16)
        proxy_layout.setHorizontalSpacing(12)
        proxy_layout.setVerticalSpacing(10)
        proxy_layout.setColumnStretch(0, 1)
        proxy_layout.setColumnStretch(1, 1)
        proxy_heading = QLabel(tr('Сетевой прокси-сервер'))
        proxy_heading.setObjectName('settingsHeadingAccent')
        proxy_layout.addWidget(proxy_heading, 0, 0, 1, 2)

        self.http_port_spin = QSpinBox()
        self.http_port_spin.setRange(1024, 65535)
        self.http_port_spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.http_port_spin.setAccessibleName(tr('HTTP порт'))
        self.socks_port_spin = QSpinBox()
        self.socks_port_spin.setRange(1024, 65535)
        self.socks_port_spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.socks_port_spin.setAccessibleName(tr('SOCKS5 порт'))
        self.dns_edit = QLineEdit()
        self.dns_edit.setPlaceholderText('1.1.1.1, 8.8.8.8')

        proxy_layout.addLayout(self._field_caption('HTTP Port', tr('Порт локального HTTP сервера')), 1, 0)
        proxy_layout.addLayout(self._field_caption('SOCKS5 Port', tr('Порт локального SOCKS5 сервера')), 1, 1)
        proxy_layout.addWidget(self.http_port_spin, 2, 0)
        proxy_layout.addWidget(self.socks_port_spin, 2, 1)
        proxy_layout.addLayout(self._field_caption(tr('Пользовательский DNS'), tr('DNS-серверы через запятую')), 3, 0, 1, 2)
        proxy_layout.addWidget(self.dns_edit, 4, 0, 1, 2)
        self._add_setting_row(proxy_layout, 5, tr('Останавливать старые сеансы'), tr('Закрывать только сеансы, запущенные Outward App'), self.stop_existing_check)
        proxy_layout.setRowStretch(6, 1)
        cards.addWidget(proxy, 1)
        layout.addLayout(cards)

        layout.addStretch(1)
        save_button = QPushButton(tr('Сохранить настройки'))
        save_button.setObjectName('primaryButton')
        save_button.setFixedHeight(36)
        save_button.clicked.connect(self.save_settings)
        layout.addWidget(save_button, 0, Qt.AlignmentFlag.AlignRight)
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
        update_title = QLabel(tr('Обновление системы'))
        update_title.setObjectName('settingLabel')
        self.update_status_label = QLabel(tr('Текущая версия {0}: {1}. Проверка обновлений будет выполнена при запуске.', APP_NAME, get_app_version()))
        self.update_status_label.setObjectName('mutedLabel')
        self.update_status_label.setWordWrap(True)
        update_copy.addWidget(update_title)
        update_copy.addWidget(self.update_status_label)
        self.auto_update_check = self._make_switch()
        self.auto_update_check.setAccessibleName(tr('Автоматическое обновление приложения'))
        self._connect_switch(self.auto_update_check, self._remember_auto_update)
        auto_update_row = QVBoxLayout()
        auto_update_row.setSpacing(2)
        auto_update_title = QLabel(tr('Автоматическое обновление приложения'))
        auto_update_title.setObjectName('settingLabel')
        auto_update_hint = QLabel(tr('Скачивать новую версию в фоне после проверки'))
        auto_update_hint.setObjectName('mutedLabel')
        auto_update_hint.setWordWrap(True)
        auto_update_row.addWidget(auto_update_title)
        auto_update_row.addWidget(auto_update_hint)
        auto_update_setting = QHBoxLayout()
        auto_update_setting.setSpacing(12)
        auto_update_setting.addLayout(auto_update_row, 1)
        auto_update_setting.addWidget(self.auto_update_check, 0, Qt.AlignTop)
        self.update_button = QPushButton(tr('Проверить обновления'))
        self.update_button.setObjectName('outlineButton')
        self.update_button.clicked.connect(lambda: self.check_for_updates(silent=False))
        self.update_restart_button = QPushButton(tr('Перезапустить и обновить'))
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
        title_label.setWordWrap(True)
        hint_label = QLabel(hint)
        hint_label.setObjectName('mutedLabel')
        hint_label.setWordWrap(True)
        labels.addWidget(title_label)
        labels.addWidget(hint_label)
        return labels

    def _add_setting_row(self, layout: QGridLayout, row: int, title: str, hint: str, control: QWidget) -> None:
        control.setAccessibleName(title)
        control.setAccessibleDescription(hint)
        labels = QVBoxLayout()
        labels.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName('settingLabel')
        title_label.setWordWrap(True)
        labels.addWidget(title_label)
        if hint:
            hint_label = QLabel(hint)
            hint_label.setObjectName('mutedLabel')
            hint_label.setWordWrap(True)
            labels.addWidget(hint_label)
        layout.addLayout(labels, row, 0)
        layout.addWidget(control, row, 1, Qt.AlignmentFlag.AlignRight)

    def _create_tray_icon(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = QIcon(str(asset_path('outward.ico')))
        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip(APP_NAME)
        menu = QMenu(self)
        show_action = QAction(tr('Показать {0}', APP_NAME), self)
        quit_action = QAction(tr('Выход'), self)
        show_action.triggered.connect(self._restore_from_tray)
        quit_action.triggered.connect(self._quit_from_tray)
        menu.addAction(show_action)
        menu.addAction(quit_action)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(lambda reason: self._restore_from_tray() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray_icon.show()

    def _load_settings_to_ui(self) -> None:
        self._loading_settings = True
        self.theme_selector.set_theme(self.settings.theme)
        index = self.browser_combo.findData(self.settings.preferred_browser)
        self.browser_combo.setCurrentIndex(max(index, 0))
        self.http_port_spin.setValue(self.settings.http_port)
        self.socks_port_spin.setValue(self.settings.socks_port)
        self._sync_launch_sites_combo(self.settings.launch_url)
        self.launch_auto_open_check.setChecked(self.settings.auto_open_browser)
        self.auto_open_check.setChecked(self.settings.auto_open_browser)
        self.launch_on_startup_check.setChecked(self.settings.launch_on_startup)
        self.auto_connect_settings.setVisible(self.settings.launch_on_startup)
        self._refresh_auto_connect_list()
        self.disable_extensions_check.setChecked(self.settings.disable_browser_extensions)
        self.stop_existing_check.setChecked(self.settings.stop_existing_sing_box)
        self.minimize_to_tray_check.setChecked(self.settings.minimize_to_tray)
        self.auto_update_check.setChecked(self.settings.auto_update_app)
        language_index = self.language_combo.findData(self.settings.language)
        self.language_combo.setCurrentIndex(max(language_index, 0))
        self.dns_edit.setText(self.settings.custom_dns)
        self.http_port_spin.setToolTip(tr('Порты первоначального окна; новые окна имеют собственные параметры'))
        self.socks_port_spin.setToolTip(self.http_port_spin.toolTip())
        self.auto_open_check.setToolTip(tr('Значение по умолчанию для новых окон; в каждой карточке свой переключатель'))
        self._loading_settings = False

    def save_settings(self) -> None:
        http_port = int(self.http_port_spin.value())
        socks_port = int(self.socks_port_spin.value())
        if http_port == socks_port:
            QMessageBox.warning(self, APP_NAME, tr('HTTP и SOCKS5 должны использовать разные порты.'))
            return
        ports_changed = (http_port, socks_port) != (self.settings.http_port, self.settings.socks_port)
        first = self.controller.collection.windows[0] if self.controller.collection.windows else None
        if ports_changed and first and self._view(first.id).status not in {'offline', 'error'}:
            QMessageBox.information(self, APP_NAME, tr('Сначала отключите окно №{0}, чтобы изменить его порты.', first.number))
            return
        candidate = AppSettings(
            preferred_browser=str(self.browser_combo.currentData()),
            http_port=http_port,
            socks_port=socks_port,
            launch_url=self._current_launch_url(),
            launch_sites=self._launch_sites(),
            auto_open_browser=self.auto_open_check.isChecked(),
            auto_connect_on_startup=self.settings.auto_connect_on_startup,
            launch_on_startup=self.launch_on_startup_check.isChecked(),
            disable_browser_extensions=self.disable_extensions_check.isChecked(),
            stop_existing_sing_box=self.stop_existing_check.isChecked(),
            minimize_to_tray=self.minimize_to_tray_check.isChecked(),
            auto_update_app=self.auto_update_check.isChecked(),
            language=str(self.language_combo.currentData()),
            custom_dns=self.dns_edit.text().strip(),
            theme=self.settings.theme,
        )
        original_ports = (first.http_port, first.socks_port, first.fixed_ports) if first else None
        configured = False
        try:
            if ports_changed and first:
                self.controller.configure(first.id, http_port=http_port, socks_port=socks_port, fixed_ports=True)
                configured = True
            self.store.save_settings(candidate)
        except Exception as exc:
            if configured:
                try:
                    self.controller.configure(first.id, http_port=original_ports[0], socks_port=original_ports[1],
                                              fixed_ports=original_ports[2])
                except Exception:
                    pass
            QMessageBox.warning(self, APP_NAME, sanitize_connection_error(str(exc)))
            return
        self.settings = candidate
        self.controller.settings = self.settings
        self._sync_windows_startup()
        self.status_caption_label.setText(tr('Настройки сохранены.'))

    def _remember_theme(self, name: str) -> None:
        previous = self.settings.theme
        if name == previous:
            return
        try:
            self.store.save_theme(name)
        except Exception as exc:
            self.theme_selector.set_theme(previous)
            QMessageBox.warning(self, APP_NAME, tr('Не удалось сохранить тему.\n\n') + sanitize_connection_error(str(exc)))
            return
        self.settings.theme = name
        theme_manager().apply(name)

    def _remember_language(self, *_args) -> None:
        if getattr(self, '_loading_settings', False):
            return
        language = self.language_combo.currentData()
        previous = self.settings.language
        if language not in {'ru', 'en'} or language == previous:
            return
        try:
            self.store.save_language(language)
        except Exception as exc:
            self.language_combo.blockSignals(True)
            self.language_combo.setCurrentIndex(self.language_combo.findData(previous))
            self.language_combo.blockSignals(False)
            QMessageBox.warning(self, APP_NAME, tr('Не удалось сохранить язык.\n\n') + sanitize_connection_error(str(exc)))
            return
        self.settings.language = language

    def _on_theme_changed(self, name: str) -> None:
        self.theme_selector.set_theme(name)
        cursor = self.log_view.textCursor()
        anchor, position = cursor.anchor(), cursor.position()
        scroll = self.log_view.verticalScrollBar()
        value, at_bottom = scroll.value(), scroll.value() == scroll.maximum()
        self.log_view.setHtml(self._format_log_html(self._last_log_text))
        cursor = self.log_view.textCursor()
        limit = self.log_view.document().characterCount() - 1
        cursor.setPosition(min(anchor, limit))
        cursor.setPosition(min(position, limit), QTextCursor.MoveMode.KeepAnchor)
        self.log_view.setTextCursor(cursor)
        scroll.setValue(scroll.maximum() if at_bottom else value)
        self._set_launch_favicon(self._current_launch_url())
        for button in self.findChildren(LoadingButton):
            if button._loading:
                button._advance_loading_icon()
        self.dark_title_applied = False
        if self.isVisible():
            self._apply_windows_dark_title_bar()
            self.dark_title_applied = True
        for widget in self.findChildren(QWidget):
            widget.update()

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

    def _remember_launch_on_startup(self, *_args) -> None:
        enabled = self.launch_on_startup_check.isChecked()
        self.auto_connect_settings.setVisible(enabled)
        if getattr(self, '_loading_settings', False):
            return
        previous = self.settings.launch_on_startup
        self.settings.launch_on_startup = enabled
        try:
            self.store.save_settings(self.settings)
        except Exception as exc:
            self.settings.launch_on_startup = previous
            self.launch_on_startup_check.blockSignals(True)
            self.launch_on_startup_check.setChecked(previous)
            self.launch_on_startup_check.blockSignals(False)
            self.auto_connect_settings.setVisible(previous)
            QMessageBox.warning(self, APP_NAME, sanitize_connection_error(str(exc)))
            return
        self._sync_windows_startup()

    def _refresh_auto_connect_list(self) -> None:
        if not hasattr(self, 'auto_connect_list'):
            return
        rows = []
        for view in self.controller.views():
            connection = view.connection
            profile = self.controller.profiles.get(connection.profile_id)
            name = tr('Системное подключение') if connection.kind == 'system' else tr('Окно №{0}', connection.number)
            label = f'{name} · {profile.name}' if profile else tr('{0} · выберите профиль на главной', name)
            rows.append((connection.id, label, connection.auto_connect, profile is not None))
        signature = tuple(rows)
        if signature == getattr(self, '_auto_connect_list_signature', None):
            return
        self._auto_connect_list_signature = signature
        current = self.auto_connect_list.currentItem()
        current_id = current.data(Qt.ItemDataRole.UserRole) if current else None
        scroll = self.auto_connect_list.verticalScrollBar().value()
        self.auto_connect_list.blockSignals(True)
        existing_ids = [self.auto_connect_list.item(i).data(Qt.ItemDataRole.UserRole)
                        for i in range(self.auto_connect_list.count())]
        rebuild = existing_ids != [row[0] for row in rows]
        if rebuild:
            self.auto_connect_list.clear()
        for index, (connection_id, label, checked, available) in enumerate(rows):
            item = QListWidgetItem() if rebuild else self.auto_connect_list.item(index)
            item.setText(label)
            item.setData(Qt.ItemDataRole.UserRole, connection_id)
            item.setToolTip(label)
            item.setSizeHint(QSize(0, 28))
            flags = Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable
            if available:
                flags |= Qt.ItemFlag.ItemIsEnabled
            item.setFlags(flags)
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            if rebuild:
                self.auto_connect_list.addItem(item)
            if rebuild and connection_id == current_id:
                self.auto_connect_list.setCurrentItem(item)
        self.auto_connect_list.setFixedHeight(28 * min(4, max(1, len(rows))) + 8)
        self.auto_connect_list.verticalScrollBar().setValue(scroll)
        self.auto_connect_list.blockSignals(False)

    def _remember_auto_connect_selection(self, item: QListWidgetItem) -> None:
        self._auto_connect_list_signature = None
        self._set_connection_autostart(item.data(Qt.ItemDataRole.UserRole), item.checkState() == Qt.CheckState.Checked)
        self._refresh_auto_connect_list()

    def _sync_windows_startup(self) -> None:
        try:
            set_launch_on_startup(self.settings.launch_on_startup)
        except Exception as exc:
            self.status_caption_label.setText(tr('Не удалось обновить автозагрузку Windows.'))
            QMessageBox.warning(self, APP_NAME, tr('Не удалось обновить автозагрузку Windows.\n\n{0}', exc))


    def _connect_on_startup(self) -> None:
        if self._closing or not self._launched_on_startup or not self.settings.launch_on_startup:
            return
        self._launched_on_startup = False
        for view in self.controller.views():
            if view.connection.auto_connect and view.connection.profile_id in self.controller.profiles:
                self.start_connection(view.connection.id, automatic=True)


    def _check_updates_on_startup(self) -> None:
        if not self._closing:
            self.check_for_updates(silent=True)

    def check_for_updates(self, silent: bool = False) -> None:
        if self.update_check_thread is not None:
            return
        self._update_check_silent = silent
        self.update_button.setEnabled(False)
        self.update_restart_button.hide()
        self.update_status_label.setText(tr('Проверяем обновления на GitHub...'))
        # Keep the QThread object in the GUI thread. No worker QObject is
        # destroyed in the background while the GUI is updating Qt widgets.
        self.update_check_thread = self.update_check_worker = UpdateCheckWorker(self.update_manager, self)
        self.update_check_worker.checked.connect(self._on_update_checked)
        self.update_check_worker.failed.connect(self._on_update_check_failed)
        self.update_check_thread.finished.connect(self._on_update_check_finished)
        self.update_check_thread.finished.connect(self.update_check_thread.deleteLater)
        self.update_check_thread.start()

    def _on_update_checked(self, result: object) -> None:
        if not isinstance(result, UpdateCheckResult):
            return
        self.available_update = result.release if result.update_available else None
        self.downloaded_update_installer = None
        if result.update_available and result.release:
            self.update_status_label.setText(tr('Доступна версия {0}. Текущая версия: {1}.', result.latest_version, result.current_version))
            if self.settings.auto_update_app:
                self.download_update(result.release)
            elif not getattr(self, '_update_check_silent', False):
                QMessageBox.information(self, APP_NAME, tr('Доступно обновление {0}. Включите автоматическое обновление, чтобы скачать его в фоне.', result.latest_version))
            return
        self.update_status_label.setText(tr('Установлена последняя версия {0}.', result.current_version))
        if not getattr(self, '_update_check_silent', False):
            QMessageBox.information(self, APP_NAME, tr('Установлена последняя версия приложения.'))

    def _on_update_check_failed(self, message: str) -> None:
        self.update_status_label.setText(tr('Не удалось проверить обновления. Проверьте подключение к GitHub.'))
        if not getattr(self, '_update_check_silent', False):
            QMessageBox.warning(self, APP_NAME, tr('Не удалось проверить обновления.\n\n{0}', message))

    def _on_update_check_finished(self) -> None:
        self.update_check_thread = None
        self.update_check_worker = None
        self.update_button.setEnabled(True)

    def download_update(self, release: UpdateRelease) -> None:
        if self.update_download_thread is not None:
            return
        self.update_button.setEnabled(False)
        self.update_status_label.setText(tr('Скачиваем обновление {0}...', release.version))
        self.update_download_thread = self.update_download_worker = UpdateDownloadWorker(self.update_manager, release, self)
        self.update_download_worker.progress.connect(self._on_update_download_progress)
        self.update_download_worker.downloaded.connect(self._on_update_downloaded)
        self.update_download_worker.failed.connect(self._on_update_download_failed)
        self.update_download_thread.finished.connect(self._on_update_download_finished)
        self.update_download_thread.finished.connect(self.update_download_thread.deleteLater)
        self.update_download_thread.start()

    def _on_update_download_progress(self, downloaded: int, total: int) -> None:
        if total > 0:
            percent = int(downloaded * 100 / total)
            self.update_status_label.setText(tr('Скачиваем обновление... {0}%', percent))
        else:
            megabytes = downloaded / (1024 * 1024)
            self.update_status_label.setText(tr('Скачиваем обновление... {0:.1f} МБ', megabytes))

    def _on_update_downloaded(self, path: object) -> None:
        self.downloaded_update_installer = path if isinstance(path, Path) else Path(str(path))
        self.update_status_label.setText(tr('Обновление загружено и готово к установке.'))
        self.update_restart_button.show()

    def _on_update_download_failed(self, message: str) -> None:
        self.downloaded_update_installer = None
        self.update_status_label.setText(tr('Не удалось скачать обновление.'))
        QMessageBox.warning(self, APP_NAME, tr('Не удалось скачать обновление.\n\n{0}', message))

    def _on_update_download_finished(self) -> None:
        self.update_download_thread = None
        self.update_download_worker = None
        self.update_button.setEnabled(True)

    def install_downloaded_update(self) -> None:
        installer = self.downloaded_update_installer
        if installer is None or not installer.exists():
            QMessageBox.warning(self, APP_NAME, tr('Файл обновления не найден. Проверьте обновления еще раз.'))
            return
        if QMessageBox.question(self, tr('Обновить {0}', APP_NAME), tr('Приложение остановит подключения, установит обновление и запустится снова. Продолжить?')) != QMessageBox.StandardButton.Yes:
            return
        def install_after_shutdown():
            try:
                subprocess.Popen([str(installer), '/SILENT', '/NORESTART'], cwd=str(installer.parent), close_fds=True)
            except Exception as exc:
                QMessageBox.critical(self, APP_NAME, tr('Не удалось запустить установщик.\n\n{0}', exc))
                return
            self.force_quit = True
            self.close()
        self._shutdown_connections(install_after_shutdown)


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
        has_profiles = bool(self.profiles)
        self.empty_profiles.setVisible(not has_profiles)
        self.profile_list.setVisible(has_profiles)
        self.add_button.setVisible(has_profiles)
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

        flag = CountryFlagBadge(self._profile_country_code(profile))
        layout.addWidget(flag)

        copy = QVBoxLayout()
        copy.setSpacing(0)
        name = ElidedLabel(profile.name)
        name.setObjectName('profileName')
        protocol = QLabel(protocol_label_for_link(profile.link))
        protocol.setObjectName('profileProtocol')
        copy.addWidget(name)
        copy.addWidget(protocol)
        layout.addLayout(copy, 1)
        menu_button = MenuButton()
        menu_button.setObjectName('profileMenuButton')
        menu_button.setFixedSize(24, 28)
        menu_button.setToolTip(tr('Изменить или удалить профиль'))
        menu_button.setAccessibleName(tr('Действия с профилем {0}', profile.name))
        menu_button.clicked.connect(lambda _checked=False: self._open_profile_menu(profile.id, menu_button))
        layout.addWidget(menu_button)
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
        if item is None or self.connect_thread is not None or self.disconnect_thread is not None:
            return
        self.profile_list.setCurrentItem(item)
        self._profile_menu(self.profile_list.mapToGlobal(position))

    def _open_profile_menu(self, profile_id: str, button: QPushButton) -> None:
        if self.connect_thread is not None or self.disconnect_thread is not None:
            return
        for index in range(self.profile_list.count()):
            item = self.profile_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == profile_id:
                self.profile_list.setCurrentItem(item)
                self._profile_menu(button.mapToGlobal(button.rect().bottomLeft()))
                break

    def _profile_menu(self, position) -> None:
        menu = QMenu(self)
        edit_action = QAction(tr('Изменить'), menu)
        delete_action = QAction(tr('Удалить'), menu)
        edit_action.setEnabled(self.edit_button.isEnabled())
        delete_action.setEnabled(self.delete_button.isEnabled())
        edit_action.triggered.connect(self.edit_profile)
        delete_action.triggered.connect(self.delete_profile)
        menu.addAction(edit_action)
        menu.addAction(delete_action)
        try:
            menu.exec(position)
        finally:
            menu.deleteLater()
    def _sync_profile_buttons(self) -> None:
        selected = self.current_profile() is not None
        self.edit_button.setEnabled(selected)
        self.delete_button.setEnabled(selected)
        self._refresh_profile_item_selection()
        self._sync_connections_profiles()




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
        uses = [v for v in self.controller.views() if v.connection.profile_id == profile.id]
        if any(v.status not in {'offline', 'error'} or self.controller.entries[v.connection.id].manager is not None for v in uses):
            QMessageBox.information(self, APP_NAME, tr('Сначала отключите подключения, использующие этот профиль.'))
            return
        text = tr('Удалить профиль {0}?', profile.name)
        if uses:
            text += tr('\nДля связанных окон потребуется выбрать новый профиль.')
        if QMessageBox.question(self, tr('Удалить профиль'), text) == QMessageBox.StandardButton.Yes:
            for view in uses:
                self.controller.configure(view.connection.id, profile_id='', auto_connect=False)
            self.store.delete_profile(profile.id)
            self._load_profiles()


    def connect_profile(self) -> None:
        self.add_connection_window()






















    def _update_session_time(self) -> None:
        self.dashboard.tick()
















    def refresh_log(self) -> None:
        if self._log_connection == 'system':
            self._background('system-log', lambda: self.controller.log_text('system'), self._system_log_received)
            return
        text = self.controller.log_text(self._log_connection)
        self._render_log_text(text)

    def _system_log_received(self, text, error):
        if self._log_connection == 'system':
            self._render_log_text(error or text or '')

    def _render_log_text(self, text: str) -> None:
        if text != self._last_log_text:
            self._last_log_text = text
            self.log_view.setHtml(self._format_log_html(text))
            self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())


    def _format_log_html(self, text: str) -> str:
        colors = theme_colors()
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
        body = ''.join(rows) or tr('<span class="time">Лог sing-box появится здесь после запуска.</span>')
        return f"""
        <html><head><style>
        body {{ background: {colors['input']}; color: {colors['text']}; font-family: 'Cascadia Mono', Consolas, monospace; font-size: 12px; }}
        div {{ white-space: pre-wrap; line-height: 1.35; }}
        .time {{ color: {colors['muted']}; }}
        .level {{ font-weight: 700; }}
        .info {{ color: {colors['muted']}; }}
        .warn, .warning {{ color: {colors['warning']}; }}
        .error {{ color: {colors['error']}; }}
        .debug, .trace, .plain {{ color: {colors['muted']}; }}
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
        self.close()


    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self.dark_title_applied:
            self._apply_windows_dark_title_bar()
            self.dark_title_applied = True

    def _apply_windows_dark_title_bar(self) -> None:
        self.sync_native_theme()

    def closeEvent(self, event) -> None:
        if self._close_ready:
            if self.tray_icon:
                self.tray_icon.hide()
            event.accept()
            # A window already hidden in the tray does not trigger Qt's
            # lastWindowClosed exit. All cleanup has completed at this point.
            QApplication.instance().quit()
            return
        self.save_settings()
        if not self.force_quit and self.settings.minimize_to_tray and self.tray_icon:
            self.hide()
            event.ignore()
            return
        event.ignore()
        if not self._closing:
            self.force_quit = True
            self._shutdown_connections(self.close)
