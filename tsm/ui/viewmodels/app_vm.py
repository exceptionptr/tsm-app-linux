"""Top-level application view model."""

from __future__ import annotations

import logging

from PySide6.QtCore import Property, QObject, Signal

from tsm.core.models.auth import UserSession

logger = logging.getLogger(__name__)


class AppViewModel(QObject):
    authenticated_changed = Signal(bool)
    status_changed = Signal(str)
    error_occurred = Signal(str)
    backup_notification = Signal(str)  # emitted from any thread via invokeMethod
    addon_notification = Signal(str)  # emitted when addon files are actually installed
    realm_data_received = Signal(object)  # emitted by scheduler job with AuctionData result

    def __init__(self, auth_service=None, parent: QObject | None = None):
        super().__init__(parent)
        self._auth_service = auth_service
        self._authenticated = False
        self._status = "Ready"
        self._session: UserSession | None = None

    @Property(bool, notify=authenticated_changed)
    def authenticated(self) -> bool:
        return self._authenticated

    @Property(str, notify=status_changed)
    def status(self) -> str:
        return self._status

    def set_authenticated(self, value: bool) -> None:
        if self._authenticated != value:
            self._authenticated = value
            self.authenticated_changed.emit(value)

    def set_status(self, msg: str) -> None:
        self._status = msg
        self.status_changed.emit(msg)

    def on_login_success(self, session: UserSession) -> None:
        self._session = session
        self.set_authenticated(True)
        self.set_status(f"Logged in as {session.username}")

    def on_logout(self) -> None:
        self._session = None
        self.set_authenticated(False)
        self.set_status("Logged out")
