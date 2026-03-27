"""Custom status bar widget."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import QLabel, QPushButton, QStatusBar

_ASSETS = Path(__file__).parent.parent / "assets"
_GITHUB_URL = "https://github.com/exceptionptr/tsm-app-linux"

_GITHUB_ICON = QIcon(str(_ASSETS / "github.svg"))
_GITHUB_ICON_HOVER = QIcon(str(_ASSETS / "github-hover.svg"))
_SETTINGS_ICON = QIcon(str(_ASSETS / "settings.svg"))
_SETTINGS_ICON_HOVER = QIcon(str(_ASSETS / "settings-hover.svg"))


class _IconButton(QPushButton):
    """Transparent icon-only button that swaps icon on hover."""

    def __init__(self, icon: QIcon, icon_hover: QIcon, tooltip: str, parent=None) -> None:
        super().__init__(parent)
        self._icon = icon
        self._icon_hover = icon_hover
        self.setIcon(icon)
        self.setIconSize(QSize(18, 18))
        self.setFixedSize(26, 26)
        self.setToolTip(tooltip)
        self.setObjectName("statusbar-icon")

    def enterEvent(self, event: object) -> None:
        self.setIcon(self._icon_hover)
        super().enterEvent(event)  # type: ignore[arg-type]

    def leaveEvent(self, event: object) -> None:
        self.setIcon(self._icon)
        super().leaveEvent(event)  # type: ignore[arg-type]


class TSMStatusBar(QStatusBar):
    settings_requested: Signal = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeGripEnabled(False)

        self._status_label = QLabel("Checking status…")
        self.addWidget(self._status_label, 1)

        github_btn = _IconButton(_GITHUB_ICON, _GITHUB_ICON_HOVER, "View on GitHub")
        github_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(_GITHUB_URL))
        )
        self.addPermanentWidget(github_btn)

        settings_btn = _IconButton(_SETTINGS_ICON, _SETTINGS_ICON_HOVER, "Settings")
        settings_btn.clicked.connect(self.settings_requested)
        self.addPermanentWidget(settings_btn)

    def set_status(self, msg: str) -> None:
        self._status_label.setText(msg)
