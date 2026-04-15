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


_GV_LABEL_MAP: dict[str, tuple[str, str]] = {
    "retail": ("Retail", "retail"),
    "bcc": ("Progression", "bcc"),
    "classic": ("Classic Era", "classic"),
    "anniversary": ("Anniversary", "anniversary"),
}

# Status endpoint keys that provide realm lists for game versions not covered
# by the realms2/list endpoint.  Maps status key -> (gv_label, api_gv).
_STATUS_REALM_KEYS: dict[str, tuple[str, str]] = {
    "extraAnniversaryRealms": ("Anniversary", "anniversary"),
    "extraClassicRealms": ("Classic Era", "classic"),
}


def build_realm_tree(
    realm_list: dict,
    status: dict | None = None,
) -> dict[str, dict[str, list[dict]]]:
    """Parse API responses into a {gv_label: {region: [realm_dict]}} tree.

    *realm_list* comes from ``realms2/list`` (has retail + bcc).
    *status* comes from ``GET /v2/status`` and supplies anniversary / classic
    realms via ``extraAnniversaryRealms`` / ``extraClassicRealms``.
    Each realm dict has keys: id, name, gameVersion.
    """
    tree: dict[str, dict[str, list[dict]]] = {}

    # 1) realms2/list — retail & bcc (and anything else the API returns)
    for game_ver, realms in realm_list.items():
        if not isinstance(realms, list):
            continue
        mapping = _GV_LABEL_MAP.get(game_ver)
        if mapping is None:
            continue
        gv_label, api_gv = mapping
        _insert_realms(tree, gv_label, api_gv, realms)

    # 2) status endpoint — anniversary & classic era
    if status:
        for status_key, (gv_label, api_gv) in _STATUS_REALM_KEYS.items():
            realms = status.get(status_key, [])
            if isinstance(realms, list) and realms:
                _insert_realms(tree, gv_label, api_gv, realms)

    for gv in tree.values():
        for region in gv:
            gv[region].sort(key=lambda r: r["name"])
    return tree


def _insert_realms(
    tree: dict[str, dict[str, list[dict]]],
    gv_label: str,
    api_gv: str,
    realms: list[dict],
) -> None:
    gv_node = tree.setdefault(gv_label, {})
    seen: set[tuple[str, str]] = set()
    for existing_realms in gv_node.values():
        for r in existing_realms:
            seen.add((r.get("name", ""), r.get("region", "")))

    for realm in realms:
        name = realm.get("name", "")
        region = realm.get("region", "")
        if (name, region) in seen:
            continue
        seen.add((name, region))
        gv_node.setdefault(region, []).append(
            {
                "id": realm.get("id", 0),
                "name": name,
                "gameVersion": api_gv,
            }
        )
