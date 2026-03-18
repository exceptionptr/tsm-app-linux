"""Settings form view model."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from tsm.core.models.config import AppConfig, WoWInstall
from tsm.storage.config_store import ConfigStore

logger = logging.getLogger(__name__)


class SettingsViewModel(QObject):
    config_changed = Signal()
    saved = Signal()

    def __init__(self, config_store: ConfigStore | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._store = config_store or ConfigStore()
        self._config = self._store.load()

    @property
    def config(self) -> AppConfig:
        return self._config

    def add_wow_path(self, path: str, version: str = "_retail_") -> None:
        install = WoWInstall(path=path, version=version)
        if install not in self._config.wow_installs:
            self._config.wow_installs.append(install)
            self.config_changed.emit()

    def remove_wow_path(self, path: str) -> None:
        self._config.wow_installs = [w for w in self._config.wow_installs if w.path != path]
        self.config_changed.emit()

    def set_minimize_to_tray(self, value: bool) -> None:
        self._config.minimize_to_tray = value
        self.config_changed.emit()

    def set_notifications_enabled(self, value: bool) -> None:
        self._config.notifications_enabled = value
        self.config_changed.emit()

    def set_notify_realm_data(self, value: bool) -> None:
        self._config.notify_realm_data = value
        self.config_changed.emit()

    def set_notify_addon_update(self, value: bool) -> None:
        self._config.notify_addon_update = value
        self.config_changed.emit()

    def set_notify_backup(self, value: bool) -> None:
        self._config.notify_backup = value
        self.config_changed.emit()

    def set_start_minimized(self, value: bool) -> None:
        self._config.start_minimized = value
        self.config_changed.emit()

    def set_show_confirmation_on_exit(self, value: bool) -> None:
        self._config.show_confirmation_on_exit = value
        self.config_changed.emit()

    def set_backup_period_minutes(self, value: int) -> None:
        self._config.backup_period_minutes = value
        self.config_changed.emit()

    def set_backup_retain_days(self, value: int) -> None:
        self._config.backup_retain_days = value
        self.config_changed.emit()

    def save(self) -> None:
        self._store.save(self._config)
        self.saved.emit()
        logger.info("Settings saved")
