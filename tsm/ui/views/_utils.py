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


def build_realm_tree(data: dict) -> dict[str, dict[str, list[dict]]]:
    """Parse raw API realms response into a {gv_label: {region: [realm_dict]}} tree.

    Only "retail" and "bcc" game versions are included (matches original TSM behaviour).
    Each realm dict has keys: id, name, gameVersion.
    """
    tree: dict[str, dict[str, list[dict]]] = {}
    for game_ver, realms in data.items():
        if not isinstance(realms, list):
            continue
        if game_ver == "retail":
            gv_label, api_gv = "Retail", "retail"
        elif game_ver == "bcc":
            gv_label, api_gv = "Progression", "bcc"
        else:
            continue
        tree.setdefault(gv_label, {})
        for realm in realms:
            region = realm.get("region", "")
            tree[gv_label].setdefault(region, []).append(
                {
                    "id": realm.get("id", 0),
                    "name": realm.get("name", ""),
                    "gameVersion": api_gv,
                }
            )
    for gv in tree.values():
        for region in gv:
            gv[region].sort(key=lambda r: r["name"])
    return tree
