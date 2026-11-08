"""Shared UI utilities for view modules."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QComboBox, QPushButton, QTableWidget, QTableWidgetItem


def populate_combo(combo: QComboBox, items: list[str]) -> None:
    """Clear and repopulate *combo* without firing currentIndexChanged signals."""
    combo.blockSignals(True)
    combo.clear()
    for item in items:
        combo.addItem(item)
    combo.blockSignals(False)


def set_table_cell(
    table: QTableWidget, row: int, col: int, text: str, color: str | None = None
) -> None:
    """Create a non-editable table cell, optionally with a foreground color."""
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if color:
        item.setForeground(QBrush(QColor(color)))
    table.setItem(row, col, item)


def table_content_height(table: QTableWidget, row_count: int) -> int:
    """Exact pixel height a table needs to show row_count rows with no scrollbar.

    Used to size tables nested inside a CollapsibleGroup, which animates the
    body between zero and this height.
    """
    header_h = table.horizontalHeader().sizeHint().height()
    if header_h < 1:
        header_h = 28  # sizeHint is unreliable before the first show
    return header_h + row_count * table.verticalHeader().defaultSectionSize()


def start_rate_limit_countdown(
    button: QPushButton,
    label: str,
    get_remaining: Callable[[], float],
) -> None:
    """Disable *button* with a countdown display until get_remaining() <= 0."""
    remaining = get_remaining()
    if remaining > 0:
        button.setEnabled(False)
        button.setText(f"{label} ({int(remaining) + 1}s)")
        QTimer.singleShot(1000, lambda: start_rate_limit_countdown(button, label, get_remaining))
    else:
        button.setEnabled(True)
        button.setText(label)
