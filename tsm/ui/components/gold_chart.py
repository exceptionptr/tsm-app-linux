"""Player gold over time: an area chart with a hover readout.

Drawn with QPainter rather than QtCharts so no extra Qt module has to be added
to debian/control, the rpm spec and the PKGBUILD, and so the dark styling and
the tooltip match the rest of the app exactly.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget

from tsm.ui.components._gold_format import RANGES, format_gold_full, format_gold_short

_LINE = "#4caf50"
_FILL_TOP = QColor(76, 175, 80, 90)
_FILL_BOTTOM = QColor(76, 175, 80, 10)
_GRID = "#2e2e2e"
_AXIS_TEXT = "#8a8a8a"
_CROSSHAIR = "#d0d0d0"
_TOOLTIP_BG = "#0d0d12"
_GOLD = "#ffd100"

_PAD_LEFT = 58
_PAD_RIGHT = 12
_PAD_TOP = 12
_PAD_BOTTOM = 26
_MIN_HEIGHT = 140


class RangeSelector(QWidget):
    """The 1D / 1W / ... / All button row above the plot."""

    range_changed: Signal = Signal(object)  # days, or None for all

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._buttons: dict[str, QPushButton] = {}
        for label, days in RANGES:
            button = QPushButton(label)
            button.setObjectName("range-button")
            button.setCheckable(True)
            button.setFixedSize(38, 24)
            button.clicked.connect(lambda _, d=days, ln=label: self._select(ln, d))
            self._buttons[label] = button
            layout.addWidget(button)
        self._select("All", None, emit=False)

    def _select(self, label: str, days: int | None, emit: bool = True) -> None:
        for name, button in self._buttons.items():
            button.setChecked(name == label)
        if emit:
            self.range_changed.emit(days)


class GoldChart(QWidget):
    """Area chart of total gold, with a crosshair and value readout on hover."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._points: list[tuple[int, int]] = []  # (timestamp, copper)
        self._hover: int | None = None  # index into _points
        self.setMouseTracking(True)
        self.setMinimumHeight(_MIN_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_points(self, points: list[tuple[int, int]]) -> None:
        self._points = sorted(points)
        self._hover = None
        self.update()

    def date_span(self) -> tuple[int, int] | None:
        """First and last timestamp, for the subtitle above the plot."""
        if not self._points:
            return None
        return self._points[0][0], self._points[-1][0]

    # ── Geometry ──────────────────────────────────────────────────────

    def _plot_rect(self) -> QRect:
        return QRect(
            _PAD_LEFT,
            _PAD_TOP,
            max(1, self.width() - _PAD_LEFT - _PAD_RIGHT),
            max(1, self.height() - _PAD_TOP - _PAD_BOTTOM),
        )

    def _bounds(self) -> tuple[int, int, int, int]:
        times = [t for t, _ in self._points]
        values = [v for _, v in self._points]
        t_min, t_max = min(times), max(times)
        v_max = max(values)
        # Always anchor at zero: gold is an absolute amount, and a floating
        # baseline makes a flat balance look like a cliff.
        return t_min, max(t_max, t_min + 1), 0, max(v_max, 1)

    def _x_for(self, ts: int, rect: QRect, t_min: int, t_max: int) -> float:
        return rect.left() + (ts - t_min) / (t_max - t_min) * rect.width()

    def _y_for(self, copper: int, rect: QRect, v_min: int, v_max: int) -> float:
        return rect.bottom() - (copper - v_min) / (v_max - v_min) * rect.height()

    # ── Painting ──────────────────────────────────────────────────────

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self._plot_rect()

        if len(self._points) < 2:
            painter.setPen(QColor(_AXIS_TEXT))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "No gold history")
            painter.end()
            return

        t_min, t_max, v_min, v_max = self._bounds()
        self._draw_grid(painter, rect, v_min, v_max)
        self._draw_area(painter, rect, t_min, t_max, v_min, v_max)
        self._draw_time_axis(painter, rect, t_min, t_max)
        if self._hover is not None:
            self._draw_hover(painter, rect, self._hover, t_min, t_max, v_min, v_max)
        painter.end()

    def _draw_grid(self, painter: QPainter, rect: QRect, v_min: int, v_max: int) -> None:
        painter.setFont(self.font())
        for i in range(5):
            value = v_min + (v_max - v_min) * i / 4
            y = self._y_for(int(value), rect, v_min, v_max)
            painter.setPen(QPen(QColor(_GRID), 1))
            painter.drawLine(rect.left(), int(y), rect.right(), int(y))
            painter.setPen(QColor(_AXIS_TEXT))
            painter.drawText(
                QRect(0, int(y) - 8, _PAD_LEFT - 6, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                format_gold_short(int(value)),
            )

    def _draw_area(
        self, painter: QPainter, rect: QRect, t_min: int, t_max: int, v_min: int, v_max: int
    ) -> None:
        from PySide6.QtGui import QPainterPath

        path = QPainterPath()
        first_x = self._x_for(self._points[0][0], rect, t_min, t_max)
        path.moveTo(first_x, self._y_for(self._points[0][1], rect, v_min, v_max))
        for ts, copper in self._points[1:]:
            path.lineTo(
                self._x_for(ts, rect, t_min, t_max),
                self._y_for(copper, rect, v_min, v_max),
            )

        fill = QPainterPath(path)
        last_x = self._x_for(self._points[-1][0], rect, t_min, t_max)
        fill.lineTo(last_x, rect.bottom())
        fill.lineTo(first_x, rect.bottom())
        fill.closeSubpath()

        gradient = QLinearGradient(0, rect.top(), 0, rect.bottom())
        gradient.setColorAt(0.0, _FILL_TOP)
        gradient.setColorAt(1.0, _FILL_BOTTOM)
        painter.fillPath(fill, gradient)

        painter.setPen(QPen(QColor(_LINE), 1.5))
        painter.drawPath(path)

    def _draw_time_axis(self, painter: QPainter, rect: QRect, t_min: int, t_max: int) -> None:
        painter.setPen(QColor(_AXIS_TEXT))
        span_days = (t_max - t_min) / 86400
        fmt = "%H:%M" if span_days <= 2 else ("%d %b" if span_days <= 120 else "%b %y")
        for i in range(5):
            ts = int(t_min + (t_max - t_min) * i / 4)
            x = self._x_for(ts, rect, t_min, t_max)
            label = datetime.fromtimestamp(ts).strftime(fmt)
            width = QFontMetrics(self.font()).horizontalAdvance(label)
            painter.drawText(
                QRect(int(x) - width // 2, rect.bottom() + 6, width + 8, 16),
                Qt.AlignmentFlag.AlignLeft,
                label,
            )

    def _draw_hover(
        self,
        painter: QPainter,
        rect: QRect,
        index: int,
        t_min: int,
        t_max: int,
        v_min: int,
        v_max: int,
    ) -> None:
        ts, copper = self._points[index]
        x = self._x_for(ts, rect, t_min, t_max)
        y = self._y_for(copper, rect, v_min, v_max)

        painter.setPen(QPen(QColor(_CROSSHAIR), 1, Qt.PenStyle.DashLine))
        painter.drawLine(int(x), rect.top(), int(x), rect.bottom())
        painter.setPen(QPen(QColor(_LINE), 2))
        painter.setBrush(QColor(_LINE))
        painter.drawEllipse(QPoint(int(x), int(y)), 3, 3)

        value = format_gold_full(copper)
        when = datetime.fromtimestamp(ts).strftime("%d %b %Y, %H:%M")
        metrics = QFontMetrics(self.font())
        width = max(metrics.horizontalAdvance(value), metrics.horizontalAdvance(when)) + 16
        height = 38

        # Flip to the other side of the cursor near the right edge.
        box_x = x + 10 if x + 10 + width < rect.right() else x - 10 - width
        box_y = min(max(rect.top(), y - height - 8), rect.bottom() - height)
        box = QRect(int(box_x), int(box_y), width, height)

        painter.setPen(QColor(_GRID))
        painter.setBrush(QColor(_TOOLTIP_BG))
        painter.drawRect(box)
        painter.setPen(QColor(_GOLD))
        painter.drawText(box.adjusted(8, 4, -8, 0), Qt.AlignmentFlag.AlignTop, value)
        painter.setPen(QColor(_AXIS_TEXT))
        painter.drawText(box.adjusted(8, 0, -8, -4), Qt.AlignmentFlag.AlignBottom, when)

    # ── Hover ─────────────────────────────────────────────────────────

    def mouseMoveEvent(self, event: object) -> None:
        rect = self._plot_rect()
        if len(self._points) < 2:
            return
        x = event.position().x()  # type: ignore[attr-defined]
        t_min, t_max, _, _ = self._bounds()
        if not rect.left() <= x <= rect.right():
            self._clear_hover()
            return
        target = t_min + (x - rect.left()) / rect.width() * (t_max - t_min)
        nearest = min(range(len(self._points)), key=lambda i: abs(self._points[i][0] - target))
        if nearest != self._hover:
            self._hover = nearest
            self.update()

    def leaveEvent(self, _event: object) -> None:
        self._clear_hover()

    def _clear_hover(self) -> None:
        if self._hover is not None:
            self._hover = None
            self.update()
