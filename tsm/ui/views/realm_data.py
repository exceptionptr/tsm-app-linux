"""Realm Data tab: matches original TSM layout."""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QDateTime, QLocale
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from tsm.ui.viewmodels.realm_vm import RealmViewModel
from tsm.ui.views._utils import set_table_cell, start_rate_limit_countdown

logger = logging.getLogger(__name__)

_GREEN = "#4caf50"
_YELLOW = "#ffc107"
_RED = "#f44336"


class RealmDataView(QWidget):
    def __init__(self, realm_vm: RealmViewModel, parent=None):
        super().__init__(parent)
        self._vm = realm_vm
        self._last_manual_refresh: float = 0.0
        self._vm.data_updated.connect(self._refresh)
        self._vm.loading_changed.connect(self._on_loading)
        self._setup_ui()

    def _setup_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Region/Realm", "AuctionDB", "Last Updated"])
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setMinimumSectionSize(100)
        vbox.addWidget(self._table, 1)

        # Bottom bar
        bottom = QWidget()
        bottom.setObjectName("realm-bottom")
        row = QHBoxLayout(bottom)
        row.setContentsMargins(8, 8, 8, 8)
        self._hint = QLabel("Double-click on a realm to remove it from the list above.")
        self._hint.setObjectName("hint")
        row.addWidget(self._hint)
        row.addStretch()
        self._refresh_btn = QPushButton("Refresh Now")
        self._refresh_btn.setObjectName("refresh-btn")
        self._refresh_btn.clicked.connect(self._on_refresh_now)
        row.addWidget(self._refresh_btn)
        vbox.addWidget(bottom)

        self._table.doubleClicked.connect(self._on_double_click)

    def _refresh(self) -> None:
        summaries = self._vm.summaries
        self._table.setRowCount(len(summaries))
        for row, s in enumerate(summaries):
            set_table_cell(self._table, row, 0, s.display_name)

            if s.auctiondb_status == "Up to date":
                adb_color = _GREEN
            elif s.auctiondb_status == "Outdated":
                adb_color = _RED
            else:
                adb_color = _YELLOW
            set_table_cell(self._table, row, 1, s.auctiondb_status, adb_color)

            dt_str = _fmt_ts(s.last_updated)
            set_table_cell(self._table, row, 2, dt_str)

    def _on_refresh_now(self) -> None:
        self._last_manual_refresh = time.time()
        self._vm.refresh_all()
        self._update_refresh_btn()

    def _update_refresh_btn(self) -> None:
        start_rate_limit_countdown(
            self._refresh_btn,
            "Refresh Now",
            lambda: 60.0 - (time.time() - self._last_manual_refresh),
        )

    def _on_loading(self, loading: bool) -> None:
        if loading:
            self._refresh_btn.setEnabled(False)
            self._refresh_btn.setText("Syncing…")
        else:
            self._update_refresh_btn()

    def _on_double_click(self, index) -> None:
        row = index.row()
        summaries = self._vm.summaries
        if row >= len(summaries):
            return
        s = summaries[row]

        # Regions cannot be removed (matches original behaviour)
        if s.is_region:
            QMessageBox.warning(self, "TSM", "Regions cannot be removed.")
            return

        reply = QMessageBox.question(
            self,
            "TSM",
            f"Are you sure you want to remove '{s.display_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            # Optimistically remove from local display, then call API + refresh
            self._vm.summaries.pop(row)
            self._refresh()
            self._vm.remove_realm(s.game_version, s.region, s.name)


def _fmt_ts(ts: int) -> str:
    if not ts:
        return "Never"
    dt = QDateTime.fromSecsSinceEpoch(ts)
    return QLocale.system().toString(dt, QLocale.FormatType.ShortFormat)
