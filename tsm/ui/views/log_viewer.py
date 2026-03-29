"""Log viewer window: displays in-session log records in a styled table."""

from __future__ import annotations

import logging
import re
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from tsm.core.log_buffer import LogBuffer

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Row background colors per level (subtle, dark-theme friendly)
_BG: dict[int, str] = {
    logging.ERROR: "#3d1a1a",
    logging.CRITICAL: "#3d1a1a",
    logging.WARNING: "#3d2d0a",
}
# Level label text colors
_FG: dict[int, str] = {
    logging.ERROR: "#f44336",
    logging.CRITICAL: "#f44336",
    logging.WARNING: "#f26522",
    logging.DEBUG: "#888888",
}

_COL_TIME = 0
_COL_LEVEL = 1
_COL_LOGGER = 2
_COL_MESSAGE = 3


_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def _redact(text: str) -> str:
    """Replace email addresses with a placeholder for safe sharing."""
    return _EMAIL_RE.sub("[email redacted]", text)


def _format_records(records: list[logging.LogRecord]) -> str:
    """Format records as plain text matching the log file format, with PII redacted."""
    formatter = logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)
    return "\n".join(_redact(formatter.format(r)) for r in records)


class LogViewerWindow(QDialog):
    """Non-modal window that shows all log records from the current session."""

    def __init__(self, buffer: LogBuffer, parent=None) -> None:
        super().__init__(parent)
        self._buffer = buffer
        self._setup_ui()
        self.setWindowTitle("Logs - current session")
        self.resize(900, 500)
        self.setModal(False)
        self._populate()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Header: session start timestamp
        start_str = self._buffer.start_time.strftime(_DATE_FORMAT)
        header = QLabel(f"Session started {start_str}  |  showing up to 2,000 records")
        header.setObjectName("hint")
        layout.addWidget(header)

        # Table
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Time", "Level", "Logger", "Message"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setWordWrap(True)
        self._table.setStyleSheet(
            "QTableWidget { background-color: #191919; alternate-background-color: #262626; }"
        )
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(_COL_TIME, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_COL_LEVEL, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_COL_LOGGER, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(_COL_MESSAGE, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(_COL_TIME, 158)
        self._table.setColumnWidth(_COL_LEVEL, 75)
        self._table.setColumnWidth(_COL_LOGGER, 220)

        mono = QFont("Monospace")
        mono.setStyleHint(QFont.StyleHint.TypeWriter)
        mono.setPointSize(9)
        self._table.setFont(mono)

        layout.addWidget(self._table, 1)

        # Bottom button row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._copy_btn = QPushButton("Copy to Clipboard")
        self._copy_btn.setFixedHeight(32)
        self._copy_btn.clicked.connect(self._copy_to_clipboard)
        btn_row.addWidget(self._copy_btn)

        btn_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setObjectName("secondary")
        close_btn.setFixedHeight(32)
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

    def _populate(self) -> None:
        records = self._buffer.records
        self._table.setRowCount(len(records))
        for row, record in enumerate(records):
            ts = datetime.fromtimestamp(record.created).strftime(_DATE_FORMAT)
            level = record.levelname
            logger = record.name
            message = record.getMessage()

            items = [
                QTableWidgetItem(ts),
                QTableWidgetItem(level),
                QTableWidgetItem(logger),
                QTableWidgetItem(message),
            ]

            # Level-specific background overrides the alternating stripe.
            bg = _BG.get(record.levelno)
            fg = _FG.get(record.levelno)
            for col, item in enumerate(items):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
                )
                if bg:
                    item.setBackground(QColor(bg))
                if fg:
                    item.setForeground(QColor(fg))
                self._table.setItem(row, col, item)

        # Scroll to the most recent entry
        if records:
            self._table.scrollToBottom()

    def showEvent(self, event) -> None:
        """Refresh records each time the window is shown."""
        super().showEvent(event)
        self._populate()

    def _copy_to_clipboard(self) -> None:
        text = _format_records(self._buffer.records)
        QGuiApplication.clipboard().setText(text)
        self._copy_btn.setText("Copied!")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(2000, lambda: self._copy_btn.setText("Copy to Clipboard"))
