"""Login page shown when the TSM login window was closed or failed.

Like the official client, the app opens the TSM login window by itself (see
AppWindow.show_login). This page only appears when that did not lead to a
login: it shows what went wrong and one button that opens the window again.
"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout


def format_auth_error(raw: str) -> str:
    """Turn an exception string into a concise user-facing message."""
    low = raw.lower()
    if "window was closed" in low:
        return "The login window was closed."
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
    """Error text plus one button; accepting the dialog means "open the window again"."""

    def __init__(self, error: str = "", info: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("TSM - Sign In")
        self.setFixedWidth(480)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(32, 20, 32, 20)

        if info:
            info_label = QLabel(info)
            info_label.setWordWrap(True)
            info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(info_label)

        self._error_label = QLabel(error)
        self._error_label.setObjectName("status-error")
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_label.setWordWrap(True)
        self._error_label.setMinimumHeight(32)
        layout.addWidget(self._error_label)

        button = QPushButton("Login Again")
        button.setDefault(True)
        button.clicked.connect(self.accept)
        layout.addWidget(button)
