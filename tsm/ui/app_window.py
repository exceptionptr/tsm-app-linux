"""Main application window: matches original TSM Desktop App layout."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from tsm.ui.views.log_viewer import LogViewerWindow

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from tsm.ui._freshness import realm_freshness
from tsm.ui._tray_action import TrayAction, tray_action
from tsm.ui._tray_status import TrayStatus, tray_status, tray_tooltip
from tsm.ui._window_close import CloseAction, close_action
from tsm.ui.components.status_bar import TSMStatusBar
from tsm.ui.components.tray_badge import tray_icon
from tsm.ui.viewmodels.app_vm import AppViewModel
from tsm.ui.viewmodels.realm_vm import RealmViewModel
from tsm.ui.viewmodels.settings_vm import SettingsViewModel
from tsm.ui.views.accounting_export import AccountingExportView
from tsm.ui.views.addon_versions import AddonVersionsView
from tsm.ui.views.backups import BackupsView
from tsm.ui.views.login import format_auth_error, login_was_closed
from tsm.ui.views.realm_data import RealmDataView, fmt_ts
from tsm.workers.bridge import AsyncBridge

logger = logging.getLogger(__name__)

_ASSETS_DIR = Path(__file__).parent / "assets"

# The traffic light depends on the age of the data, so the tray re-checks it this often.
_TRAY_REFRESH_MS = 60_000

_TABS = [
    ("Realm Data", "realm"),
    ("Addon Versions", "addons"),
    ("Backups", "backups"),
    ("Accounting", "accounting"),
]


class AppWindow(QMainWindow):
    def __init__(
        self,
        app_vm: AppViewModel,
        realm_vm: RealmViewModel,
        settings_vm: SettingsViewModel,
        auth_service=None,
        addon_service=None,
        api_client=None,
        backup_service=None,
        updater_service=None,
        auction_service=None,
        focus_login: Callable[[], bool] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._app_vm = app_vm
        self._realm_vm = realm_vm
        self._settings_vm = settings_vm
        self._auth_service = auth_service
        self._addon_service = addon_service
        self._api_client = api_client
        self._backup_service = backup_service
        self._updater_service = updater_service
        self._auction_service = auction_service
        self._focus_login = focus_login
        # The one-time hint that the old saved password was removed was shown.
        self._migration_info_shown = False
        self._connected = False
        self._quitting = False
        self._logging_out = False
        # True from the moment a login bridge runs until its answer arrives.
        self._login_pending = False
        # Set once something else has taken over from the startup session restore
        # (a login started, a logout began): the restore chain then does nothing.
        self._startup_superseded = False
        self._session_ending = False
        self._backup_stats: str = ""
        self._tray_status: TrayStatus | None = None
        self._tray_icons: dict[TrayStatus, QIcon] = {}
        self._log_viewer: LogViewerWindow | None = None

        from tsm import __version__

        self.setWindowTitle(f"TradeSkillMaster Application - v{__version__}")
        # The Accounting dashboard needs room for the chart, six headline
        # figures across, three money panels and the item table.
        self.setMinimumSize(1000, 720)
        self.resize(1280, 860)
        self.setWindowIcon(_make_window_icon())
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
        )

        self._setup_ui()
        self._setup_tray()
        self._connect_signals()

    # ── Layout ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        vbox = QVBoxLayout(root)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        vbox.addWidget(self._build_tabbar())

        self._stack = QStackedWidget()
        self._realm_view = RealmDataView(self._realm_vm)
        self._realm_vm.realm_tree_ready.connect(self._realm_view.set_realm_tree)
        self._addon_view = AddonVersionsView(self._addon_service, self._updater_service)
        self._backup_view = BackupsView(self._backup_service, backup_now_fn=self._run_backup_now)
        self._acct_view = AccountingExportView(self._addon_service)

        self._stack.addWidget(self._realm_view)  # 0
        self._stack.addWidget(self._addon_view)  # 1
        self._stack.addWidget(self._backup_view)  # 2
        self._stack.addWidget(self._acct_view)  # 3
        vbox.addWidget(self._stack, 1)

        # Wire addon versions update from realm VM
        self._realm_vm.addons_updated.connect(self._addon_view.update_from_api)
        self._addon_view.install_completed.connect(self._realm_vm.refresh_all)
        # Refresh accounting dropdowns after data sync (detector will have installs by then)
        self._realm_vm.data_updated.connect(self._acct_view.populate)

        self._status_bar = TSMStatusBar()
        self.setStatusBar(self._status_bar)

    def _build_tabbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("tabbar")
        bar.setFixedHeight(36)
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self._tab_buttons: list[QPushButton] = []
        for label, key in _TABS:
            btn = QPushButton(label)
            btn.setObjectName("tab")
            btn.setCheckable(True)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            btn.clicked.connect(lambda _, k=key: self._switch_tab(k))
            row.addWidget(btn)
            self._tab_buttons.append(btn)

        self._tab_buttons[0].setChecked(True)
        return bar

    # ── Signals ─────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        self._app_vm.status_changed.connect(self._status_bar.set_status)
        self._app_vm.update_available.connect(self._status_bar.set_update_available)
        self._status_bar.settings_requested.connect(self._open_settings)
        self._status_bar.logs_requested.connect(self._open_log_viewer)
        self._app_vm.authenticated_changed.connect(self._update_status)
        self._app_vm.authenticated_changed.connect(self._update_tray)
        self._realm_vm.data_updated.connect(self._update_status)
        self._realm_vm.data_updated.connect(self._update_tray)
        self._realm_vm.data_updated.connect(self._notify_realm_data)
        self._realm_vm.loading_changed.connect(self._on_loading_changed)
        self._app_vm.backup_notification.connect(self._notify_backup)
        self._app_vm.backup_notification.connect(lambda _: self._backup_view.refresh())
        self._backup_view.stats_updated.connect(self._on_backup_stats)
        self._backup_view.refresh()
        self._app_vm.addon_notification.connect(self._notify_addon)
        self._app_vm.group_send_notification.connect(self.notify)
        self._app_vm.realm_data_received.connect(self._realm_vm.on_data_received)
        self._app_vm.connection_changed.connect(self._on_connection_changed)
        self._app_vm.session_lost.connect(self._on_session_lost)
        self._settings_vm.saved.connect(self._on_settings_saved)
        self._update_status()

    def _on_settings_saved(self) -> None:
        """Push updated WoW install paths into the detector immediately.

        _resolve_wow_installs only runs once at scheduler startup, so without
        this hook a freshly saved custom path is ignored until the app restarts.
        """
        if self._addon_service is None:
            return
        cfg = self._settings_vm.config
        if cfg.wow_path and Path(cfg.wow_path).exists():
            from tsm.core.models.config import WoWInstall

            self._addon_service.set_installs([WoWInstall(path=cfg.wow_path)])
            logger.info("Settings saved: pushed WoW path to detector: %s", cfg.wow_path)
        self._update_status()

    def notify(self, message: str, critical: bool = False) -> None:
        cfg = self._settings_vm.config
        if not cfg.notifications_enabled:
            return
        icon = (
            QSystemTrayIcon.MessageIcon.Critical
            if critical
            else QSystemTrayIcon.MessageIcon.Information
        )
        self._tray.showMessage("TradeSkillMaster", message, icon, 4000)

    def _notify_realm_data(self) -> None:
        if self._settings_vm.config.notify_realm_data and self._realm_vm.had_new_data:
            n = len(self._realm_vm.summaries)
            self.notify(f"{n} realm(s)/region(s) updated.")

    def _notify_backup(self, message: str) -> None:
        if self._settings_vm.config.notify_backup:
            self.notify(message)

    def _notify_addon(self, message: str) -> None:
        if self._settings_vm.config.notify_addon_update:
            self.notify(message)

    def _run_backup_now(self, name: str, done_callback) -> None:
        if self._backup_service is None:
            done_callback()
            return

        backup_service = self._backup_service

        async def _do_backup():
            import asyncio

            cfg = self._settings_vm.config
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None,
                lambda: backup_service.run(
                    period_minutes=0,
                    retain_days=cfg.backup_retain_days,
                    keep=True,
                    name=name,
                ),
            )

        bridge = AsyncBridge(self)
        bridge.result_ready.connect(lambda _: done_callback())
        bridge.error_occurred.connect(lambda _: done_callback())
        bridge.run(_do_backup())

    def _current_tab_key(self) -> str:
        idx = self._stack.currentIndex()
        return _TABS[idx][1] if 0 <= idx < len(_TABS) else ""

    def _on_backup_stats(self, text: str) -> None:
        self._backup_stats = text
        if self._current_tab_key() == "backups":
            self._app_vm.set_status(text)

    def _update_status(self, *_: object) -> None:
        if self._current_tab_key() == "backups":
            self._app_vm.set_status(self._backup_stats or "No backups stored.")
            return
        installs = list(self._addon_service.installs) if self._addon_service is not None else []
        if not installs and self._settings_vm.config.wow_path:
            from tsm.core.models.config import WoWInstall

            installs = [WoWInstall(path=self._settings_vm.config.wow_path)]
        has_wow = bool(installs)
        self._set_wow_tabs_enabled(has_wow)
        if not has_wow:
            self._app_vm.set_status("⚠ WoW directory not configured")
            return
        missing_gv = self._realm_vm.apphelper_missing_gv
        if missing_gv:
            from tsm.wow.utils import apphelper_addon_name

            names = ", ".join(apphelper_addon_name(gv) for gv in missing_gv)
            self._app_vm.set_status(f"⚠ No {names} installed")
            return
        if self._app_vm.authenticated and not self._connected:
            self._app_vm.set_status("Connecting to the TSM server…")
            return
        last = self._realm_vm.last_sync
        if last:
            self._app_vm.set_status(f"Up to date as of {fmt_ts(last)}")
        else:
            self._app_vm.set_status("Checking status…")

    def _set_wow_tabs_enabled(self, enabled: bool) -> None:
        wow_tabs = {"addons", "backups", "accounting"}
        for i, (_, key) in enumerate(_TABS):
            if key in wow_tabs:
                self._tab_buttons[i].setEnabled(enabled)
        if not enabled and self._current_tab_key() in wow_tabs:
            self._switch_tab("realm")

    def _on_connection_changed(self, connected: bool) -> None:
        self._connected = connected
        self._update_status()
        self._update_tray()

    def _on_loading_changed(self, loading: bool) -> None:
        if loading:
            self._app_vm.set_status("Syncing data with server…")

    # ── Navigation ───────────────────────────────────────────────────

    def _switch_tab(self, key: str) -> None:
        idx = {k: i for i, (_, k) in enumerate(_TABS)}.get(key, 0)
        self._stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._tab_buttons):
            btn.setChecked(i == idx)
        self._update_status()

    # ── Settings dialog ──────────────────────────────────────────────

    def _open_settings(self) -> None:
        if self._logging_out:
            return
        from tsm.ui.views.settings import SettingsDialog

        dlg = SettingsDialog(
            self._settings_vm,
            self._auth_service,
            wow_detector=self._addon_service,
            parent=self,
        )
        dlg.logout_started.connect(self._on_logout_started)
        dlg.logged_out.connect(self._on_logged_out)
        dlg.exec()

    def _open_log_viewer(self) -> None:
        from tsm.core.log_buffer import get_log_buffer
        from tsm.ui.views.log_viewer import LogViewerWindow

        if self._log_viewer is None or not self._log_viewer.isVisible():
            self._log_viewer = LogViewerWindow(get_log_buffer(), parent=self)
        self._log_viewer.show()
        self._log_viewer.raise_()
        self._log_viewer.activateWindow()

    # ── Tray ─────────────────────────────────────────────────────────

    def _setup_tray(self) -> None:
        self._tray = QSystemTrayIcon(self)
        menu = QMenu()
        show_action = QAction("Show", self)
        show_action.triggered.connect(lambda _checked=False: self._show_from_tray())
        menu.addAction(show_action)
        menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray_timer = QTimer(self)
        self._tray_timer.setInterval(_TRAY_REFRESH_MS)
        self._tray_timer.timeout.connect(self._update_tray)
        self._tray_timer.start()
        # The icon must be set before the tray is shown.
        self._update_tray()
        self._tray.show()

    def _update_tray(self, *_: object) -> None:
        """Show the current status as tray icon badge and tooltip."""
        status = tray_status(
            authenticated=bool(self._app_vm.authenticated),
            connected=self._connected,
            freshness=[
                realm_freshness(s.auctiondb_status, s.last_updated, s.is_region)
                for s in self._realm_vm.summaries
            ],
        )
        if status is not self._tray_status:
            icon = self._tray_icons.get(status)
            if icon is None:
                icon = tray_icon(status, _app_icon_images())
                self._tray_icons[status] = icon
            self._tray.setIcon(icon)
            self._tray_status = status
        self._tray.setToolTip(tray_tooltip(status))

    def _on_tray_activated(self, reason) -> None:
        # DoubleClick and Trigger both run the tray rule: it shows the main
        # window when signed in and brings the login window back otherwise.
        show_reasons = (
            QSystemTrayIcon.ActivationReason.DoubleClick,
            QSystemTrayIcon.ActivationReason.Trigger,
        )
        if reason in show_reasons:
            self._show_from_tray()

    def _show_from_tray(self) -> None:
        """Show the main window when signed in, otherwise bring the login back."""
        action = tray_action(
            authenticated=bool(self._app_vm.authenticated),
            logging_out=self._logging_out,
            login_pending=self._login_pending,
            startup_superseded=self._startup_superseded,
        )
        if action is TrayAction.SHOW_MAIN:
            self.show()
            self.raise_()
            self.activateWindow()
        elif action is TrayAction.FOCUS_LOGIN:
            if self._focus_login is not None:
                self._focus_login()
        elif action is TrayAction.START_LOGIN:
            self._start_login()

    def begin_session_end(self) -> None:
        """The desktop session is ending, so stop holding the window open.

        Called when the session manager announces a logout. From here on a
        close request is obeyed instead of being turned into a tray hide or a
        question box, either of which would cancel the logout.
        """
        self._session_ending = True

    def _confirm_quit(self) -> bool:
        reply = QMessageBox.question(
            self,
            "Quit TSM",
            "Are you sure you want to quit TradeSkillMaster?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def closeEvent(self, event) -> None:
        if self._quitting:
            event.accept()
            return
        cfg = self._settings_vm.config
        action = close_action(
            session_ending=self._session_ending,
            minimize_to_tray=cfg.minimize_to_tray,
            confirm_on_exit=cfg.show_confirmation_on_exit,
        )
        if action is CloseAction.HIDE:
            event.ignore()
            self.hide()
            return
        if action is CloseAction.CONFIRM and not self._confirm_quit():
            event.ignore()
            return
        event.accept()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _quit(self) -> None:
        if self._settings_vm.config.show_confirmation_on_exit and not self._confirm_quit():
            return
        self._quitting = True
        app = QApplication.instance()
        if app is not None:
            app.quit()

    # ── Login ────────────────────────────────────────────────────────

    def show_login(self) -> None:
        """Open the TSM login window at once, like the official client."""
        self._start_login()

    @property
    def startup_superseded(self) -> bool:
        """True when the startup restore must no longer open windows."""
        return self._startup_superseded

    def _start_login(self) -> None:
        self._startup_superseded = True
        if self._auth_service is None:
            logger.error("Auth service not configured, cannot start a login")
            _tray_message(self._tray, "Auth service not configured.", critical=True)
            _quit_without_tray_if_signed_out(self._app_vm)
            return
        if self._login_pending:
            logger.info("A login is already in progress, not starting another")
            return
        if (
            getattr(self._auth_service, "migrated_from_password", False)
            and not self._migration_info_shown
        ):
            self._migration_info_shown = True
            _tray_message(
                self._tray,
                "TSM now signs in through its website. Please sign in once more; "
                "your old saved password has been removed.",
            )
        self._login_pending = True
        bridge = AsyncBridge(self)
        bridge.result_ready.connect(self._on_login_result)
        bridge.error_occurred.connect(self._on_login_error)
        bridge.run(self._auth_service.login())

    def _on_login_result(self, session) -> None:
        self._login_pending = False
        if session.remember_failed:
            QMessageBox.warning(
                self,
                "TSM - Sign In",
                "You are signed in, but your login could not be saved because the "
                "system keyring is not available.\n\n"
                "Make sure a Secret Service provider such as GNOME Keyring or KWallet "
                "is running and unlocked. Until then you will be asked to sign in "
                "each time the app starts.",
            )
        self._app_vm.on_login_success(session)
        self._on_login_success()

    def _on_login_error(self, error_msg: str) -> None:
        self._login_pending = False
        if login_was_closed(error_msg):
            # No window and no page: the app waits in the tray, a click reopens the login.
            logger.info("Login ended without a sign-in: %s", error_msg)
            _quit_without_tray_if_signed_out(self._app_vm)
            return
        message = format_auth_error(error_msg)
        logger.warning("Login failed: %s", error_msg)
        _tray_message(self._tray, message, critical=True)
        _quit_without_tray_if_signed_out(self._app_vm)

    def _on_logout_started(self) -> None:
        """Logout clicked in Settings: leave the signed-in state and hide the window now."""
        if self._logging_out:
            return
        self._logging_out = True
        self._startup_superseded = True
        if self._auth_service is not None:
            self._auth_service.cancel_restore()
        self._app_vm.on_logout()
        self.hide()

    def _on_logged_out(self) -> None:
        """The logout has finished: show the login, once per logout."""
        if not self._logging_out:
            return
        self._logging_out = False
        self.show_login()

    def _on_session_lost(self) -> None:
        """The stored login stopped working (revoked, expired): sign in again."""
        if not self._app_vm.authenticated:
            return
        self._app_vm.on_logout()
        self.hide()
        self.show_login()

    def _on_login_success(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self._app_vm.set_status("Connected, syncing data…")
        self._realm_vm.load_snapshot()
        self._realm_vm.load_realm_tree()

    def on_authenticated(self, session) -> None:
        """Called after successful authentication (login or session restore)."""
        self._app_vm.on_login_success(session)
        self._app_vm.set_status("Connected, loading data...")
        if not self._settings_vm.config.start_minimized:
            self.show()
        self._realm_vm.load_snapshot()
        self._realm_vm.load_realm_tree()


def _quit_without_tray_if_signed_out(app_vm) -> None:
    """Quit when no tray exists and nobody is signed in: nothing could bring a window back."""
    if QSystemTrayIcon.isSystemTrayAvailable() or app_vm.authenticated:
        return
    app = QApplication.instance()
    if app is not None:
        app.quit()


def _tray_message(tray: QSystemTrayIcon, message: str, critical: bool = False) -> None:
    """Show a tray message even when notifications are switched off in the settings."""
    kind = QSystemTrayIcon.MessageIcon
    icon = kind.Critical if critical else kind.Information
    tray.showMessage("TradeSkillMaster", message, icon, 6000)


def _make_window_icon() -> QIcon:
    """256 px icon for the window title bar / taskbar indicator."""
    p = _ASSETS_DIR / "tsm_256.png"
    if p.exists():
        return QIcon(str(p))
    px = QPixmap(256, 256)
    px.fill(QColor("#f26522"))
    return QIcon(px)


def _app_icon_images() -> list[QImage]:
    """The tray icon sizes as images, the base for the status badge."""
    images: list[QImage] = []
    for name in ("tsm_16.png", "tsm_32.png", "tsm_48.png", "tsm_128.png", "tsm_256.png"):
        p = _ASSETS_DIR / name
        if p.exists():
            img = QImage(str(p))
            if not img.isNull():
                images.append(img)
    if not images:
        img = QImage(22, 22, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor("#f26522"))
        images.append(img)
    return images

