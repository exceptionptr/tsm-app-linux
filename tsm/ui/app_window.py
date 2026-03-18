"""Main application window — matches original TSM Desktop App layout."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from tsm.ui.components.status_bar import TSMStatusBar
from tsm.ui.viewmodels.app_vm import AppViewModel
from tsm.ui.viewmodels.realm_vm import RealmViewModel
from tsm.ui.viewmodels.settings_vm import SettingsViewModel
from tsm.ui.views.accounting_export import AccountingExportView
from tsm.ui.views.addon_versions import AddonVersionsView
from tsm.ui.views.backups import BackupsView
from tsm.ui.views.login import LoginView
from tsm.ui.views.realm_data import RealmDataView, _fmt_ts

logger = logging.getLogger(__name__)

_ASSETS_DIR = Path(__file__).parent / "assets"

_TABS = [
    ("Realm Data", "realm"),
    ("Addon Versions", "addons"),
    ("Backups", "backups"),
    ("Accounting Export", "accounting"),
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
        self._realm_tree_cache: dict | None = None

        from tsm import __version__
        self.setWindowTitle(f"TradeSkillMaster Application - v{__version__}")
        self.setMinimumSize(620, 540)
        self.setMaximumSize(1200, 900)
        self.resize(620, 560)
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
        self._addon_view = AddonVersionsView(self._addon_service)
        self._backup_view = BackupsView(self._backup_service, backup_now_fn=self._run_backup_now)
        self._acct_view = AccountingExportView(self._addon_service)
        self._stack.addWidget(self._realm_view)  # 0
        self._stack.addWidget(self._addon_view)  # 1
        self._stack.addWidget(self._backup_view)  # 2
        self._stack.addWidget(self._acct_view)  # 3
        vbox.addWidget(self._stack, 1)

        # Wire addon versions update from realm VM
        self._realm_vm.addons_updated.connect(self._addon_view.update_from_api)
        # Refresh accounting dropdowns after data sync (detector will have installs by then)
        self._realm_vm.data_updated.connect(self._acct_view._populate)

        vbox.addWidget(self._build_footer())

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

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        footer.setObjectName("footer")
        footer.setFixedHeight(44)
        row = QHBoxLayout(footer)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(6)

        premium_btn = QPushButton("Support TSM by Going Premium!")
        premium_btn.setFixedHeight(30)
        premium_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://tradeskillmaster.com/premium"))
        )
        row.addWidget(premium_btn)

        github_btn = QPushButton("GitHub")
        github_btn.setFixedHeight(30)
        github_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://github.com/exceptionptr/tsm-app-linux"))
        )
        row.addWidget(github_btn)

        settings_btn = QPushButton("Settings")
        settings_btn.setFixedHeight(30)
        settings_btn.clicked.connect(self._open_settings)
        row.addWidget(settings_btn)

        return footer

    # ── Signals ─────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        self._app_vm.status_changed.connect(self._status_bar.set_status)  # single pipe
        self._app_vm.authenticated_changed.connect(self._update_status)
        self._realm_vm.data_updated.connect(self._update_status)
        self._realm_vm.data_updated.connect(self._notify_realm_data)
        self._realm_vm.loading_changed.connect(self._on_loading_changed)
        self._app_vm.backup_notification.connect(self._notify_backup)
        self._app_vm.backup_notification.connect(lambda _: self._backup_view._refresh())
        self._app_vm.addon_notification.connect(self._notify_addon)
        self._app_vm.realm_data_received.connect(self._realm_vm._on_data_received)
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
            self.notify(f"Auction data synced — {n} realm(s)/region(s) updated.")

    def _notify_backup(self, message: str) -> None:
        if self._settings_vm.config.notify_backup:
            self.notify(message)

    def _notify_addon(self, message: str) -> None:
        if self._settings_vm.config.notify_addon_update:
            self.notify(message)

    def _run_backup_now(self, done_callback) -> None:
        if self._backup_service is None:
            done_callback()
            return

        async def _do_backup():
            import asyncio

            cfg = self._settings_vm.config
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                lambda: self._backup_service.run(
                    period_minutes=0,
                    retain_days=cfg.backup_retain_days,
                    extra_installs=cfg.wow_installs,
                    keep=True,
                ),
            )

        from tsm.workers.bridge import AsyncBridge

        bridge = AsyncBridge(self)
        bridge.result_ready.connect(lambda _: done_callback())
        bridge.error_occurred.connect(lambda _: done_callback())
        bridge.run(_do_backup())

    def _update_status(self, *_args: object) -> None:
        installs = list(getattr(self._addon_service, "_installs", []) or [])
        if not installs:
            installs = list(getattr(self._settings_vm.config, "wow_installs", []) or [])
        if not installs:
            self._app_vm.set_status("⚠ WoW directory not configured")
            return
        last = self._realm_vm.last_sync
        if last:
            self._app_vm.set_status(f"Up to date as of {_fmt_ts(last)}")
        else:
            self._app_vm.set_status("Checking status…")

    def _on_loading_changed(self, loading: bool) -> None:
        if loading:
            self._app_vm.set_status("Syncing data with server…")

    # ── Navigation ───────────────────────────────────────────────────

    def _switch_tab(self, key: str) -> None:
        idx = {k: i for i, (_, k) in enumerate(_TABS)}.get(key, 0)
        self._stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._tab_buttons):
            btn.setChecked(i == idx)

    # ── Settings dialog ──────────────────────────────────────────────

    def _open_settings(self) -> None:
        from tsm.ui.views.settings import SettingsDialog

        dlg = SettingsDialog(
            self._settings_vm,
            self._auth_service,
            wow_detector=self._addon_service,
            api_client=self._api_client,
            realm_vm=self._realm_vm,
            realm_tree=self._realm_tree_cache,
            parent=self,
        )
        dlg.exec()

    # ── Tray ─────────────────────────────────────────────────────────

    def _setup_tray(self) -> None:
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(_make_app_icon())
        menu = QMenu()
        show_action = QAction("Show", self)
        show_action.triggered.connect(self.show)
        menu.addAction(show_action)
        menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason) -> None:
        # On Linux, DoubleClick and Trigger both should show the window.
        show_reasons = (
            QSystemTrayIcon.ActivationReason.DoubleClick,
            QSystemTrayIcon.ActivationReason.Trigger,
        )
        if reason in show_reasons:
            self.show()
            self.raise_()
            self.activateWindow()

    def closeEvent(self, event) -> None:
        cfg = self._settings_vm.config
        if cfg.minimize_to_tray:
            event.ignore()
            self.hide()
            return
        if cfg.show_confirmation_on_exit:
            from PySide6.QtWidgets import QMessageBox

            reply = QMessageBox.question(
                self,
                "Quit TSM",
                "Are you sure you want to quit TradeSkillMaster?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _quit(self) -> None:
        cfg = self._settings_vm.config
        if cfg.show_confirmation_on_exit:
            from PySide6.QtWidgets import QMessageBox

            reply = QMessageBox.question(
                self,
                "Quit TSM",
                "Are you sure you want to quit TradeSkillMaster?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        cfg.minimize_to_tray = False
        app = QApplication.instance()
        if app is not None:
            app.quit()

    # ── Login ────────────────────────────────────────────────────────

    def show_login(self) -> None:
        login = LoginView(self._app_vm, self._auth_service, parent=None)
        login.login_successful.connect(self._on_login_success)
        result = login.exec()
        # If user dismissed login without logging in, quit the app.
        if result == 0 and not self._app_vm.authenticated:
            app = QApplication.instance()
            if app is not None:
                app.quit()

    def _on_login_success(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self._app_vm.set_status("Connected — syncing data…")
        self._realm_vm.load_snapshot()
        self._realm_vm.refresh_all()
        self._prefetch_realm_list()

    def _prefetch_realm_list(self) -> None:
        if self._api_client is None:
            return
        from tsm.workers.bridge import AsyncBridge

        bridge = AsyncBridge(self)
        bridge.result_ready.connect(self._on_realm_list_fetched)
        bridge.run(self._api_client.realms.list())

    def _on_realm_list_fetched(self, data) -> None:
        if not isinstance(data, dict):
            return
        tree: dict[str, dict[str, list[dict]]] = {}
        for game_ver, realms in data.items():
            if not isinstance(realms, list):
                continue
            if game_ver == "retail":
                gv_label, api_gv = "Retail", "retail"
            elif game_ver == "bcc":
                gv_label, api_gv = "Progression", "bcc"
            else:
                continue
            tree.setdefault(gv_label, {})
            for realm in realms:
                region = realm.get("region", "")
                tree[gv_label].setdefault(region, []).append(
                    {
                        "id": realm.get("id", 0),
                        "name": realm.get("name", ""),
                        "gameVersion": api_gv,
                    }
                )
        for gv in tree.values():
            for region in gv:
                gv[region].sort(key=lambda r: r["name"])
        self._realm_tree_cache = tree


def _make_window_icon() -> QIcon:
    """Single 16 px icon for the window title bar / taskbar indicator."""
    p = _ASSETS_DIR / "tsm_16.png"
    if p.exists():
        return QIcon(str(p))
    px = QPixmap(16, 16)
    px.fill(QColor("#f26522"))
    return QIcon(px)


def _make_app_icon() -> QIcon:
    icon = QIcon()
    for name in ("tsm_16.png", "tsm_32.png", "tsm_48.png", "tsm_128.png", "tsm_256.png"):
        p = _ASSETS_DIR / name
        if p.exists():
            px = QPixmap(str(p))
            if not px.isNull():
                icon.addPixmap(px)
    if icon.isNull():
        px = QPixmap(22, 22)
        px.fill(QColor("#f26522"))
        return QIcon(px)
    return icon
