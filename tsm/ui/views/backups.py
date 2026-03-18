"""Backups tab."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tsm.core.services.backup import _BACKUP_DIR, _KEEP_DIR, BackupService

logger = logging.getLogger(__name__)


class BackupsView(QWidget):
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

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["System ID", "Account", "Timestamp", "Type"])
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        vbox.addWidget(self._table, 1)

        self._table.doubleClicked.connect(self._on_double_click)

        # Bottom bar
        bottom = QWidget()
        bottom.setObjectName("realm-bottom")
        row = QHBoxLayout(bottom)
        row.setContentsMargins(8, 8, 8, 8)
        hint = QLabel("Double-click on a backup to restore or delete it.")
        hint.setObjectName("hint")
        row.addWidget(hint)
        row.addStretch()
        self._backup_now_btn = QPushButton("Backup Now")
        self._backup_now_btn.setObjectName("refresh-btn")
        self._backup_now_btn.clicked.connect(self._on_backup_now)
        row.addWidget(self._backup_now_btn)
        vbox.addWidget(bottom)

    def _refresh(self) -> None:
        backups = _list_backups()
        self._table.setRowCount(len(backups))
        for row, (sys_id, account, timestamp, _, is_manual) in enumerate(backups):
            self._set_cell(row, 0, sys_id)
            self._set_cell(row, 1, account)
            self._set_cell(row, 2, timestamp)
            self._set_cell(row, 3, "Manual" if is_manual else "Automatic")
        self._update_backup_btn()

    def _update_backup_btn(self) -> None:
        """Disable Backup Now for the remainder of the 1-minute rate-limit window."""
        import time

        manual_backups = [b for b in _list_backups() if b[4]]
        if not manual_backups:
            self._backup_now_btn.setEnabled(True)
            self._backup_now_btn.setText("Backup Now")
            return
        most_recent_mtime = max(b[3].stat().st_mtime for b in manual_backups)
        remaining = 60.0 - (time.time() - most_recent_mtime)
        if remaining > 0:
            self._backup_now_btn.setEnabled(False)
            self._backup_now_btn.setText(f"Backup Now ({int(remaining) + 1}s)")
            QTimer.singleShot(1000, self._update_backup_btn)
        else:
            self._backup_now_btn.setEnabled(True)
            self._backup_now_btn.setText("Backup Now")

    def _set_cell(self, row: int, col: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, col, item)

    def _on_backup_now(self) -> None:
        if self._backup_now_fn is None:
            return
        self._backup_now_btn.setEnabled(False)
        self._backup_now_btn.setText("Backing up…")
        self._backup_now_fn(self._on_backup_done)

    def _on_backup_done(self) -> None:
        self._refresh()

    def _on_double_click(self, index) -> None:
        from PySide6.QtWidgets import QDialog, QMessageBox, QSizePolicy

        row = index.row()
        backups = _list_backups()
        if row >= len(backups):
            return
        _, _, _, zip_path, _ = backups[row]

        dlg = QDialog(self)
        dlg.setWindowTitle("Backup")
        dlg.setFixedSize(360, 130)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(0)

        text_label = QLabel("What would you like to do with")
        name_label = QLabel(zip_path.name)
        name_label.setStyleSheet("color: #f26522;")
        layout.addWidget(text_label)
        layout.addWidget(name_label)
        layout.addSpacing(14)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        restore_btn = QPushButton("Restore")
        delete_btn = QPushButton("Delete")
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondary")

        for btn in (restore_btn, delete_btn, cancel_btn):
            btn.setFixedHeight(28)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        btn_row.addWidget(restore_btn)
        btn_row.addWidget(delete_btn)
        btn_row.addSpacing(16)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        action: dict = {}
        def _accept_restore() -> None:
            action.update(v="restore")
            dlg.accept()

        def _accept_delete() -> None:
            action.update(v="delete")
            dlg.accept()

        restore_btn.clicked.connect(_accept_restore)
        delete_btn.clicked.connect(_accept_delete)
        cancel_btn.clicked.connect(dlg.reject)
        dlg.exec()

        if action.get("v") == "restore":
            if self._backup_svc is None:
                QMessageBox.warning(self, "TSM", "Backup service not available.")
                return
            ok = self._backup_svc.restore(zip_path)
            if ok:
                QMessageBox.information(self, "TSM", "Backup restored successfully.")
            else:
                QMessageBox.warning(self, "TSM", "Failed to restore backup.")
        elif action.get("v") == "delete":
            reply = QMessageBox.question(
                self,
                "Delete Backup",
                f"Permanently delete {zip_path.name}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    zip_path.unlink()
                except Exception as e:
                    QMessageBox.warning(self, "TSM", f"Failed to delete backup:\n{e}")
                self._refresh()


def _list_backups() -> list[tuple[str, str, str, Path, bool]]:
    """Return (system_id, account, timestamp, path, is_manual) tuples, newest first."""
    from datetime import datetime

    result = []
    for is_manual, directory in ((True, _KEEP_DIR), (False, _BACKUP_DIR)):
        if not directory.exists():
            continue
        for f in directory.glob("*.zip"):
            parts = f.stem.split("_", 2)
            if len(parts) < 3:
                continue
            sys_id, account, ts_raw = parts
            try:
                ts = datetime.strptime(ts_raw, "%Y%m%d%H%M%S")
                ts_display = ts.strftime("%-m/%-d/%Y %-I:%M %p")
            except ValueError:
                ts_display = ts_raw
            result.append((sys_id, account, ts_display, f, is_manual))
    result.sort(key=lambda x: x[3].stat().st_mtime, reverse=True)
    return result
