from __future__ import annotations

from outward_app.ui.i18n import tr, traffic_text

from html import escape
import time
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                              QPushButton, QScrollArea, QSizePolicy, QToolTip, QVBoxLayout, QWidget)

from outward_app.core.connections import protocol_label_for_link
from outward_app.core.sessions import SessionView
from outward_app.core.countries import country_label, guess_country_code
from outward_app.ui.country_flags import country_icon
from outward_app.ui.widgets import MenuButton, PlusButton, SelectCombo
from outward_app.ui.themes import theme_color
from outward_app.ui.system_mode import SystemModeSelector


STATUS = {"offline": "Выключено", "preparing": "Подготовка…", "connecting": "Подключение…",
          "connected": "Подключено", "reconnecting": "Переподключение…", "stopping": "Отключение…", "error": "Ошибка"}
WINDOW_CARD_WIDTH = 260


class ErrorIndicator(QWidget):
    """Small vector warning with the full error in a native hover tooltip."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(18, 22)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAccessibleName(tr('Ошибка окна'))
        self.hide()

    def set_error(self, text):
        self.setToolTip('<qt>' + escape(text).replace('\n', '<br>') + '</qt>' if text else '')
        self.setAccessibleDescription(text)
        self.setVisible(bool(text))

    def focusInEvent(self, event):
        super().focusInEvent(event)
        # Qt dismisses tooltips during focus/activation dispatch; show after it.
        QTimer.singleShot(0, self._show_focused_tooltip)
        self.update()

    def _show_focused_tooltip(self):
        if self.hasFocus() and self.isVisible():
            QToolTip.showText(self.mapToGlobal(self.rect().bottomLeft()), self.toolTip(), self)

    def focusOutEvent(self, event):
        QToolTip.hideText()
        super().focusOutEvent(event)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        triangle = QPainterPath()
        triangle.moveTo(9, 3)
        triangle.lineTo(17, 17)
        triangle.lineTo(1, 17)
        triangle.closeSubpath()
        color = theme_color('error')
        painter.setPen(QPen(color, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(color)
        painter.drawPath(triangle)
        painter.setPen(QPen(theme_color('panel'), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(9, 8), QPointF(9, 11.5))
        painter.drawPoint(QPointF(9, 14.5))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(theme_color('focus'), 1, Qt.PenStyle.DotLine))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 2, 2)
        painter.end()


class ResourceCombo(SelectCombo):
    """Launch resource selection shares the standard single-select behavior."""


class ProfileButton(QPushButton):
    def set_profile_text(self, text):
        self.full_text = text
        self._elide()

    def _elide(self):
        self.setText(self.fontMetrics().elidedText(getattr(self, 'full_text', ''),
                     Qt.TextElideMode.ElideRight, max(0, self.width() - 4)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()


class PowerButton(QPushButton):
    """One stable power affordance; the rotating arc also remains cancellable."""
    def __init__(self):
        super().__init__()
        self.setObjectName('connectionPower')
        self.setProperty('keyboardFocus', False)
        self.setFixedSize(36, 36)
        self.connected, self.busy, self.angle = False, False, 0
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._advance)

    def _set_keyboard_focus(self, visible):
        self.setProperty('keyboardFocus', visible)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def focusInEvent(self, event):
        if event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
                              Qt.FocusReason.ShortcutFocusReason):
            self._set_keyboard_focus(True)
        elif event.reason() == Qt.FocusReason.MouseFocusReason:
            self._set_keyboard_focus(False)
        super().focusInEvent(event)

    def mousePressEvent(self, event):
        self._set_keyboard_focus(False)
        super().mousePressEvent(event)

    def set_state(self, state):
        connected_changed = self.connected != (state == 'connected')
        self.connected = state == 'connected'
        self.setProperty('connected', self.connected)
        if connected_changed:
            self.style().unpolish(self)
            self.style().polish(self)
        self.busy = state in {'preparing', 'connecting', 'reconnecting', 'stopping'}
        action = tr('Отменить подключение') if self.busy else tr('Отключить') if self.connected else tr('Повторить подключение') if state == 'error' else tr('Подключить')
        if state == 'stopping':
            action = tr('Отключение…')
        self.setAccessibleName(action)
        self.setToolTip(action)
        self.setAccessibleDescription(tr(STATUS[state]))
        if self.busy and self.isVisible():
            self.timer.start()
        else:
            self.timer.stop()
        self.update()

    def _advance(self):
        self.angle = (self.angle + 12) % 360
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if self.busy:
            self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = theme_color('success' if self.connected else 'accent' if self.busy else 'muted')
        painter.setPen(QPen(color, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        center = QRectF(self.rect()).center()
        ring = QRectF(center.x() - 10, center.y() - 10, 20, 20)
        if self.busy:
            painter.drawArc(ring, -self.angle * 16, 270 * 16)
        else:
            painter.drawArc(ring, 135 * 16, 270 * 16)
            painter.drawLine(QPointF(center.x(), center.y() - 10), QPointF(center.x(), center.y() - 2))
        painter.end()


class ConnectionFlag(QLabel):
    def __init__(self, compact=False):
        super().__init__()
        self.flag_size = QSize(24, 18) if compact else QSize(40, 30)
        self.setFixedSize(QSize(28, 20) if compact else QSize(40, 40))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._state = None

    def set_country(self, code, connected):
        ratio = self.devicePixelRatioF()
        if self._state == (code, connected, ratio):
            return
        self._state = code, connected, ratio
        self.colored = connected
        self.country_code = code
        description = country_label(code) if code else tr('Страна не определена')
        self.setToolTip(description)
        self.setAccessibleName(description)
        pixmap = country_icon(code).pixmap(self.flag_size * ratio)
        if not connected:
            source = pixmap.toImage()
            for y in range(source.height()):
                for x in range(source.width()):
                    color = source.pixelColor(x, y)
                    gray = round(.299 * color.red() + .587 * color.green() + .114 * color.blue())
                    source.setPixelColor(x, y, QColor(gray, gray, gray, color.alpha()))
            pixmap = QPixmap.fromImage(source)
        pixmap.setDevicePixelRatio(ratio)
        self.setPixmap(pixmap)


class ConnectionCard(QFrame):
    action = Signal(str)
    profile_requested = Signal(str)
    menu_requested = Signal(str)
    browser_requested = Signal(str)
    sites_requested = Signal(str)
    launch_changed = Signal(str, str)
    auto_changed = Signal(str, bool)

    def __init__(self, view: SessionView, profiles, sites, switch_factory=QCheckBox, parent=None):
        super().__init__(parent)
        self.connection_id = view.connection.id
        self.system = view.connection.kind == "system"
        self.setObjectName("statusPanel" if self.system else "connectionCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.view = view
        self.profiles = profiles
        self._local_message = ''
        self._render_key = None
        self.browser_pending = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16 if self.system else 12, 12, 16 if self.system else 12, 12)
        outer.setSpacing(8)
        header = QGridLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setHorizontalSpacing(10)
        header.setVerticalSpacing(4)
        logo = ConnectionFlag(compact=self.system)
        self.logo = logo
        if not self.system:
            header.addWidget(logo, 0, 0, 2, 1)
        title_row = QHBoxLayout()
        title_row.setSpacing(7 if self.system else 4)
        self.dot = QLabel("●")
        self.dot.setObjectName("statusDot")
        self.title = QLabel()
        self.title.setObjectName("statusTitle")
        self.title.setWordWrap(True)
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        title_row.addWidget(self.dot)
        self.dot.hide()
        title_row.addWidget(self.title, 1 if self.system else 0)
        self.error_indicator = ErrorIndicator(self)
        if not self.system:
            title_row.addWidget(self.error_indicator)
            title_row.addStretch(1)
        self.status = QLabel(self)
        self.status.setObjectName("connectionState")
        self.status.hide()
        header.addLayout(title_row, 0, 0 if self.system else 1)
        self.action_button = PowerButton()
        self.action_button.clicked.connect(lambda: self.action.emit(self.connection_id))
        self.menu_button = MenuButton()
        self.menu_button.setObjectName("iconButton")
        self.menu_button.setFixedSize(28, 28)
        self.menu_button.setAccessibleName(tr('Параметры системного подключения') if self.system else tr('Параметры окна №{0}', view.connection.number))
        self.menu_button.setToolTip(self.menu_button.accessibleName())
        self.menu_button.clicked.connect(lambda: self.menu_requested.emit(self.connection_id))
        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        for button in (self.menu_button, self.action_button):
            buttons.addWidget(button)
        header.addLayout(buttons, 0, 2, 1 if self.system else 2, 1)
        self.profile_button = ProfileButton()
        self.profile_button.setObjectName("connectionProfile")
        self.profile_button.setMinimumWidth(0)
        self.profile_button.setMaximumWidth(16777215)
        self.profile_button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.profile_button.clicked.connect(lambda: self.profile_requested.emit(self.connection_id))
        self.session_label = QLabel(tr('Сессия: —'))
        self.session_label.setObjectName("connectionMetadata")
        self.ping_label = QLabel("Ping: —")
        self.ping_label.setObjectName("connectionMetadata")
        self.traffic = QLabel()
        self.traffic.setObjectName('connectionPorts' if not self.system else 'connectionMetadata')
        self.traffic.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if self.system:
            self.protocol = QLabel()
            self.protocol.setObjectName('systemProtocol')
        header.setColumnStretch(0 if self.system else 1, 1)
        outer.addLayout(header)
        if self.system:
            mode_row = QHBoxLayout()
            mode_row.setContentsMargins(0, 0, 0, 0)
            self.mode_selector = SystemModeSelector(self)
            mode_row.addWidget(self.mode_selector)
            mode_row.addStretch(1)
            outer.addLayout(mode_row)
            metadata = QGridLayout()
            metadata.setContentsMargins(0, 0, 0, 0)
            metadata.setHorizontalSpacing(18)
            metadata.setVerticalSpacing(4)
            profile_row = QHBoxLayout()
            profile_row.setSpacing(6)
            profile_row.addWidget(logo)
            profile_row.addWidget(self.profile_button, 1)
            profile_row.addWidget(self.protocol)
            profile_row.addStretch()
            for column, (caption, value) in enumerate((
                (tr('Профиль'), None), (tr('Задержка'), self.ping_label),
                (tr('Сессия'), self.session_label), (tr('Трафик'), self.traffic),
            )):
                label = QLabel(caption)
                label.setObjectName('connectionMetadata')
                metadata.addWidget(label, 0, column)
                if value is None:
                    metadata.addLayout(profile_row, 1, column)
                else:
                    value.setObjectName('systemMetricValue')
                    metadata.addWidget(value, 1, column)
                if column == 1:
                    self.ping_caption = label
                metadata.setColumnStretch(column, 2 if column == 0 else 1)
            outer.addLayout(metadata)
        self.message = QLabel()
        self.message.setObjectName("connectionMessage")
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.hide()
        if not self.system:
            outer.addWidget(self.profile_button)
            outer.addWidget(self.message)
            port_row = QGridLayout()
            port_row.setHorizontalSpacing(8)
            port_row.setVerticalSpacing(8)
            port_row.setColumnStretch(0, 1)
            port_row.setColumnStretch(1, 1)
            port_row.addWidget(self.session_label, 0, 0)
            port_row.addWidget(self.ping_label, 0, 1)
            self.http = QLabel()
            self.socks = QLabel()
            self.protocol = QLabel()
            for label in (self.http, self.socks, self.protocol):
                label.setObjectName("connectionPorts")
                label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                label.setWordWrap(True)
                label.setMinimumWidth(0)
                label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            port_row.addWidget(self.http, 1, 0)
            port_row.addWidget(self.socks, 1, 1)
            port_row.addWidget(self.protocol, 2, 0)
            port_row.addWidget(self.traffic, 2, 1)
            outer.addLayout(port_row)
            divider = QFrame()
            divider.setObjectName('connectionDivider')
            divider.setFixedHeight(1)
            outer.addWidget(divider)
            self.browser_row = QGridLayout()
            self.browser_row.setContentsMargins(0, 0, 0, 0)
            self.browser_row.setHorizontalSpacing(8)
            self.browser_row.setVerticalSpacing(6)
            self.open_browser = QPushButton(tr('Открыть браузер'))
            self.open_browser.setObjectName("primaryButton")
            self.open_browser.setFixedHeight(34)
            self.open_browser.clicked.connect(lambda: self.browser_requested.emit(self.connection_id))
            self.url = ResourceCombo()
            self.url.setObjectName("launchCombo")
            self.url.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            self.url.setMinimumWidth(0)
            self.url.setFixedHeight(34)
            self.url.setAccessibleName(tr('Ресурс для окна №{0}', view.connection.number))
            self.url.currentTextChanged.connect(lambda text: self.launch_changed.emit(self.connection_id, text))
            self.auto = switch_factory()
            self.auto.setAccessibleName(tr('Открыть браузер после подключения окна №{0}', view.connection.number))
            self.auto.setToolTip(tr('Открывать выбранный ресурс после подключения этого окна'))
            self.auto.toggled.connect(lambda value: self.auto_changed.emit(self.connection_id, value))
            self.auto_group = QWidget()
            self.auto_group.setObjectName("connectionAutoGroup")
            group_layout = QHBoxLayout(self.auto_group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(6)
            group_layout.addWidget(self.auto)
            hint = QLabel(tr('Открыть после запуска'))
            hint.setObjectName("launchHint")
            hint.setBuddy(self.auto)
            group_layout.addWidget(hint)
            self.sites = PlusButton()
            self.sites.setObjectName("launchManageButton")
            self.sites.setFixedSize(34, 34)
            self.sites.setAccessibleName(tr('Ресурсы запуска окна №{0}', view.connection.number))
            self.sites.setToolTip(tr('Ресурсы запуска'))
            self.sites.clicked.connect(lambda: self.sites_requested.emit(self.connection_id))
            outer.addLayout(self.browser_row)
            self.browser_row.addWidget(self.open_browser, 0, 0, 1, 2)
            self.browser_row.addWidget(self.url, 1, 0)
            self.browser_row.addWidget(self.sites, 1, 1)
            self.browser_row.addWidget(self.auto_group, 2, 0, 1, 2)
            self.browser_row.setColumnStretch(0, 1)
            self.set_sites(sites)
            self.setFixedWidth(WINDOW_CARD_WIDTH)
        else:
            outer.addWidget(self.message)
        self.render(view, profiles)

    def show_error(self, text):
        self._local_message = text
        self.render(self.view)

    def clear_error(self):
        self._local_message = ''
        self.render(self.view)

    def set_browser_pending(self, pending):
        self.browser_pending = pending
        self.render(self.view)

    def set_sites(self, sites):
        if self.system:
            return
        selected = self.view.connection.launch_url
        self.url.blockSignals(True)
        self.url.clear()
        self.url.addItems(list(dict.fromkeys([*sites, selected])))
        self.url.setCurrentText(selected)
        self.url.blockSignals(False)

    def render(self, view, profiles=None):
        self.view = view
        if profiles is not None:
            self.profiles = profiles
        connection, state = view.connection, view.status
        key = view.generation, state, connection.profile_id, connection.system_mode
        if key != self._render_key:
            self._local_message = ''
        self._render_key = key
        profile = self.profiles.get(connection.profile_id)
        profile_name = view.runtime.profile_name if view.runtime else (profile.name if profile else tr('Выбрать профиль'))
        self.profile_button.set_profile_text(profile_name if self.system else tr('Профиль: ') + profile_name)
        if self.system:
            self.profile_button.ensurePolished()
            self.profile_button.setMaximumWidth(self.profile_button.fontMetrics().horizontalAdvance(profile_name) + 4)
        self.profile_button.setToolTip(profile_name)
        self.profile_button.setAccessibleName((tr('Профиль системы: ') if self.system else tr('Профиль окна №{0}: ', connection.number)) + profile_name)
        self.title.setText(tr('Системное подключение') if self.system else tr('Окно №{0}', connection.number))
        code = (view.runtime.country_code if view.runtime else profile.country_code if profile else '')
        code = code or guess_country_code(profile_name, profile.remark if profile else '', profile.server if profile else '')
        self.logo.set_country(code, self.system or state == 'connected')
        self.status.setText(tr(STATUS[state]))
        self.setAccessibleDescription(tr(STATUS[state]))
        self.dot.setToolTip(tr(STATUS[state]))
        self.dot.setAccessibleName(tr('Состояние подключения: ') + tr(STATUS[state]))
        self.status.setProperty("active", state == "connected")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.dot.setProperty("connected", "true" if state == "connected" else ("error" if state == "error" else
                              "pending" if state in {"connecting", "preparing", "reconnecting"} else "false"))
        self.dot.style().unpolish(self.dot)
        self.dot.style().polish(self.dot)
        self.action_button.set_state(state)
        self.action_button.setEnabled(state != "stopping")
        self.profile_button.setEnabled(state in {"offline", "error"})
        if self.system:
            self.mode_selector.set_mode(connection.system_mode)
            self.mode_selector.setEnabled(state in {'offline', 'error'})
        message = tr(self._local_message or (view.message if self.system or state in {'error', 'connected', 'reconnecting'} else ''))
        is_error = state == 'error' or bool(self._local_message)
        self.error_indicator.set_error((message or tr('Ошибка подключения')) if not self.system and is_error else '')
        inline_message = message if self.system or not is_error else ''
        self.message.setText(inline_message)
        self.message.setVisible(bool(inline_message))
        self.message.setProperty("error", is_error)
        self.message.style().unpolish(self.message)
        self.message.style().polish(self.message)
        self.traffic.setText(traffic_text(view.traffic_bytes) if self.system else
                             tr('Трафик: <span style="font-weight:600">{0}</span>', traffic_text(view.traffic_bytes)))
        self.traffic.setToolTip(tr('Входящий и исходящий трафик за текущий календарный месяц (') + view.traffic_month + tr(').\nУчёт ведётся с момента обновления приложения. ') + tr(view.traffic_error))
        self.traffic.setAccessibleName(tr('Трафик за текущий месяц: ') + traffic_text(view.traffic_bytes))
        metric = 'HTTPS' if view.latency_kind == 'https' else 'Ping'
        if state != 'connected':
            value = '—'
        elif view.latency_pending:
            value = '…'
        else:
            value = tr('{0} мс', view.latency) if view.latency is not None else tr('нет ответа')
        self.ping_label.setText(value if self.system else f'{metric}: {value}')
        self.ping_label.setAccessibleName(f'{metric}: {value}')
        if self.system:
            self.ping_caption.setText('HTTPS' if view.latency_kind == 'https' else tr('Задержка'))
        self.ping_label.setToolTip(tr('Время полного HTTPS-запроса через подключение. Для UDP-сервера WireGuard TCP-пинг неприменим.')
                                  if view.latency_kind == 'https' else
                                  tr('TCP-пинг до сервера профиля через внешний интерфейс, без DNS, TLS и HTTP. Измеряется после подключения и каждые 5 секунд; отсутствие ответа не отключает VPN.'))
        if self.system:
            protocol = view.runtime.protocol_label if view.runtime else protocol_label_for_link(profile.link) if profile else '—'
            self.protocol.setTextFormat(Qt.TextFormat.PlainText)
            self.protocol.setText(protocol)
            self.protocol.setToolTip(tr('Протокол подключения: ') + protocol)
            self.protocol.setAccessibleName(tr('Протокол подключения: ') + protocol)
        if not self.system:
            http = view.runtime.http_port if view.runtime else connection.http_port
            socks = view.runtime.socks_port if view.runtime else connection.socks_port
            protocol = view.runtime.protocol_label if view.runtime else protocol_label_for_link(profile.link) if profile else "—"
            for label, name, value in ((self.http, "HTTP", str(http)), (self.socks, "SOCKS5", str(socks)),
                                       (self.protocol, tr('Протокол'), protocol)):
                from html import escape
                label.setText(f'{name}: <span style="font-weight:600">{escape(value)}</span>')
            self.http.setToolTip(f"http://127.0.0.1:{http}")
            self.socks.setToolTip(f"socks5://127.0.0.1:{socks}")
            self.open_browser.setEnabled(state == "connected" and view.runtime is not None and not self.browser_pending)
            self.open_browser.setToolTip(tr('Использует SOCKS5-порт именно этого окна') if state == "connected" else tr('Сначала подключите это окно'))
            self.auto.blockSignals(True)
            self.auto.setChecked(connection.auto_open_browser)
            self.auto.blockSignals(False)
            if self.url.currentText() != connection.launch_url:
                self.url.blockSignals(True)
                self.url.setCurrentText(connection.launch_url)
                self.url.blockSignals(False)
        self.tick()

    def tick(self):
        seconds = max(0, int(time.monotonic() - self.view.connected_at)) if self.view.status == "connected" else 0
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        value = f'{hours:02}:{minutes:02}:{seconds:02}' if self.view.status == 'connected' else '—'
        self.session_label.setText(value if self.system else tr('Сессия: ') + value)
        self.session_label.setAccessibleName(tr('Сессия: ') + value)


class WindowsList(QWidget):
    resized = Signal()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()


class ConnectionsDashboard(QWidget):
    def heightForWidth(self, width):
        # Only the pinned controls impose a required height. The windows area
        # must be allowed to shrink and scroll instead of scrolling the page.
        layout = self.layout()
        margins = layout.contentsMargins()
        inner_width = max(0, width - margins.left() - margins.right())
        system_height = max(self.system.minimumSizeHint().height(), self.system.heightForWidth(inner_width))
        return (margins.top() + margins.bottom() + system_height
                + layout.itemAt(1).minimumSize().height() + self.scroll.minimumHeight()
                + 2 * layout.spacing())

    def __init__(self, views, profiles, sites, switch_factory, parent=None):
        super().__init__(parent)
        self.setObjectName("connectionsDashboard")
        self.cards = {}
        self.profiles, self.sites, self.switch_factory = profiles, sites, switch_factory
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.system = ConnectionCard(next(v for v in views if v.connection.kind == "system"), profiles, sites, switch_factory)
        layout.addWidget(self.system)
        toolbar = QHBoxLayout()
        title = QLabel(tr('Окна подключения'))
        title.setObjectName("settingLabel")
        self.add = QPushButton(tr('+ Добавить окно'))
        self.add.setObjectName("outlineButton")
        toolbar.addWidget(title)
        toolbar.addStretch(1)
        toolbar.addWidget(self.add)
        layout.addLayout(toolbar)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("windowsScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMinimumHeight(90)
        inner = WindowsList()
        inner.setObjectName("windowsList")
        self.rows = QGridLayout(inner)
        self.rows.setContentsMargins(0, 0, 5, 0)
        self.rows.setSpacing(12)
        self.rows.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.empty = QLabel(tr('Добавьте окно, чтобы получить отдельные HTTP- и SOCKS5-порты.'))
        self.empty.setObjectName("mutedLabel")
        self.empty.setWordWrap(True)
        self.rows.addWidget(self.empty, 0, 0)
        inner.resized.connect(self._arrange_cards)
        self.scroll.setWidget(inner)
        layout.addWidget(self.scroll, 1)
        for view in views:
            if view.connection.kind == "window":
                self.insert(view)

    def insert(self, view):
        card = ConnectionCard(view, self.profiles, self.sites, self.switch_factory)
        self.cards[view.connection.id] = card
        self._arrange_cards()
        self.empty.hide()
        return card

    def _arrange_cards(self):
        while self.rows.count():
            self.rows.takeAt(0)
        columns = max(1, (self.scroll.viewport().width() - 5 + 12) // (WINDOW_CARD_WIDTH + 12))
        if not self.cards:
            self.rows.addWidget(self.empty, 0, 0)
        for index, card in enumerate(self.cards.values()):
            self.rows.addWidget(card, index // columns, index % columns, Qt.AlignmentFlag.AlignTop)

    def update_view(self, view):
        if view.connection.kind == "system":
            card = self.system
        else:
            card = self.cards.get(view.connection.id)
        if card:
            card.render(view, self.profiles)

    def remove(self, connection_id):
        card = self.cards.pop(connection_id)
        self.rows.removeWidget(card)
        card.deleteLater()
        self._arrange_cards()
        self.empty.setVisible(not self.cards)

    def tick(self):
        for card in [self.system, *self.cards.values()]:
            card.tick()
