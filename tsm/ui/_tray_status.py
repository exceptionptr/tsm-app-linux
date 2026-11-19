"""The state the tray icon shows: signed out, in sync, behind or outdated.

Kept free of PySide6 so the rules can be tested without a display stack.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum

from tsm.ui._freshness import Freshness


class TrayStatus(Enum):
    LOGGED_OUT = "logged_out"
    SYNCED = "synced"
    OUT_OF_DATE = "out_of_date"
    OUTDATED = "outdated"


def tray_status(
    *, authenticated: bool, connected: bool, freshness: Iterable[Freshness]
) -> TrayStatus:
    """Summarise the session: the worst realm or region dot wins.

    Signed out beats everything. A red dot means outdated, even without a
    connection. Disconnected, no realm data yet, or a yellow dot means the data
    is not current. Only a connected session with all dots green is synced.
    """
    if not authenticated:
        return TrayStatus.LOGGED_OUT
    dots = list(freshness)
    worst = max(dots) if dots else None
    if worst is Freshness.RED:
        return TrayStatus.OUTDATED
    if not connected or worst is None or worst is Freshness.YELLOW:
        return TrayStatus.OUT_OF_DATE
    return TrayStatus.SYNCED


_TOOLTIPS = {
    TrayStatus.LOGGED_OUT: "TradeSkillMaster: not logged in",
    TrayStatus.SYNCED: "TradeSkillMaster: up to date",
    TrayStatus.OUT_OF_DATE: "TradeSkillMaster: logged in, data not up to date",
    TrayStatus.OUTDATED: "TradeSkillMaster: data outdated",
}


def tray_tooltip(status: TrayStatus) -> str:
    return _TOOLTIPS[status]
