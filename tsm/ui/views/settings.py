"""Settings dialog — matches original TSM settings window."""

from __future__ import annotations

import logging
import subprocess

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from tsm.ui.viewmodels.settings_vm import SettingsViewModel

logger = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    def __init__(
        self,
        settings_vm: SettingsViewModel,
        auth_service=None,
        wow_detector=None,
        api_client=None,
        realm_vm=None,
        realm_tree=None,
        parent=None,
    ):
        super().__init__(parent)
        self._vm = settings_vm
        self._auth_service = auth_service
        self._detector = wow_detector
        self._api_client = api_client
        self._realm_vm = realm_vm

        from tsm import __version__
        self.setWindowTitle(f"Settings - v{__version__}")
        self.setModal(True)
        self.setMinimumSize(540, 400)
        self.setMaximumSize(800, 620)
        self.resize(560, 440)
        self._setup_ui()
        self._load()
        if realm_tree is not None:
            self._realm_tree = realm_tree
            self._populate_gv_combo()
        else:
            self._load_realms_async()

    def _setup_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        # Custom tab bar — same style as main window
        tabbar = QWidget()
        tabbar.setObjectName("tabbar")
        tabbar.setFixedHeight(36)
        tab_row = QHBoxLayout(tabbar)
        tab_row.setContentsMargins(0, 0, 0, 0)
        tab_row.setSpacing(0)

        self._tab_buttons: list[QPushButton] = []
        self._stack = QStackedWidget()
        pages = [
            ("General", self._build_general()),
            ("Notifications", self._build_notifications()),
            ("Backup", self._build_backup()),
        ]
        for i, (label, page) in enumerate(pages):
            btn = QPushButton(label)
            btn.setObjectName("tab")
            btn.setCheckable(True)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            btn.clicked.connect(lambda _, idx=i: self._switch_tab(idx))
            tab_row.addWidget(btn)
            self._tab_buttons.append(btn)
            self._stack.addWidget(page)

        self._tab_buttons[0].setChecked(True)
        vbox.addWidget(tabbar)
        vbox.addWidget(self._stack, 1)

        # Bottom bar
        bottom = QWidget()
        bottom_row = QHBoxLayout(bottom)
        bottom_row.setContentsMargins(10, 8, 10, 8)

        logout_btn = QPushButton("Logout and Reset Settings")
        logout_btn.setObjectName("secondary")
        logout_btn.clicked.connect(self._logout_reset)
        bottom_row.addWidget(logout_btn)

        bottom_row.addStretch()

        done_btn = QPushButton("Done")
        done_btn.setFixedWidth(80)
        done_btn.clicked.connect(self._save_and_close)
        bottom_row.addWidget(done_btn)

        vbox.addWidget(bottom)

    def _switch_tab(self, idx: int) -> None:
        self._stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._tab_buttons):
            btn.setChecked(i == idx)

    # ── Tab: General ─────────────────────────────────────────────────

    def _build_general(self) -> QWidget:
        w = QWidget()
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(10, 10, 10, 10)
        vbox.setSpacing(8)

        # WoW Directory
        wow_label = QLabel("WoW Directory")
        wow_label.setObjectName("section-title")
        vbox.addWidget(wow_label)

        dir_row = QHBoxLayout()
        self._wow_dir = QLineEdit()
        dir_row.addWidget(self._wow_dir, 1)
        browse_btn = QPushButton("Browse")
        browse_btn.setObjectName("secondary")
        browse_btn.setFixedWidth(70)
        browse_btn.clicked.connect(self._browse_wow)
        dir_row.addWidget(browse_btn)
        vbox.addLayout(dir_row)

        vbox.addSpacing(8)

        realms_label = QLabel("Realms")
        realms_label.setObjectName("section-title")
        vbox.addWidget(realms_label)

        # Realm selectors: Game Version | Region | Realm + Add
        realm_row = QHBoxLayout()
        realm_row.setSpacing(8)
        self._gv_combo = QComboBox()
        self._gv_combo.setFixedWidth(110)
        self._gv_combo.currentIndexChanged.connect(self._on_gv_changed)
        realm_row.addWidget(self._gv_combo)

        self._region_combo = QComboBox()
        self._region_combo.setFixedWidth(80)
        self._region_combo.currentIndexChanged.connect(self._on_region_changed)
        realm_row.addWidget(self._region_combo)

        self._realm_combo = QComboBox()
        self._realm_combo.setMinimumWidth(130)
        realm_row.addWidget(self._realm_combo, 1)

        add_btn = QPushButton("Add")
        add_btn.setObjectName("secondary")
        add_btn.setFixedWidth(50)
        add_btn.clicked.connect(self._add_realm)
        realm_row.addWidget(add_btn)
        vbox.addLayout(realm_row)

        vbox.addSpacing(8)

        # Startup
        startup_label = QLabel("Startup")
        startup_label.setObjectName("section-title")
        vbox.addWidget(startup_label)

        cb_grid = QGridLayout()
        cb_grid.setHorizontalSpacing(20)
        cb_grid.setVerticalSpacing(4)
        self._minimized_cb = QCheckBox("Start Minimized to Tray")
        self._tray_cb = QCheckBox("Minimize to System Tray")
        self._confirm_cb = QCheckBox("Show Confirmation on Exit")
        cb_grid.addWidget(self._minimized_cb, 0, 0)
        cb_grid.addWidget(self._tray_cb, 0, 1)
        cb_grid.addWidget(self._confirm_cb, 1, 0)
        vbox.addLayout(cb_grid)

        vbox.addStretch()
        return w

    # ── Tab: Notifications ────────────────────────────────────────────

    def _build_notifications(self) -> QWidget:
        w = QWidget()
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(10, 10, 10, 10)
        vbox.setSpacing(6)

        vbox.addWidget(
            QLabel(
                "Check the boxes below to enable desktop notifications (aka toasts) "
                "for various events."
            )
        )

        vbox.addSpacing(8)

        self._notif_realm = QCheckBox("New Realm Data Downloaded")
        self._notif_addon = QCheckBox("Addon Update")
        self._notif_backup = QCheckBox("New Backup Created")
        notif_grid = QGridLayout()
        notif_grid.setHorizontalSpacing(20)
        notif_grid.setVerticalSpacing(6)
        notif_grid.addWidget(self._notif_realm, 0, 0)
        notif_grid.addWidget(self._notif_addon, 0, 1)
        notif_grid.addWidget(self._notif_backup, 1, 0)
        vbox.addLayout(notif_grid)

        vbox.addStretch()
        return w

    # ── Tab: Backup ───────────────────────────────────────────────────

    def _build_backup(self) -> QWidget:
        w = QWidget()
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(10, 10, 10, 10)
        vbox.setSpacing(8)

        vbox.addWidget(
            QLabel(
                "Your TSM addon settings will be automatically backed-up every time they "
                "change assuming the minimum backup period has elapsed."
            )
        )

        vbox.addSpacing(8)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)

        grid.addWidget(QLabel("Minimum Backup Period:"), 0, 0)
        self._backup_period = QComboBox()
        self._backup_period.addItems(["15 minutes", "30 minutes", "1 hour", "2 hours", "6 hours"])
        self._backup_period.setCurrentText("1 hour")
        grid.addWidget(self._backup_period, 0, 1)

        grid.addWidget(QLabel("Delete Backups After:"), 1, 0)
        self._backup_retain = QComboBox()
        self._backup_retain.addItems(["1 week", "2 weeks", "1 month", "3 months", "Never"])
        self._backup_retain.setCurrentText("1 month")
        grid.addWidget(self._backup_retain, 1, 1)

        vbox.addLayout(grid)

        open_btn = QPushButton("Open Backup Folder")
        open_btn.setObjectName("secondary")
        open_btn.clicked.connect(self._open_backup_folder)
        vbox.addWidget(open_btn)

        vbox.addStretch()
        return w

    # ── Actions ───────────────────────────────────────────────────────

    def _load(self) -> None:
        cfg = self._vm.config
        self._tray_cb.setChecked(cfg.minimize_to_tray)
        self._minimized_cb.setChecked(cfg.start_minimized)
        self._confirm_cb.setChecked(cfg.show_confirmation_on_exit)
        self._notif_realm.setChecked(cfg.notify_realm_data)
        self._notif_addon.setChecked(cfg.notify_addon_update)
        self._notif_backup.setChecked(cfg.notify_backup)
        self._backup_period.setCurrentText(_minutes_to_period(cfg.backup_period_minutes))
        self._backup_retain.setCurrentText(_days_to_retain(cfg.backup_retain_days))

        # Prefer detected WoW path from detector (shows WoW root, not _retail_)
        if self._detector is not None:
            installs = getattr(self._detector, "_installs", []) or []
            if installs:
                from pathlib import Path

                # install.path is _retail_ directory; show the parent (WoW root)
                wow_root = str(Path(installs[0].path).parent)
                self._wow_dir.setText(wow_root)
                return
        # Fallback: stored paths in config
        for install in cfg.wow_installs:
            self._wow_dir.setText(install.path)
            break

    def _save_and_close(self) -> None:
        self._vm.set_minimize_to_tray(self._tray_cb.isChecked())
        self._vm.set_start_minimized(self._minimized_cb.isChecked())
        self._vm.set_show_confirmation_on_exit(self._confirm_cb.isChecked())
        self._vm.set_notify_realm_data(self._notif_realm.isChecked())
        self._vm.set_notify_addon_update(self._notif_addon.isChecked())
        self._vm.set_notify_backup(self._notif_backup.isChecked())
        self._vm.set_backup_period_minutes(_period_to_minutes(self._backup_period.currentText()))
        self._vm.set_backup_retain_days(_retain_to_days(self._backup_retain.currentText()))
        self._vm.save()
        self.accept()

    def _browse_wow(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select WoW Directory")
        if path:
            self._wow_dir.setText(path)
            self._vm.add_wow_path(path)

    def _load_realms_async(self) -> None:
        """Fetch realm list from API and populate the combo box."""
        if self._api_client is None:
            return
        from tsm.workers.bridge import AsyncBridge

        bridge = AsyncBridge(self)
        bridge.result_ready.connect(self._on_realms_loaded)
        bridge.error_occurred.connect(lambda e: logger.warning("Failed to load realm list: %s", e))
        bridge.run(self._api_client.realms.list())

    def _on_realms_loaded(self, data) -> None:
        """Raw API response → build processed tree then populate combos."""
        if not isinstance(data, dict):
            return
        self._realm_tree = {}
        for game_ver, realms in data.items():
            if not isinstance(realms, list):
                continue
            if game_ver == "retail":
                gv_label, api_gv = "Retail", "retail"
            elif game_ver == "bcc":
                gv_label, api_gv = "Progression", "bcc"
            else:
                continue
            self._realm_tree.setdefault(gv_label, {})
            for realm in realms:
                region = realm.get("region", "")
                self._realm_tree[gv_label].setdefault(region, []).append(
                    {
                        "id": realm.get("id", 0),
                        "name": realm.get("name", ""),
                        "gameVersion": api_gv,
                    }
                )
        for gv in self._realm_tree.values():
            for region in gv:
                gv[region].sort(key=lambda r: r["name"])
        self._populate_gv_combo()

    def _populate_gv_combo(self) -> None:
        self._gv_combo.blockSignals(True)
        self._gv_combo.clear()
        for gv_label in sorted(self._realm_tree):
            self._gv_combo.addItem(gv_label)
        self._gv_combo.blockSignals(False)
        retail_idx = self._gv_combo.findText("Retail")
        self._gv_combo.setCurrentIndex(retail_idx if retail_idx >= 0 else 0)
        self._on_gv_changed(self._gv_combo.currentIndex())

    def _on_gv_changed(self, _index: int) -> None:
        gv_label = self._gv_combo.currentText()
        regions = (
            sorted(self._realm_tree.get(gv_label, {}).keys())
            if hasattr(self, "_realm_tree")
            else []
        )
        self._region_combo.blockSignals(True)
        self._region_combo.clear()
        for r in regions:
            self._region_combo.addItem(r)
        self._region_combo.blockSignals(False)
        self._on_region_changed(0)

    def _on_region_changed(self, _index: int) -> None:
        gv_label = self._gv_combo.currentText()
        region = self._region_combo.currentText()
        realms = []
        if hasattr(self, "_realm_tree"):
            realms = self._realm_tree.get(gv_label, {}).get(region, [])
        self._realm_combo.clear()
        for r in realms:
            self._realm_combo.addItem(r["name"])

    def _add_realm(self) -> None:
        gv_label = self._gv_combo.currentText()
        region = self._region_combo.currentText()
        idx = self._realm_combo.currentIndex()
        if not hasattr(self, "_realm_tree") or not gv_label or not region or idx < 0:
            return
        realm_list = self._realm_tree.get(gv_label, {}).get(region, [])
        if idx >= len(realm_list):
            return
        realm = realm_list[idx]
        if self._api_client is None:
            return
        from tsm.workers.bridge import AsyncBridge

        bridge = AsyncBridge(self)

        def _on_added(_):
            logger.info("Realm added: %s %s %s", gv_label, region, realm["name"])
            if self._realm_vm is not None:
                self._realm_vm.refresh_all()

        bridge.result_ready.connect(_on_added)
        bridge.error_occurred.connect(lambda e: logger.error("Failed to add realm: %s", e))
        bridge.run(self._api_client.realms.add(realm["gameVersion"], realm["id"]))

    def _open_backup_folder(self) -> None:
        from tsm.core.services.backup import _BACKUP_DIR

        _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", str(_BACKUP_DIR)])

    def _logout_reset(self) -> None:
        """Logout and reset all settings to defaults."""
        # Reset config to defaults
        from tsm.core.models.config import AppConfig

        self._vm._config = AppConfig()
        self._vm.save()

        if self._auth_service:
            from tsm.workers.bridge import AsyncBridge

            bridge = AsyncBridge(self)
            bridge.run(self._auth_service.logout())

        self.reject()


_PERIOD_MAP = {
    "15 minutes": 15,
    "30 minutes": 30,
    "1 hour": 60,
    "2 hours": 120,
    "6 hours": 360,
}
_RETAIN_MAP = {
    "1 week": 7,
    "2 weeks": 14,
    "1 month": 30,
    "3 months": 90,
    "Never": -1,
}


def _period_to_minutes(text: str) -> int:
    return _PERIOD_MAP.get(text, 60)


def _minutes_to_period(minutes: int) -> str:
    return next((k for k, v in _PERIOD_MAP.items() if v == minutes), "1 hour")


def _retain_to_days(text: str) -> int:
    return _RETAIN_MAP.get(text, 30)


def _days_to_retain(days: int) -> str:
    return next((k for k, v in _RETAIN_MAP.items() if v == days), "1 month")
