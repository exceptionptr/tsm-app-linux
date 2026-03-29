"""Login dialog view."""

from __future__ import annotations

import logging
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from tsm.ui.viewmodels.app_vm import AppViewModel
from tsm.workers.bridge import AsyncBridge

logger = logging.getLogger(__name__)

# Maps HTTP status codes to user-friendly messages shown in the login dialog.
_STATUS_MESSAGES: dict[int, str] = {
    401: "Invalid email or password.",
    403: "Account access denied. Contact TSM support.",
    429: "Too many login attempts. Please wait and try again.",
}


def _format_auth_error(raw: str) -> str:
    """Convert a raw exception string into a concise user-facing message.

    aiohttp.ClientResponseError serialises as:
        "401, message='Unauthorized', url='https://...'"
    Other exceptions are treated as connectivity failures.
    """
    m = re.match(r"^(\d{3})\b", raw)
    if m:
        code = int(m.group(1))
        if code in _STATUS_MESSAGES:
            return _STATUS_MESSAGES[code]
        if code >= 500:
            return f"TSM server error ({code}). Please try again later."
        return f"Login failed (HTTP {code})."
    if any(k in raw.lower() for k in ("connect", "timeout", "network", "ssl")):
        return "Unable to reach TSM servers. Check your internet connection."
    return "Login failed. Please try again."


class LoginView(QDialog):
    login_successful = Signal()

    def __init__(self, app_vm: AppViewModel, auth_service=None, parent=None):
        super().__init__(parent)
        self._app_vm = app_vm
        self._auth_service = auth_service
        self._setup_ui()
        self.setWindowTitle("TSM - Login")
        self.setFixedSize(480, 240)
        self.setModal(True)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(32, 20, 32, 20)

        # Email
        self._username = QLineEdit()
        self._username.setPlaceholderText("Email")
        layout.addWidget(self._username)

        # Password
        self._password = QLineEdit()
        self._password.setPlaceholderText("Password")
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self._password)

        # Remember me
        self._remember = QCheckBox("Remember me")
        layout.addWidget(self._remember)

        # Error label - always in layout to reserve space; never resizes the dialog
        self._error_label = QLabel()
        self._error_label.setObjectName("status-error")
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_label.setWordWrap(True)
        self._error_label.setFixedHeight(32)
        layout.addWidget(self._error_label)

        # Login button
        self._login_btn = QPushButton("Sign In")
        self._login_btn.clicked.connect(self._on_login)
        self._login_btn.setDefault(True)
        layout.addWidget(self._login_btn)

    def _on_login(self) -> None:
        username = self._username.text().strip()
        password = self._password.text()
        if not username or not password:
            self._show_error("Please enter your email and password.")
            return

        self._login_btn.setEnabled(False)
        self._login_btn.setText("Signing in...")
        self._error_label.clear()

        if self._auth_service is None:
            self._show_error("Auth service not configured.")
            return

        remember_me = self._remember.isChecked()
        bridge = AsyncBridge(self)
        bridge.result_ready.connect(self._on_login_success)
        bridge.error_occurred.connect(self._on_login_error)
        bridge.run(self._auth_service.login(username, password, remember_me=remember_me))

    def _on_login_success(self, session) -> None:
        self._app_vm.on_login_success(session)
        self.login_successful.emit()
        self.accept()

    def _on_login_error(self, error_msg: str) -> None:
        self._login_btn.setEnabled(True)
        self._login_btn.setText("Sign In")
        self._show_error(_format_auth_error(error_msg))

    def _show_error(self, msg: str) -> None:
        self._error_label.setText(msg)
