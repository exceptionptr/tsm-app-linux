"""The tray badge paints a status dot or a bolt without touching the base image."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtGui", exc_type=ImportError)

from PySide6.QtGui import QColor, QImage  # noqa: E402

from tsm.ui._freshness import FRESHNESS_COLORS, Freshness  # noqa: E402
from tsm.ui._tray_status import TrayStatus  # noqa: E402
from tsm.ui.components.tray_badge import badge_image  # noqa: E402


def _base() -> QImage:
    img = QImage(32, 32, QImage.Format.Format_ARGB32)
    img.fill(0)
    return img


@pytest.mark.parametrize(
    ("status", "freshness"),
    [
        (TrayStatus.SYNCED, Freshness.GREEN),
        (TrayStatus.OUT_OF_DATE, Freshness.YELLOW),
        (TrayStatus.OUTDATED, Freshness.RED),
    ],
)
def test_dot_center_has_the_freshness_color(status, freshness):
    out = badge_image(_base(), status)
    # The dot spans about 14 px, inset from the bottom right corner of a 32 px icon.
    center = out.pixelColor(32 - 11, 32 - 11)
    assert center.name() == QColor(FRESHNESS_COLORS[freshness]).name()
    assert center.alpha() == 255


def test_logged_out_bolt_is_centred_with_thin_white_outline():
    out = badge_image(_base(), TrayStatus.LOGGED_OUT)
    assert out.pixelColor(16, 16).name() == "#ffc107"
    assert out.pixelColor(31, 31).alpha() == 0
    white = [
        (x, y)
        for x in range(32)
        for y in range(32)
        if out.pixelColor(x, y).alpha() > 100 and out.pixelColor(x, y).blue() > 120
    ]
    assert white


def test_logged_out_draws_yellow_bolt_pixels():
    out = badge_image(_base(), TrayStatus.LOGGED_OUT)
    found = False
    for x in range(32):
        for y in range(32):
            c = out.pixelColor(x, y)
            if c.alpha() > 200 and c.red() > 200 and c.green() > 150 and c.blue() < 100:
                found = True
    assert found


def test_base_image_stays_unchanged():
    base = _base()
    badge_image(base, TrayStatus.OUTDATED)
    assert all(base.pixelColor(x, y).alpha() == 0 for x in range(32) for y in range(32))


def test_tray_images_cover_native_sizes():
    from tsm.ui.components.tray_badge import tray_images

    sizes = {img.width() for img in tray_images(TrayStatus.SYNCED, [_base()])}
    assert sizes == {16, 22, 24, 32, 48}


def test_logo_keeps_full_size():
    base = QImage(32, 32, QImage.Format.Format_ARGB32)
    base.fill(QColor("#ff00ff"))
    out = badge_image(base, TrayStatus.SYNCED)
    assert out.pixelColor(2, 2).name() == "#ff00ff"
    assert out.pixelColor(30, 2).name() == "#ff00ff"


@pytest.mark.parametrize("status", list(TrayStatus))
@pytest.mark.parametrize("edge", [16, 22, 24, 32, 48])
def test_badge_stays_inside_the_circle(status, edge):
    from tsm.ui.components.tray_badge import _compose

    out = _compose(_base(), edge, status)
    centre = edge / 2
    for x in range(edge):
        for y in range(edge):
            if out.pixelColor(x, y).alpha() > 0:
                assert (x + 0.5 - centre) ** 2 + (y + 0.5 - centre) ** 2 <= centre**2
    for x, y in ((0, 0), (edge - 1, 0), (0, edge - 1), (edge - 1, edge - 1)):
        assert out.pixelColor(x, y).alpha() == 0
