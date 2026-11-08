"""Login dialog: sign in through the TSM login page in the system browser.

The account server only accepts the browser login for desktop apps now, so
there are no email and password fields: the button opens the login page, the
dialog waits for the browser to hand the result back on a local port, and the
link is shown for copying in case no browser opened.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import Future
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from tsm.ui.viewmodels.app_vm import AppViewModel
from tsm.workers.bridge import AsyncBridge

logger = logging.getLogger(__name__)


def _format_auth_error(raw: str) -> str:
    """Turn an exception string into a concise user-facing message."""
    low = raw.lower()
    if "timed out" in low and "login" in low:
        return "The sign-in was not completed in time. Please try again."
    m = re.match(r"^(\d{3})\b", raw)
    if m:
        code = int(m.group(1))
        if code == 429:
            return "Too many login attempts. Please wait and try again."
        if code >= 500:
            return f"TSM server error ({code}). Please try again later."
        return f"Login failed (HTTP {code})."
    if any(k in low for k in ("connect", "timeout", "network", "ssl", "name resolution")):
        return "Unable to reach TSM servers. Check your internet connection."
    if raw and len(raw) < 160:
        return f"Login failed: {raw}"
    return "Login failed. Please try again."


class LoginView(QDialog):
    login_successful = Signal()
    _url_ready = Signal(str)  # from the async thread

    def __init__(self, app_vm: AppViewModel, auth_service=None, parent=None):
        super().__init__(parent)
        self._app_vm = app_vm
        self._auth_service = auth_service
        self._future: Future[Any] | None = None
        self._cancelled = False
        self._url_ready.connect(self._show_url)
        self._setup_ui()
        self.setWindowTitle("TSM - Sign In")
        self.setFixedWidth(480)
        self.setModal(True)
        if getattr(auth_service, "migrated_from_password", False):
            self._info.setText(
                "TSM now signs in through its website. Please sign in once more; "
                "your old saved password has been removed."
            )

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(32, 20, 32, 20)

        self._info = QLabel("Sign in with your TradeSkillMaster account in your web browser.")
        self._info.setWordWrap(True)
        self._info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._info)

        self._remember = QCheckBox("Remember me")
        self._remember.setChecked(True)
        layout.addWidget(self._remember)

        # Shown once the login page has been opened.
        self._url_row = QHBoxLayout()
        self._url_edit = QLineEdit()
        self._url_edit.setReadOnly(True)
        self._url_edit.setToolTip("Open this link if no browser window appeared")
        self._copy_btn = QPushButton("Copy link")
        self._copy_btn.setObjectName("secondary")
        self._copy_btn.clicked.connect(self._copy_url)
        self._url_row.addWidget(self._url_edit, 1)
        self._url_row.addWidget(self._copy_btn)
        layout.addLayout(self._url_row)
        self._set_url_visible(False)

        self._error_label = QLabel()
        self._error_label.setObjectName("status-error")
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_label.setWordWrap(True)
        self._error_label.setMinimumHeight(32)
        layout.addWidget(self._error_label)

        buttons = QHBoxLayout()
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setObjectName("secondary")
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._cancel_btn.setVisible(False)
        self._login_btn = QPushButton("Sign in with browser")
        self._login_btn.clicked.connect(self._on_login)
        self._login_btn.setDefault(True)
        buttons.addWidget(self._cancel_btn)
        buttons.addWidget(self._login_btn, 1)
        layout.addLayout(buttons)

    def _set_url_visible(self, visible: bool) -> None:
        self._url_edit.setVisible(visible)
        self._copy_btn.setVisible(visible)

    def _show_url(self, url: str) -> None:
        self._url_edit.setText(url)
        self._url_edit.setCursorPosition(0)
        self._set_url_visible(True)

    def _copy_url(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._url_edit.text())
        self._copy_btn.setText("Copied")
        QTimer.singleShot(1500, lambda: self._copy_btn.setText("Copy link"))

    def _on_login(self) -> None:
        if self._auth_service is None:
            self._show_error("Auth service not configured.")
            return
        self._cancelled = False
        self._login_btn.setEnabled(False)
        self._login_btn.setText("Waiting for the browser...")
        self._cancel_btn.setVisible(True)
        self._remember.setEnabled(False)
        self._error_label.clear()

        bridge = AsyncBridge(self)
        bridge.result_ready.connect(self._on_login_success)
        bridge.error_occurred.connect(self._on_login_error)
        self._future = bridge.run(
            self._auth_service.login(
                remember_me=self._remember.isChecked(), on_url=self._url_ready.emit
            )
        )

    def _on_cancel(self) -> None:
        self._cancelled = True
        if self._future is not None:
            self._future.cancel()
        self._reset()

    def _reset(self) -> None:
        self._future = None
        self._login_btn.setEnabled(True)
        self._login_btn.setText("Sign in with browser")
        self._cancel_btn.setVisible(False)
        self._remember.setEnabled(True)
        self._set_url_visible(False)

    def _on_login_success(self, session) -> None:
        if session.remember_failed:
            QMessageBox.warning(
                self,
                "TSM - Remember me",
                "You are signed in, but your login could not be saved because the "
                "system keyring is not available.\n\n"
                "Make sure a Secret Service provider such as GNOME Keyring or KWallet "
                "is running and unlocked. Until then you will be asked to sign in "
                "each time the app starts.",
            )
        self._app_vm.on_login_success(session)
        self.login_successful.emit()
        self.accept()

    def _on_login_error(self, error_msg: str) -> None:
        if self._cancelled:
            return
        self._reset()
        self._show_error(_format_auth_error(error_msg))

    def _show_error(self, msg: str) -> None:
        self._error_label.setText(msg)

    def reject(self) -> None:
        if self._future is not None:
            self._future.cancel()
        super().reject()
