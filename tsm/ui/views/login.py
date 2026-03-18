"""Login dialog view."""

from __future__ import annotations

import logging

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


class LoginView(QDialog):
    login_successful = Signal()

    def __init__(self, app_vm: AppViewModel, auth_service=None, parent=None):
        super().__init__(parent)
        self._app_vm = app_vm
        self._auth_service = auth_service
        self._setup_ui()
        self.setWindowTitle("TSM - Login")
        self.setMinimumWidth(360)
        self.setModal(True)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(32, 32, 32, 32)

        # Title
        title = QLabel("TradeSkillMaster")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Sign in to your TSM account")
        subtitle.setObjectName("subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(8)

        # Username
        self._username = QLineEdit()
        self._username.setPlaceholderText("Username or Email")
        layout.addWidget(self._username)

        # Password
        self._password = QLineEdit()
        self._password.setPlaceholderText("Password")
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self._password)

        # Remember me
        self._remember = QCheckBox("Remember me")
        layout.addWidget(self._remember)

        # Error label
        self._error_label = QLabel()
        self._error_label.setObjectName("status-error")
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_label.hide()
        layout.addWidget(self._error_label)

        # Login button
        self._login_btn = QPushButton("Sign In")
        self._login_btn.clicked.connect(self._on_login)
        self._login_btn.setDefault(True)
        layout.addWidget(self._login_btn)

        self._password.returnPressed.connect(self._on_login)

    def _on_login(self) -> None:
        username = self._username.text().strip()
        password = self._password.text()
        if not username or not password:
            self._show_error("Please enter username and password")
            return

        self._login_btn.setEnabled(False)
        self._login_btn.setText("Signing in...")
        self._error_label.hide()

        if self._auth_service is None:
            self._show_error("Auth service not configured")
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
        self._show_error(f"Login failed: {error_msg}")

    def _show_error(self, msg: str) -> None:
        self._error_label.setText(msg)
        self._error_label.show()
