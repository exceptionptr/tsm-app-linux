"""Collapsible group: a clickable header over an animated body.

Shared by the Addon Versions and Realm Data tabs, which both present one group
per WoW game version. The caller supplies the body widget (normally a table) and
tells the group how tall that body wants to be.

The QSS object names are the historical `addon-group-*` ones so both tabs pick
up the existing styling in tsm_dark.qss unchanged.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

ANIM_MS = 180  # collapse/expand animation duration (ms)
_UNCONSTRAINED = 16777215  # Qt's QWIDGETSIZE_MAX, releases the height cap


class GroupHeader(QWidget):
    """Clickable group header with arrow, group name, side label and summary."""

    clicked: Signal = Signal()

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._label = label
        self.setObjectName("addon-group-header")
        self.setFixedHeight(32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(6)

        self._arrow = QLabel("▶")
        self._arrow.setObjectName("addon-group-arrow")
        self._arrow.setFixedWidth(12)
        layout.addWidget(self._arrow)

        self._name = QLabel(label)
        self._name.setObjectName("addon-group-name")
        layout.addWidget(self._name)

        self._side = QLabel("")
        self._side.setObjectName("addon-group-wow")
        layout.addWidget(self._side)

        layout.addStretch()

        self._summary = QLabel("")
        self._summary.setObjectName("addon-group-summary")
        layout.addWidget(self._summary)

    def set_expanded(self, expanded: bool) -> None:
        self._arrow.setText("▼" if expanded else "▶")

    def set_summary(self, text: str) -> None:
        self._summary.setText(text)

    def set_title(self, text: str) -> None:
        self._name.setText(text)

    def set_side_label(self, text: str) -> None:
        """Secondary label next to the group name. Empty string hides it."""
        self._side.setText(text)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class CollapsibleGroup(QWidget):
    """Header plus a body that animates between zero height and its content size."""

    def __init__(self, label: str, body: QWidget, parent=None):
        super().__init__(parent)
        self._expanded = False
        self._initialized = False
        self._natural_height = 0
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        self._header = GroupHeader(label)
        self._header.clicked.connect(self.toggle)
        vbox.addWidget(self._header)

        self._body = QWidget()
        self._body.setMaximumHeight(0)
        body_vbox = QVBoxLayout(self._body)
        body_vbox.setContentsMargins(0, 0, 0, 0)
        body_vbox.setSpacing(0)
        body_vbox.addWidget(body)
        vbox.addWidget(self._body)

        self._anim = QPropertyAnimation(self._body, b"maximumHeight")
        self._anim.setDuration(ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._anim.finished.connect(self._on_anim_finished)

    # ── Header passthrough ────────────────────────────────────────────

    def set_summary(self, text: str) -> None:
        self._header.set_summary(text)

    def set_title(self, text: str) -> None:
        self._header.set_title(text)

    def set_side_label(self, text: str) -> None:
        self._header.set_side_label(text)

    # ── Toggle ────────────────────────────────────────────────────────

    def toggle(self) -> None:
        if self._expanded:
            self._anim.stop()
            self._anim.setStartValue(self._body.height())
            self._anim.setEndValue(0)
            self._expanded = False
        else:
            self._anim.stop()
            self._anim.setStartValue(self._body.maximumHeight())
            self._anim.setEndValue(self._natural_height)
            self._expanded = True
        self._header.set_expanded(self._expanded)
        self._anim.start()

    def _on_anim_finished(self) -> None:
        if self._expanded:
            # Remove the constraint so the body can grow if rows are added later
            self._body.setMaximumHeight(_UNCONSTRAINED)

    # ── Content ───────────────────────────────────────────────────────

    def set_content_height(self, height: int, expand_if_content: bool = True) -> None:
        """Record the body's natural height after the caller refilled it.

        On the first call the group expands when it has content, matching the
        Addon Versions behaviour; afterwards the user's own expand/collapse
        state is left alone.
        """
        self._natural_height = height

        if not self._initialized:
            self._initialized = True
            if expand_if_content and height > 0:
                self._expanded = True
                self._header.set_expanded(True)
                self._body.setMaximumHeight(_UNCONSTRAINED)
        elif self._expanded:
            self._body.setMaximumHeight(_UNCONSTRAINED)
