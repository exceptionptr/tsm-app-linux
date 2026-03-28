"""Generic icon-swapping button for hover effects."""

from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QPushButton


class HoverIconButton(QPushButton):
    """Button that swaps its icon when hovered."""

    def __init__(self, icon_normal: QIcon, icon_hover: QIcon, parent=None) -> None:
        super().__init__(parent)
        self._icon_normal = icon_normal
        self._icon_hover = icon_hover
        self.setIcon(icon_normal)

    def enterEvent(self, event) -> None:
        self.setIcon(self._icon_hover)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.setIcon(self._icon_normal)
        super().leaveEvent(event)
