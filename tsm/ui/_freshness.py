"""How fresh a realm or region data set is: the traffic light of the realm list.

Kept free of PySide6 so the realm list and the tray icon share one set of
thresholds and both can be tested without a display stack.
"""

from __future__ import annotations

import time
from enum import IntEnum


class Freshness(IntEnum):
    """Ordered by severity, so max() yields the worst one."""

    GREEN = 0
    YELLOW = 1
    RED = 2


FRESHNESS_COLORS: dict[Freshness, str] = {
    Freshness.GREEN: "#4caf50",
    Freshness.YELLOW: "#ffc107",
    Freshness.RED: "#f44336",
}

# Realm data (AUCTIONDB_NON_COMMODITY_DATA) updates ~hourly
_REALM_GREEN = 2 * 3600  # < 2h  -> green
_REALM_YELLOW = 6 * 3600  # < 6h  -> yellow, else red

# Region data (AUCTIONDB_REGION_STAT) updates ~daily (MAX_DATA_AGE = 86400)
_REGION_GREEN = 26 * 3600  # < 26h -> green
_REGION_YELLOW = 50 * 3600  # < 50h -> yellow, else red


def realm_freshness(
    status: str, last_updated: int, is_region: bool, now: float | None = None
) -> Freshness:
    if status == "Updating...":
        return Freshness.YELLOW
    if status == "Outdated":
        return Freshness.RED
    # "Up to date"
    if not last_updated:
        return Freshness.YELLOW
    age = (time.time() if now is None else now) - last_updated
    green_t = _REGION_GREEN if is_region else _REALM_GREEN
    yellow_t = _REGION_YELLOW if is_region else _REALM_YELLOW
    if age < green_t:
        return Freshness.GREEN
    if age < yellow_t:
        return Freshness.YELLOW
    return Freshness.RED
