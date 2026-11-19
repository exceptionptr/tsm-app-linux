"""Traffic light thresholds shared by the realm list and the tray."""

from __future__ import annotations

import pytest

from tsm.ui._freshness import FRESHNESS_COLORS, Freshness, realm_freshness

NOW = 1_800_000_000.0
H = 3600


def _f(status: str, age_h: float, is_region: bool) -> Freshness:
    return realm_freshness(status, int(NOW - age_h * H), is_region, now=NOW)


def test_updating_is_yellow():
    assert realm_freshness("Updating...", int(NOW), False, now=NOW) is Freshness.YELLOW


def test_outdated_is_red():
    assert realm_freshness("Outdated", int(NOW), False, now=NOW) is Freshness.RED


def test_missing_timestamp_is_yellow():
    assert realm_freshness("Up to date", 0, False, now=NOW) is Freshness.YELLOW


@pytest.mark.parametrize(
    ("is_region", "green_h", "yellow_h"), [(False, 2, 6), (True, 26, 50)]
)
def test_boundaries(is_region: bool, green_h: int, yellow_h: int):
    assert _f("Up to date", green_h - 0.01, is_region) is Freshness.GREEN
    assert _f("Up to date", green_h, is_region) is Freshness.YELLOW
    assert _f("Up to date", yellow_h - 0.01, is_region) is Freshness.YELLOW
    assert _f("Up to date", yellow_h, is_region) is Freshness.RED


def test_default_now_uses_clock():
    import time

    assert realm_freshness("Up to date", int(time.time()), False) is Freshness.GREEN


def test_colors_unchanged():
    assert FRESHNESS_COLORS == {
        Freshness.GREEN: "#4caf50",
        Freshness.YELLOW: "#ffc107",
        Freshness.RED: "#f44336",
    }
