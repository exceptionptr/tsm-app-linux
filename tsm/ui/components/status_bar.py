"""Custom status bar widget."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QStatusBar


class TSMStatusBar(QStatusBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeGripEnabled(False)
        self._status_label = QLabel("Checking status…")
        self.addWidget(self._status_label, 1)

    def set_status(self, msg: str) -> None:
        self._status_label.setText(msg)
