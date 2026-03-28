"""Realm Data tab: matches original TSM layout."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import QDateTime, QLocale, QSize, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from tsm.ui.components.hover_button import HoverIconButton
from tsm.ui.viewmodels.realm_vm import RealmSummary, RealmViewModel
from tsm.ui.views._utils import populate_combo, set_table_cell

_ASSETS = Path(__file__).parent.parent / "assets"

logger = logging.getLogger(__name__)

_GREEN = "#4caf50"
_YELLOW = "#ffc107"
_RED = "#f44336"

# Realm data (AUCTIONDB_NON_COMMODITY_DATA) updates ~hourly
_REALM_GREEN = 2 * 3600   # < 2h  -> green
_REALM_YELLOW = 6 * 3600  # < 6h  -> yellow, else red

# Region data (AUCTIONDB_REGION_STAT) updates ~daily (MAX_DATA_AGE = 86400)
_REGION_GREEN = 26 * 3600   # < 26h -> green
_REGION_YELLOW = 50 * 3600  # < 50h -> yellow, else red


def _dot_color(status: str, last_updated: int, is_region: bool) -> str:
    if status == "Updating...":
        return _YELLOW
    if status == "Outdated":
        return _RED
    # "Up to date"
    if not last_updated:
        return _YELLOW
    age = time.time() - last_updated
    green_t = _REGION_GREEN if is_region else _REALM_GREEN
    yellow_t = _REGION_YELLOW if is_region else _REALM_YELLOW
    if age < green_t:
        return _GREEN
    if age < yellow_t:
        return _YELLOW
    return _RED


def _make_dot_cell(status: str, last_updated: int, is_region: bool) -> QWidget:
    color = _dot_color(status, last_updated, is_region)
    w = QWidget()
    w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    w.setStyleSheet("background: transparent;")
    layout = QHBoxLayout(w)
    layout.setContentsMargins(6, 0, 6, 0)
    layout.setSpacing(6)
    dot = QLabel()
    dot.setFixedSize(10, 10)
    dot.setStyleSheet(f"border-radius: 5px; background: {color};")
    lbl = QLabel(status)
    lbl.setStyleSheet("background: transparent;")
    layout.addWidget(dot)
    layout.addWidget(lbl)
    layout.addStretch()
    return w


_TRASH_ICON = QIcon(str(_ASSETS / "trash.svg"))
_TRASH_ICON_HOVER = QIcon(str(_ASSETS / "trash-hover.svg"))


class RealmDataView(QWidget):
    def __init__(self, realm_vm: RealmViewModel, realm_tree: dict | None = None, parent=None):
        super().__init__(parent)
        self._vm = realm_vm
        self._realm_tree: dict | None = realm_tree
        self._last_manual_refresh: float = 0.0
        self._vm.data_updated.connect(self._refresh)
        self._vm.loading_changed.connect(self._on_loading)
        self._setup_ui()
        if realm_tree is not None:
            self._populate_gv_combo()

    def _setup_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Region/Realm", "AuctionDB", "Last Updated", ""])
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(1, 120)
        self._table.setColumnWidth(3, 22)
        self._table.horizontalHeader().setMinimumSectionSize(16)
        vbox.addWidget(self._table, 1)

        vbox.addWidget(self._build_bottom())

    def _build_bottom(self) -> QWidget:
        bottom = QWidget()
        bottom.setObjectName("realm-bottom")
        outer = QHBoxLayout(bottom)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # Left group: realm selectors + add button
        self._gv_combo = QComboBox()
        self._gv_combo.setFixedWidth(110)
        self._gv_combo.currentIndexChanged.connect(self._on_gv_changed)
        outer.addWidget(self._gv_combo)

        self._region_combo = QComboBox()
        self._region_combo.setFixedWidth(80)
        self._region_combo.currentIndexChanged.connect(self._on_region_changed)
        outer.addWidget(self._region_combo)

        self._realm_combo = QComboBox()
        self._realm_combo.setMinimumWidth(80)
        outer.addWidget(self._realm_combo, 1)

        self._add_btn = QPushButton("+ Add Realm")
        self._add_btn.setObjectName("secondary")
        self._add_btn.clicked.connect(self._on_add_realm)
        outer.addWidget(self._add_btn)

        outer.addStretch()

        self._refresh_btn = QPushButton()
        self._refresh_btn.setIcon(QIcon(str(_ASSETS / "refresh-cw.svg")))
        self._refresh_btn.setIconSize(QSize(16, 16))
        self._refresh_btn.setFixedSize(32, 32)
        self._refresh_btn.setToolTip("Refresh Now - manually trigger an auction data sync")
        self._refresh_btn.clicked.connect(self._on_refresh_now)
        outer.addWidget(self._refresh_btn)

        # Disable add controls until realm tree is available
        if self._realm_tree is None:
            self._gv_combo.setEnabled(False)
            self._region_combo.setEnabled(False)
            self._realm_combo.setEnabled(False)
            self._add_btn.setEnabled(False)

        return bottom

    # ── Public API ───────────────────────────────────────────────────

    def set_realm_tree(self, tree: dict) -> None:
        """Called by app_window once the realm list pre-fetch completes."""
        self._realm_tree = tree
        self._gv_combo.setEnabled(True)
        self._region_combo.setEnabled(True)
        self._realm_combo.setEnabled(True)
        self._add_btn.setEnabled(True)
        self._populate_gv_combo()

    # ── Table ────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        summaries = self._vm.summaries
        self._table.setRowCount(len(summaries))
        for row, s in enumerate(summaries):
            set_table_cell(self._table, row, 0, s.display_name)
            dot = _make_dot_cell(s.auctiondb_status, s.last_updated, s.is_region)
            self._table.setCellWidget(row, 1, dot)
            dt_str = fmt_ts(s.last_updated)
            set_table_cell(self._table, row, 2, dt_str)
            self._table.setCellWidget(row, 3, self._make_delete_btn(row, s))

    def _make_delete_btn(self, row: int, summary: RealmSummary) -> HoverIconButton:
        btn = HoverIconButton(_TRASH_ICON, _TRASH_ICON_HOVER)
        btn.setObjectName("row-action")
        btn.setIconSize(QSize(14, 14))
        btn.clicked.connect(lambda _, r=row, s=summary: self._on_delete(r, s))
        return btn

    # ── Delete ───────────────────────────────────────────────────────

    def _on_delete(self, row: int, summary: RealmSummary) -> None:
        if summary.is_region:
            QMessageBox.warning(self, "TSM", "Regions cannot be removed.")
            return
        reply = QMessageBox.question(
            self,
            "TSM",
            f"Are you sure you want to remove '{summary.display_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._vm.summaries.pop(row)
            self._refresh()
            self._vm.remove_realm(summary.game_version, summary.region, summary.name)

    # ── Refresh ──────────────────────────────────────────────────────

    def _on_refresh_now(self) -> None:
        self._last_manual_refresh = time.time()
        self._vm.refresh_all()
        # Button state is managed entirely by _on_loading via the loading_changed signal

    def _update_refresh_btn(self) -> None:
        remaining = 60.0 - (time.time() - self._last_manual_refresh)
        if remaining > 0:
            self._refresh_btn.setEnabled(False)
            self._refresh_btn.setToolTip(f"Rate limited - available in {int(remaining) + 1}s")
            QTimer.singleShot(1000, self._update_refresh_btn)
        else:
            self._refresh_btn.setEnabled(True)
            self._refresh_btn.setToolTip("Refresh Now - manually trigger an auction data sync")

    def _on_loading(self, loading: bool) -> None:
        if loading:
            self._refresh_btn.setEnabled(False)
            self._refresh_btn.setToolTip("Syncing - auction data fetch in progress")
        else:
            self._update_refresh_btn()

    # ── Add Realm ────────────────────────────────────────────────────

    def _populate_gv_combo(self) -> None:
        populate_combo(self._gv_combo, sorted(self._realm_tree or {}))
        retail_idx = self._gv_combo.findText("Retail")
        self._gv_combo.setCurrentIndex(retail_idx if retail_idx >= 0 else 0)
        self._on_gv_changed(self._gv_combo.currentIndex())

    def _on_gv_changed(self, _: int) -> None:
        gv_label = self._gv_combo.currentText()
        regions = (
            sorted(self._realm_tree.get(gv_label, {}).keys())
            if self._realm_tree
            else []
        )
        populate_combo(self._region_combo, regions)
        self._on_region_changed(0)

    def _on_region_changed(self, _: int) -> None:
        gv_label = self._gv_combo.currentText()
        region = self._region_combo.currentText()
        realms = []
        if self._realm_tree:
            realms = self._realm_tree.get(gv_label, {}).get(region, [])
        self._realm_combo.clear()
        for r in realms:
            self._realm_combo.addItem(r["name"])

    def _on_add_realm(self) -> None:
        gv_label = self._gv_combo.currentText()
        region = self._region_combo.currentText()
        idx = self._realm_combo.currentIndex()
        if not self._realm_tree or not gv_label or not region or idx < 0:
            return
        realm_list = self._realm_tree.get(gv_label, {}).get(region, [])
        if idx >= len(realm_list):
            return
        realm = realm_list[idx]
        self._vm.add_realm(realm["gameVersion"], realm["id"])


def fmt_ts(ts: int) -> str:
    if not ts:
        return "Never"
    dt = QDateTime.fromSecsSinceEpoch(ts)
    return QLocale.system().toString(dt, QLocale.FormatType.ShortFormat)
