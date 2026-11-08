"""One column header for several tables stacked under it.

Realm Data and Addon Versions show one table per game version. Each used to
carry its own header row, so the same column titles repeated under every group.
This header sits once above the scroll area and stays put while the groups
scroll. The tables hide their own headers and take their column widths from
here, so every column lines up across all groups.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QHeaderView, QSizePolicy, QTableWidget, QWidget

from tsm.ui.components._column_widths import CONTENTS, STRETCH, column_widths

__all__ = ["CONTENTS", "STRETCH", "SharedTableHeader"]

_MIN_SECTION = 16


class SharedTableHeader(QHeaderView):
    """Horizontal header that sizes the columns of every attached table.

    `specs` gives one entry per column: a fixed width in pixels, STRETCH or
    CONTENTS. `width_source` is the widget whose width the tables fill, the
    scroll area's content widget; its resizes trigger a new layout.
    """

    def __init__(self, labels: list[str], specs: list[int], width_source: QWidget, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        if len(labels) != len(specs):
            raise ValueError("one spec per column label")
        self._specs = list(specs)
        self._tables: list[QTableWidget] = []
        self._source = width_source
        self._sync_pending = False

        model = QStandardItemModel(0, len(labels), self)
        model.setHorizontalHeaderLabels(labels)
        self.setModel(model)
        self.setSectionsClickable(False)
        self.setSectionsMovable(False)
        self.setStretchLastSection(False)
        self.setMinimumSectionSize(_MIN_SECTION)
        self.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        # One row tall, however much room the layout around it has spare.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        width_source.installEventFilter(self)

    def attach(self, table: QTableWidget) -> None:
        """Hide the table's own header and size its columns from this one."""
        hdr = table.horizontalHeader()
        hdr.setVisible(False)
        hdr.setMinimumSectionSize(_MIN_SECTION)
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self._tables.append(table)
        self.schedule_sync()

    def schedule_sync(self) -> None:
        """Lay the columns out again once control returns to the event loop.

        Call after refilling a table: a CONTENTS column may have to grow.
        Several calls in a row cost a single layout.
        """
        if not self._sync_pending:
            self._sync_pending = True
            QTimer.singleShot(0, self.sync)

    def sync(self) -> None:
        self._sync_pending = False
        content = [self._content_width(col) for col in range(len(self._specs))]
        frame = 2 * self._tables[0].frameWidth() if self._tables else 0
        widths = column_widths(
            self._specs, content, total=self._source.width() - frame, minimum=_MIN_SECTION
        )
        for col, width in enumerate(widths):
            self.resizeSection(col, width)
            for table in self._tables:
                table.setColumnWidth(col, width)

    def _content_width(self, col: int) -> int:
        if self._specs[col] != CONTENTS:
            return 0
        width = self.sectionSizeFromContents(col).width()
        for table in self._tables:
            if table.rowCount():
                width = max(width, table.sizeHintForColumn(col))
        return width

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._source and event.type() == QEvent.Type.Resize:
            self.schedule_sync()
        return super().eventFilter(watched, event)
