"""Single realm row widget for the realm list."""

from __future__ import annotations

import time

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from tsm.core.models.auction import RealmData


class RealmRowWidget(QWidget):
    def __init__(self, realm: RealmData, parent=None):
        super().__init__(parent)
        self._realm = realm
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        name_label = QLabel(f"{self._realm.realm_slug} ({self._realm.region})")
        layout.addWidget(name_label)
        layout.addStretch()

        age = int(time.time()) - self._realm.last_updated
        age_label = QLabel(f"Last sync: {_format_age(age)}")
        age_label.setObjectName("subtitle")
        layout.addWidget(age_label)


def _format_age(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    return f"{seconds // 3600}h ago"
