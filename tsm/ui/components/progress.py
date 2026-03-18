"""Download progress indicator widget."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget


class ProgressWidget(QWidget):
    def __init__(self, label: str = "Loading...", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self._label = QLabel(label)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)

        self._bar = QProgressBar()
        self._bar.setRange(0, 0)  # Indeterminate by default
        layout.addWidget(self._bar)

    def set_label(self, text: str) -> None:
        self._label.setText(text)

    def set_progress(self, value: int, maximum: int = 100) -> None:
        self._bar.setRange(0, maximum)
        self._bar.setValue(value)

    def set_indeterminate(self) -> None:
        self._bar.setRange(0, 0)
