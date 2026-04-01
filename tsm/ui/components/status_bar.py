"""Custom status bar widget."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import QLabel, QSizePolicy, QStatusBar

from tsm.ui.components.hover_button import HoverIconButton

_ASSETS = Path(__file__).parent.parent / "assets"
_GITHUB_URL = "https://github.com/exceptionptr/tsm-app-linux"

_GITHUB_ICON = QIcon(str(_ASSETS / "github.svg"))
_GITHUB_ICON_HOVER = QIcon(str(_ASSETS / "github-hover.svg"))
_LOGS_ICON = QIcon(str(_ASSETS / "logs.svg"))
_LOGS_ICON_HOVER = QIcon(str(_ASSETS / "logs-hover.svg"))
_SETTINGS_ICON = QIcon(str(_ASSETS / "settings.svg"))
_SETTINGS_ICON_HOVER = QIcon(str(_ASSETS / "settings-hover.svg"))


def _make_statusbar_button(icon: QIcon, icon_hover: QIcon, tooltip: str) -> HoverIconButton:
    """Transparent icon-only button for the status bar."""
    btn = HoverIconButton(icon, icon_hover)
    btn.setIconSize(QSize(18, 18))
    btn.setFixedSize(26, 26)
    btn.setToolTip(tooltip)
    btn.setObjectName("statusbar-icon")
    return btn


class TSMStatusBar(QStatusBar):
    settings_requested: Signal = Signal()
    logs_requested: Signal = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeGripEnabled(False)

        self._status_label = QLabel("Checking status…")
        self.addWidget(self._status_label, 1)

        self._update_label = QLabel()
        self._update_label.setStyleSheet("color: #f0a500;")
        self._update_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self._update_label.setVisible(False)
        self.addWidget(self._update_label, 0)

        github_btn = _make_statusbar_button(_GITHUB_ICON, _GITHUB_ICON_HOVER, "View on GitHub")
        github_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(_GITHUB_URL))
        )
        self.addPermanentWidget(github_btn)

        logs_btn = _make_statusbar_button(_LOGS_ICON, _LOGS_ICON_HOVER, "View session logs")
        logs_btn.clicked.connect(self.logs_requested)
        self.addPermanentWidget(logs_btn)

        settings_btn = _make_statusbar_button(_SETTINGS_ICON, _SETTINGS_ICON_HOVER, "Settings")
        settings_btn.clicked.connect(self.settings_requested)
        self.addPermanentWidget(settings_btn)

    def set_update_available(self, version: str) -> None:
        """Show an amber update notification label to the left of the icon buttons."""
        self._update_label.setText(f"New version {version} available")
        self._update_label.setVisible(True)

    def set_status(self, msg: str) -> None:
        self._status_label.setText(msg)
        if msg.startswith("⚠"):
            self._status_label.setStyleSheet("color: #f44336;")
        else:
            self._status_label.setStyleSheet("")
