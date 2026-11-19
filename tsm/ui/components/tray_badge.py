"""Tray icon badges: a status dot, or a lightning bolt when signed out."""

from __future__ import annotations

import math
from collections.abc import Iterable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)

from tsm.ui._freshness import FRESHNESS_COLORS, Freshness
from tsm.ui._tray_status import TrayStatus

_OUTLINE = "#ffffff"
_BOLT_COLOR = "#ffc107"
# Share of the icon edge the badge covers. The dot sits in the bottom right corner;
# the bolt is centred over the logo and drawn large so it reads at 22 px.
_DOT_SHARE = 0.44
# The dot keeps this distance to the bottom and right icon edge (share of the edge).
_DOT_MARGIN = 0.11
# Free space between the bolt outline and the circle of the logo (share of the edge).
_BOLT_MARGIN = 0.05
_BOLT_OUTLINE = 1.0
# Sizes rendered natively, so small tray sizes do not depend on desktop downscaling.
_SIZES = (16, 22, 24, 32, 48)
# Lightning bolt corners inside the badge square (0..1), a bold shape.
_BOLT = ((0.72, 0.0), (0.04, 0.56), (0.40, 0.56), (0.24, 1.0), (0.96, 0.38), (0.58, 0.38))

# Farthest bolt corner from the centre of the badge square, in badge sizes.
_BOLT_REACH = max(math.hypot(px - 0.5, py - 0.5) for px, py in _BOLT)

_DOT_FRESHNESS = {
    TrayStatus.SYNCED: Freshness.GREEN,
    TrayStatus.OUT_OF_DATE: Freshness.YELLOW,
    TrayStatus.OUTDATED: Freshness.RED,
}


def badge_image(base: QImage, status: TrayStatus) -> QImage:
    """Return ``base`` with the badge for ``status`` in the bottom right corner."""
    return _compose(base, min(base.width(), base.height()), status)


def _compose(source: QImage, edge: int, status: TrayStatus) -> QImage:
    """Paint ``source`` and the badge for ``status`` on a transparent ``edge`` square."""
    image = QImage(edge, edge, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    scaled = source.scaled(
        edge,
        edge,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    if status is TrayStatus.LOGGED_OUT:
        # Largest bolt whose outline stays inside the circle with a margin.
        room = edge / 2 - edge * _BOLT_MARGIN - _BOLT_OUTLINE / 2
        size = max(1.0, room) / _BOLT_REACH
        x = y = (edge - size) / 2
    else:
        size = edge * _DOT_SHARE
        x = y = edge - size - edge * _DOT_MARGIN
    border = QPen(QColor(_OUTLINE))
    border.setWidthF(max(1.0, edge / 22))
    border.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.drawImage(0, 0, scaled)
        circle = QPainterPath()
        circle.addEllipse(QRectF(0, 0, edge, edge))
        painter.setClipPath(circle)
        painter.setPen(border)
        if status is TrayStatus.LOGGED_OUT:
            border.setWidthF(_BOLT_OUTLINE)
            painter.setPen(border)
            painter.setBrush(QBrush(QColor(_BOLT_COLOR)))
            corners = [QPointF(x + px * size, y + py * size) for px, py in _BOLT]
            painter.drawPolygon(QPolygonF(corners))
        else:
            color = FRESHNESS_COLORS[_DOT_FRESHNESS[status]]
            painter.setBrush(QBrush(QColor(color)))
            inset = border.widthF() / 2
            painter.drawEllipse(QRectF(x + inset, y + inset, size - 2 * inset, size - 2 * inset))
    finally:
        painter.end()
    return image


def tray_images(status: TrayStatus, bases: Iterable[QImage]) -> list[QImage]:
    """One badged image per tray size, each painted natively from the largest base."""
    images = [b for b in bases if not b.isNull()]
    if not images:
        return []
    largest = max(images, key=lambda b: min(b.width(), b.height()))
    return [_compose(largest, edge, status) for edge in _SIZES]


def tray_icon(status: TrayStatus, bases: Iterable[QImage]) -> QIcon:
    """Build an icon with the badge painted natively at each tray size."""
    icon = QIcon()
    for image in tray_images(status, bases):
        icon.addPixmap(QPixmap.fromImage(image))
    return icon
