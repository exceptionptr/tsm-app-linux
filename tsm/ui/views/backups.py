"""Backups tab."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import QRegularExpression, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from tsm.core.services.backup import _BACKUP_DIR, _KEEP_DIR, BackupService
from tsm.ui.components.hover_button import HoverIconButton
from tsm.ui.views._utils import set_table_cell, start_rate_limit_countdown

logger = logging.getLogger(__name__)

_ASSETS = Path(__file__).parent.parent / "assets"
_ICON_RESTORE = QIcon(str(_ASSETS / "archive-restore.svg"))
_ICON_RESTORE_HOVER = QIcon(str(_ASSETS / "archive-restore-hover.svg"))
_ICON_TRASH = QIcon(str(_ASSETS / "trash.svg"))
_ICON_TRASH_HOVER = QIcon(str(_ASSETS / "trash-hover.svg"))

_NAME_MAX_LENGTH = 40

# Fixed pixel width for the Type column - wide enough for "Manual" + label padding + layout margins
_TYPE_COL_WIDTH = 92

# Only allow alphanumeric, spaces, hyphens, underscores in backup names
_NAME_VALIDATOR = QRegularExpressionValidator(QRegularExpression(r"[\w\s\-]*"))


def _fmt_size(size_bytes: int) -> str:
    if size_bytes >= 1_000_000:
        return f"{size_bytes / 1_000_000:.1f} MB"
    return f"{size_bytes / 1_000:.0f} KB"


def _make_type_tag_cell(is_manual: bool) -> QWidget:
    """Transparent cell widget with a compact Auto/Manual tag label."""
    text = "Manual" if is_manual else "Auto"
    color = "#f26522" if is_manual else "#888888"

    w = QWidget()
    w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    w.setStyleSheet("background: transparent;")
    layout = QHBoxLayout(w)
    layout.setContentsMargins(6, 0, 6, 0)
    layout.setSpacing(0)

    lbl = QLabel(text)
    lbl.setFixedWidth(58)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setContentsMargins(0, 2, 0, 2)
    lbl.setStyleSheet(
        f"color: {color}; border: 1px solid {color}; border-radius: 3px;"
        " font-size: 11px; background: transparent;"
    )
    layout.addWidget(lbl)
    layout.addStretch()
    return w


def _make_icon_button(icon_normal: QIcon, icon_hover: QIcon) -> HoverIconButton:
    btn = HoverIconButton(icon_normal, icon_hover)
    btn.setObjectName("row-action")
    btn.setIconSize(QSize(14, 14))
    return btn


class BackupsView(QWidget):
    stats_updated: Signal = Signal(str)

    def __init__(
        self, backup_service: BackupService | None = None, backup_now_fn=None, parent=None
    ):
        super().__init__(parent)
        self._backup_svc = backup_service
        self._backup_now_fn = backup_now_fn
        self._setup_ui()
        self._refresh()

    def _setup_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        # Table: Account | Timestamp | Size | Name | Type | restore | delete
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["Account", "Timestamp", "Size", "Name", "Type", "", ""]
        )
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(28)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(4, _TYPE_COL_WIDTH)
        self._table.setColumnWidth(5, 28)
        self._table.setColumnWidth(6, 28)
        hdr.setMinimumSectionSize(16)
        vbox.addWidget(self._table, 1)

        # Bottom toolbar
        toolbar = QWidget()
        toolbar.setObjectName("realm-bottom")
        toolbar_row = QHBoxLayout(toolbar)
        toolbar_row.setContentsMargins(8, 8, 8, 8)
        toolbar_row.setSpacing(6)

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Name this backup (optional)...")
        self._name_input.setMaxLength(_NAME_MAX_LENGTH)
        self._name_input.setValidator(_NAME_VALIDATOR)
        self._name_input.setFixedHeight(32)
        toolbar_row.addWidget(self._name_input, 1)

        self._backup_now_btn = QPushButton("Backup Now")
        self._backup_now_btn.setObjectName("refresh-btn")
        self._backup_now_btn.setFixedHeight(32)
        self._backup_now_btn.clicked.connect(self._on_backup_now)
        toolbar_row.addWidget(self._backup_now_btn)

        vbox.addWidget(toolbar)

        self._update_backup_btn()

    def _refresh(self) -> None:
        backups = _list_backups()
        self._table.setRowCount(len(backups))
        total_bytes = 0
        for row, (account, timestamp, size_bytes, _path, is_manual, name) in enumerate(backups):
            total_bytes += size_bytes
            set_table_cell(self._table, row, 0, account)
            set_table_cell(self._table, row, 1, timestamp)
            set_table_cell(self._table, row, 2, _fmt_size(size_bytes))
            # Name column: Qt elides text automatically when column is too narrow
            set_table_cell(self._table, row, 3, name)
            self._table.setCellWidget(row, 4, _make_type_tag_cell(is_manual))

            restore_btn = _make_icon_button(_ICON_RESTORE, _ICON_RESTORE_HOVER)
            restore_btn.clicked.connect(lambda _=False, r=row: self._on_restore(r))
            self._table.setCellWidget(row, 5, restore_btn)

            delete_btn = _make_icon_button(_ICON_TRASH, _ICON_TRASH_HOVER)
            delete_btn.clicked.connect(lambda _=False, r=row: self._on_delete(r))
            self._table.setCellWidget(row, 6, delete_btn)

        count = len(backups)
        if count == 0:
            self.stats_updated.emit("No backups stored.")
        else:
            plural = "s" if count != 1 else ""
            self.stats_updated.emit(
                f"{count} backup{plural} stored  -  {_fmt_size(total_bytes)} total"
            )
        self._update_backup_btn()

    def _update_backup_btn(self) -> None:
        """Disable Backup Now for the remainder of the 1-minute rate-limit window."""
        manual_backups = [b for b in _list_backups() if b[4]]
        if not manual_backups:
            self._backup_now_btn.setEnabled(True)
            self._backup_now_btn.setText("Backup Now")
            return
        most_recent_mtime = max(b[3].stat().st_mtime for b in manual_backups)
        start_rate_limit_countdown(
            self._backup_now_btn,
            "Backup Now",
            lambda: 60.0 - (time.time() - most_recent_mtime),
        )

    def _on_backup_now(self) -> None:
        if self._backup_now_fn is None:
            return
        name = self._name_input.text().strip()
        self._backup_now_btn.setEnabled(False)
        self._backup_now_btn.setText("Backing up...")
        self._backup_now_fn(name, self._on_backup_done)

    def _on_backup_done(self) -> None:
        self._name_input.clear()
        self._refresh()

    def _on_restore(self, row: int) -> None:
        backups = _list_backups()
        if row >= len(backups):
            return
        _, _, _, zip_path, _, _ = backups[row]
        reply = QMessageBox.question(
            self,
            "Restore Backup",
            f"Restore {zip_path.name}?\n\nThis will overwrite your current SavedVariables.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if self._backup_svc is None:
            QMessageBox.warning(self, "TSM", "Backup service not available.")
            return
        ok = self._backup_svc.restore(zip_path)
        if ok:
            QMessageBox.information(self, "TSM", "Backup restored successfully.")
        else:
            QMessageBox.warning(self, "TSM", "Failed to restore backup.")

    def _on_delete(self, row: int) -> None:
        backups = _list_backups()
        if row >= len(backups):
            return
        _, _, _, zip_path, _, _ = backups[row]
        reply = QMessageBox.question(
            self,
            "Delete Backup",
            f"Permanently delete {zip_path.name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if self._backup_svc is None:
            QMessageBox.warning(self, "TSM", "Backup service not available.")
            return
        if not self._backup_svc.delete(zip_path):
            QMessageBox.warning(self, "TSM", "Failed to delete backup.")
        self._refresh()


def _list_backups() -> list[tuple[str, str, int, Path, bool, str]]:
    """Return (account, ts_display, size_bytes, path, is_manual, name) tuples, newest first."""
    from datetime import datetime

    result = []
    for is_manual, directory in ((True, _KEEP_DIR), (False, _BACKUP_DIR)):
        if not directory.exists():
            continue
        for f in directory.glob("*.zip"):
            parts = f.stem.split("_", 3)
            if len(parts) < 3:
                continue
            account = parts[1]
            ts_raw = parts[2]
            name = parts[3] if len(parts) > 3 else ""
            try:
                ts = datetime.strptime(ts_raw, "%Y%m%d%H%M%S")
                ts_display = ts.strftime("%-m/%-d/%Y %-I:%M %p")
            except ValueError:
                ts_display = ts_raw
            try:
                size_bytes = f.stat().st_size
            except OSError:
                size_bytes = 0
            result.append((account, ts_display, size_bytes, f, is_manual, name))
    result.sort(key=lambda x: x[3].stat().st_mtime, reverse=True)
    return result
