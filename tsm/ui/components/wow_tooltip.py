"""WoW-style item tooltip popup widget."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from tsm.ui.components._wowhead_html import _BORDER_COLORS, _wowhead_to_qt

__all__ = ["WowItemTooltip", "_wowhead_to_qt"]


class WowItemTooltip(QWidget):
    """Frameless WoW-style item tooltip that appears near the cursor."""

    def __init__(self, parent: QWidget | None = None) -> None:
        # ToolTip window type bypasses the WM on X11 so move() is respected.
        super().__init__(
            parent,
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._border_color = QColor("#9d9d9d")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(0)

        self._label = QLabel()
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(320)
        self._label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._label.setStyleSheet(
            "background: transparent; color: #ffffff; font-size: 12px;"
        )
        layout.addWidget(self._label)

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0d0d12"))
        painter.setPen(self._border_color)
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.end()

    def show_for(
        self, tooltip_html: str, quality: int, global_x: int, global_y: int
    ) -> None:
        self._border_color = QColor(_BORDER_COLORS.get(quality, "#9d9d9d"))
        self._label.setText(_wowhead_to_qt(tooltip_html))
        self.adjustSize()

        x = global_x + 14
        y = global_y + 14

        from PySide6.QtCore import QPoint
        screen = QApplication.screenAt(QPoint(global_x, global_y))
        if screen:
            sg = screen.availableGeometry()
            if x + self.width() > sg.right():
                x = global_x - self.width() - 4
            if y + self.height() > sg.bottom():
                y = global_y - self.height() - 4

        # Show first, then move - some WMs override position on first show.
        self.show()
        self.move(x, y)
        self.raise_()
        self.update()
