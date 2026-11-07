"""UI orchestration for the dashboard. Existing settings/update widgets remain in MainWindow."""
from __future__ import annotations

from outward_app.ui.i18n import tr

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QMessageBox

from outward_app.app_info import APP_NAME
from outward_app.core.browser import open_url_with_proxy
from outward_app.core.connections import sanitize_connection_error
from outward_app.core.sessions import SessionController
from outward_app.ui.connection_card import ConnectionsDashboard
from outward_app.ui.connection_dialog import ConnectionDialog
from outward_app.ui.dialogs import LaunchSitesDialog


class SessionEvents(QObject):
    changed = Signal(object)


class ConnectionsUi:
    def _init_connections(self):
        self.session_events = SessionEvents(self)
        self.session_events.changed.connect(self._on_session_changed)
        self.controller = SessionController(self.store, self.settings, self.profiles, self.session_events.changed.emit)
        self._jobs = {}
        self._job_callbacks = {}
        # No Python-backed QObject is created/deleted in a worker thread. Its
        # destructor can wait for the GIL while holding a Qt signal mutex that
        # the GUI needs during setHtml(), permanently deadlocking both threads.
        self._background_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='outward-ui')
        self._background_timer = QTimer(self)
        self._background_timer.setInterval(50)
        self._background_timer.timeout.connect(self._collect_background_results)
        self._pending_reconfigure = {}
        self._pending_remove = set()
        self._browser_starts = set()
        self._log_connection = self.controller.collection.windows[0].id if self.controller.collection.windows else "system"
        self._closing = False
        self._close_ready = False

    def _build_connections(self):
        self.dashboard = ConnectionsDashboard(self.controller.views(), self.controller.profiles,
                                              self.settings.launch_sites, self._make_switch, self)
        self.dashboard.add.clicked.connect(self.add_connection_window)
        for card in [self.dashboard.system, *self.dashboard.cards.values()]:
            self._wire_card(card)
        # Existing status/caption references used by unchanged settings/update code.
        self.status_caption_label = self.dashboard.system.message
        self.status_title_label = self.dashboard.system.title
        self.status_profile_value = self.dashboard.system.profile_button
        self.connect_button = self.dashboard.system.action_button
        self.session_value = self.dashboard.system.session_label
        self.latency_value = self.dashboard.system.ping_label
        self.status_dot = self.dashboard.system.dot
        return self.dashboard

    def _wire_card(self, card):
        card.action.connect(self._connection_action)
        card.profile_requested.connect(self.edit_connection)
        card.menu_requested.connect(self.connection_menu)
        card.browser_requested.connect(self.open_connection_browser)
        card.sites_requested.connect(self.manage_window_sites)
        card.launch_changed.connect(lambda cid, url: self._configure_connection(cid, launch_url=url))
        card.auto_changed.connect(lambda cid, checked: self._configure_connection(cid, auto_open_browser=checked))
        if card.system:
            card.mode_selector.mode_selected.connect(self._system_mode_changed)

    def _system_mode_changed(self, mode):
        view = self._view('system')
        if view and view.connection.system_mode != mode:
            if not self._configure_connection('system', system_mode=mode):
                self.dashboard.system.render(self._view('system'))

    def _background(self, key, function, callback):
        if key in self._jobs:
            return
        self._jobs[key] = self._background_pool.submit(function)
        self._job_callbacks[key] = callback
        self._background_timer.start()

    def _collect_background_results(self):
        # The GUI owns job bookkeeping and all callbacks. Workers only execute
        # ordinary Python functions; they never emit Qt signals or destroy Qt objects.
        for key, future in list(self._jobs.items()):
            # A callback may open a modal dialog and re-enter the Qt event loop.
            if self._jobs.get(key) is not future or not future.done():
                continue
            del self._jobs[key]
            try:
                value, error = future.result(), ''
            except Exception as exc:
                value, error = None, sanitize_connection_error(str(exc))
            self._background_result(key, value, error)
        if not self._jobs:
            self._background_timer.stop()

    def _background_result(self, key, value, error):
        callback = self._job_callbacks.pop(key, None)
        if callback:
            callback(value, error)

    def _view(self, connection_id):
        return next((v for v in self.controller.views() if v.connection.id == connection_id), None)

    def _connection_action(self, connection_id):
        view = self._view(connection_id)
        if view is None:
            return
        if view.status in {"connected", "connecting", "preparing", "reconnecting"}:
            self._browser_starts.discard(connection_id)
            self.controller.stop(connection_id)
        elif view.status in {"offline", "error"}:
            if not self.controller.profiles.get(view.connection.profile_id):
                self.edit_connection(connection_id)
                return
            if (view.connection.kind == "system" and view.connection.system_mode == 'tun'
                    and any(word in view.message.lower() for word in ('компонент', 'служб'))):
                self.install_vpn_component()
            else:
                self.start_connection(connection_id)

    def start_connection(self, connection_id, *, automatic=False):
        self.controller.settings = self.settings
        self.controller.start(connection_id, automatic=automatic)
        view = self._view(connection_id)
        if view:
            self._browser_starts.add(connection_id)

    def _on_session_changed(self, view):
        if not hasattr(self, "dashboard"):
            return
        current = self._view(view.connection.id)
        if current is None or view.generation != current.generation:
            return
        view.message = sanitize_connection_error(view.message)
        self.dashboard.update_view(view)
        self._refresh_auto_connect_list()
        key = view.connection.id
        if view.status == "connected" and key in self._browser_starts:
            self._browser_starts.discard(key)
            if view.connection.kind == "window" and view.connection.auto_open_browser:
                self.open_connection_browser(view.connection.id)
        if view.status in {"error", "offline"}:
            self._browser_starts.discard(key)
        if view.status == "offline" and view.connection.id in self._pending_remove:
            self._pending_remove.discard(view.connection.id)
            self.controller.remove(view.connection.id)
            self.dashboard.remove(view.connection.id)
            self._refresh_auto_connect_list()
        elif view.status == "offline" and view.connection.id in self._pending_reconfigure:
            changes, restart = self._pending_reconfigure.pop(view.connection.id)
            if self._configure_connection(view.connection.id, **changes) and restart:
                self.start_connection(view.connection.id)

    def _configure_connection(self, connection_id, **changes):
        try:
            self.controller.configure(connection_id, **changes)
            card = self.dashboard.system if connection_id == 'system' else self.dashboard.cards.get(connection_id)
            if card:
                card.clear_error()
            return True
        except Exception as exc:
            card = self.dashboard.system if connection_id == "system" else self.dashboard.cards.get(connection_id)
            if card:
                card.show_error(sanitize_connection_error(str(exc)))
            return False

    def add_connection_window(self):
        if not self.profiles:
            self.add_profile()
            if not self.profiles:
                return
        profile = self.current_profile()
        dialog = ConnectionDialog(self, tr('Добавить окно'), self.profiles, profile.id if profile else "", self.settings,
                                  switch_factory=self._make_switch)
        if not self._exec_profile_dialog(dialog):
            return
        try:
            values = dialog.values()
            profile_id = values.pop("profile_id")
            connection = self.controller.add_window(profile_id, **values)
            card = self.dashboard.insert(self._view(connection.id))
            self._wire_card(card)
            self._set_route('home')
            self.start_connection(connection.id)
            self.dashboard.scroll.ensureWidgetVisible(card)
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, sanitize_connection_error(str(exc)))

    def edit_connection(self, connection_id):
        view = self._view(connection_id)
        if not view:
            return
        if not self.profiles:
            self.add_profile()
            if not self.profiles:
                return
        system = view.connection.kind == "system"
        dialog = ConnectionDialog(self, tr('Профиль для системного подключения') if system else tr('Параметры окна №{0}', view.connection.number),
                                  self.profiles, view.connection.profile_id, self.settings, view.connection, system=system,
                                  switch_factory=self._make_switch)
        if not self._exec_profile_dialog(dialog):
            return
        changes = dialog.values()
        if view.status not in {"offline", "error"}:
            text = tr('Переподключить только это подключение? Его активные соединения прервутся.')
            if not system:
                text += tr(' При изменении портов потребуется перезапустить браузер и обновить настройки внешних приложений.')
            if QMessageBox.question(self, APP_NAME, text) != QMessageBox.StandardButton.Yes:
                return
            self._pending_reconfigure[connection_id] = (changes, True)
            self.controller.stop(connection_id)
        else:
            self._configure_connection(connection_id, **changes)

    def connection_menu(self, connection_id):
        view = self._view(connection_id)
        if not view:
            return
        card = self.dashboard.system if connection_id == "system" else self.dashboard.cards[connection_id]
        menu = QMenu(self)
        edit = menu.addAction(tr('Сменить профиль') if connection_id == "system" else tr('Профиль и порты…'))
        edit.triggered.connect(lambda: self.edit_connection(connection_id))
        edit.setEnabled(view.status not in {"preparing", "connecting", "stopping"})
        auto = menu.addAction(tr('Автоподключение с Windows'))
        auto.setCheckable(True)
        auto.setChecked(view.connection.auto_connect)
        auto.setEnabled(self.settings.launch_on_startup and view.connection.profile_id in self.controller.profiles)
        auto.triggered.connect(lambda checked: self._set_connection_autostart(connection_id, checked))
        log = menu.addAction(tr('Подробности / журнал'))
        log.triggered.connect(lambda: self.show_connection_log(connection_id))
        if connection_id == "system" and view.connection.system_mode == 'tun':
            from outward_app.core.vpn_pipe import service_status
            try:
                installed = bool(service_status()[0])
            except OSError:
                installed = False
            install = menu.addAction((tr('Обновить') if installed else tr('Установить')) + tr(' службу системного VPN…'))
            install.triggered.connect(self.install_vpn_component)
            install.setEnabled(view.status in {"offline", "error"})
        elif connection_id != 'system':
            for title, text in ((tr('Копировать HTTP-адрес'), f"http://127.0.0.1:{view.runtime.http_port if view.runtime else view.connection.http_port}"),
                                (tr('Копировать SOCKS5-адрес'), f"socks5://127.0.0.1:{view.runtime.socks_port if view.runtime else view.connection.socks_port}")):
                action = menu.addAction(title)
                action.triggered.connect(lambda checked=False, value=text: QApplication.clipboard().setText(value))
            menu.addSeparator()
            remove = menu.addAction(tr('Удалить окно'))
            remove.triggered.connect(lambda: self.remove_connection(connection_id))
        menu.exec(card.menu_button.mapToGlobal(card.menu_button.rect().bottomLeft()))
        menu.deleteLater()

    def _set_connection_autostart(self, connection_id, checked):
        self._configure_connection(connection_id, auto_connect=checked)
        self._refresh_auto_connect_list()

    def remove_connection(self, connection_id):
        view = self._view(connection_id)
        if not view:
            return
        if QMessageBox.question(self, tr('Удалить окно'), tr('Остановить и удалить окно №{0}? Профиль сервера и данные браузера сохранятся.', view.connection.number)) != QMessageBox.StandardButton.Yes:
            return
        self._pending_remove.add(connection_id)
        self.controller.stop(connection_id)

    def open_connection_browser(self, connection_id):
        view = self._view(connection_id)
        if not view or view.status != "connected" or not view.runtime or not view.runtime.socks_port:
            return
        settings = deepcopy(self.settings)
        generation = view.generation
        def current():
            latest = self._view(connection_id)
            return latest and latest.generation == generation and latest.status == "connected" and not self.controller.closed.is_set()
        def launch():
            if not open_url_with_proxy(view.runtime.socks_port, settings.preferred_browser,
                    view.connection.launch_url, settings.disable_browser_extensions,
                    connection_id=connection_id, legacy_browser_dir=view.connection.legacy_browser_dir,
                    still_current=current):
                raise OSError(tr('Chrome или Edge не найдены. Установите поддерживаемый браузер; подключение окна продолжает работать.'))
        def finished(value, error):
            card = self.dashboard.cards.get(connection_id)
            if card:
                card.set_browser_pending(False)
                latest = self._view(connection_id)
                if latest:
                    card.render(latest)
                if error:
                    card.show_error(error)
        self.dashboard.cards[connection_id].clear_error()
        self.dashboard.cards[connection_id].set_browser_pending(True)
        self._background("browser-" + connection_id, launch, finished)

    def manage_window_sites(self, connection_id):
        view = self._view(connection_id)
        if not view:
            return
        dialog = LaunchSitesDialog(self, self.settings.launch_sites)
        if self._exec_profile_dialog(dialog):
            sites = dialog.build_sites()
            self.settings.launch_sites = sites
            self.store.save_settings(self.settings)
            for item in self.controller.views():
                if item.connection.kind == "window" and item.connection.launch_url not in sites:
                    self._configure_connection(item.connection.id, launch_url=sites[0])
            for card in self.dashboard.cards.values():
                card.set_sites(sites)
            self._sync_launch_sites_combo(self.settings.launch_url if self.settings.launch_url in sites else sites[0])

    def install_vpn_component(self):
        text = tr('Служба Outward для Windows нужна для режима TUN. Для системного прокси и отдельных прокси-окон она не требуется.\n\nУстановить или обновить службу? Windows запросит права администратора. Прокси-окна продолжат работать.')
        if QMessageBox.question(self, tr('Служба системного VPN'), text) != QMessageBox.StandardButton.Yes:
            return
        from outward_app.core.vpn_install import elevate_install
        self._background("install-vpn", elevate_install, self._vpn_installed)

    def _vpn_installed(self, value, error):
        if error:
            self.dashboard.system.show_error(error)
        elif self._view('system').connection.system_mode == 'tun':
            self.start_connection("system")

    def show_connection_log(self, connection_id):
        self._log_connection = connection_id
        self._set_route('settings')
        self._set_tab_index(0)
        self.refresh_log()

    def _sync_connections_profiles(self):
        if not hasattr(self, "controller") or not hasattr(self, "dashboard"):
            return
        self.controller.profiles = {p.id: deepcopy(p) for p in self.profiles}
        self.dashboard.profiles = self.controller.profiles
        for view in self.controller.views():
            self.dashboard.update_view(view)
        self._refresh_auto_connect_list()
        self.dashboard.system.action_button.setEnabled(bool(self.profiles) and self._view("system").status != "stopping")

    def _shutdown_connections(self, after):
        if self._closing:
            return
        self._closing = True
        self.log_timer.stop()
        self.session_timer.stop()
        self.centralWidget().setEnabled(False)
        self.status_caption_label.setText(tr('Останавливаем подключения и освобождаем сетевые ресурсы…'))
        self.status_caption_label.show()
        def finished(value, error):
            if error:
                self._closing = False
                QMessageBox.warning(self, APP_NAME, tr('Не удалось полностью остановить подключения.\n') + error)
                return
            self._close_ready = True
            # Drain other jobs and update threads before quitting Qt.
            QTimer.singleShot(50, lambda: self._finish_shutdown(after))
        self._background("shutdown-connections", self.controller.close, finished)

    def _finish_shutdown(self, after):
        updating = any(thread is not None and thread.isRunning() for thread in
                       (self.update_check_thread, self.update_download_thread))
        if self._jobs or updating:
            QTimer.singleShot(50, lambda: self._finish_shutdown(after))
        else:
            self._background_pool.shutdown(wait=False)
            after()
