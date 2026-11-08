"""Order realm summaries into per-game-version groups for the Realm Data tab.

Kept free of Qt imports so the ordering can be unit tested without a
QApplication.

Within a group each region comes first, carrying its own AuctionDB status, and
its realms follow indented. The region blob is the shared source for every realm
in that region, so it belongs above them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tsm.wow.game_versions import GAME_VERSIONS

# Same order as the Addon Versions tab: the order of tsm/wow/game_versions.py.
GV_ORDER: tuple[str, ...] = tuple(gv.key for gv in GAME_VERSIONS)

# Fallback group labels. The live labels come from the game-versions API and are
# passed to group_summaries() by the view.
GV_LABELS: dict[str, str] = {gv.key: gv.label for gv in GAME_VERSIONS}


@dataclass(frozen=True)
class RealmRow:
    """One rendered line: either a region header or a realm beneath it."""

    summary: Any  # RealmSummary, duck typed to keep this module Qt free
    is_region: bool
    label: str  # region row: the raw region ("BCC-EU"); realm row: the bare realm name
    indent: int  # 0 for a region, 1 for a realm


def _placeholder_region(region: str, template: Any) -> Any:
    """Stand-in region row for realms whose region is absent from the status data.

    Without this the realms would render with no header, or be dropped. Copies
    the realm's own class so the view can treat every row the same way.
    """
    return type(template)(
        display_name=region,
        is_region=True,
        auctiondb_status="",
        last_updated=0,
        game_version=template.game_version,
        region=region,
        name=region,
    )


def group_summaries(
    summaries: list[Any], labels: dict[str, str] | None = None
) -> list[tuple[str, str, list[RealmRow]]]:
    """Return [(game_version, label, rows)] in GV_ORDER, dropping empty groups."""
    labels = {**GV_LABELS, **(labels or {})}
    by_gv: dict[str, list[Any]] = {}
    for summary in summaries:
        by_gv.setdefault(summary.game_version, []).append(summary)

    # Preserve GV_ORDER first, then any unexpected game version the API adds
    # later, so a new one shows up rather than vanishing.
    ordered_gvs = [gv for gv in GV_ORDER if gv in by_gv]
    ordered_gvs += sorted(gv for gv in by_gv if gv not in GV_ORDER)

    groups: list[tuple[str, str, list[RealmRow]]] = []
    for game_version in ordered_gvs:
        entries = by_gv[game_version]
        regions = {s.region: s for s in entries if s.is_region}
        realms_by_region: dict[str, list[Any]] = {}
        for s in entries:
            if not s.is_region:
                realms_by_region.setdefault(s.region, []).append(s)

        rows: list[RealmRow] = []
        for region in sorted(set(regions) | set(realms_by_region)):
            region_summary = regions.get(region)
            if region_summary is None:
                region_summary = _placeholder_region(region, realms_by_region[region][0])
            rows.append(
                RealmRow(
                    summary=region_summary,
                    is_region=True,
                    label=region or region_summary.display_name,
                    indent=0,
                )
            )
            for realm in sorted(realms_by_region.get(region, []), key=lambda s: s.name):
                rows.append(
                    RealmRow(
                        summary=realm,
                        is_region=False,
                        label=realm.name or realm.display_name,
                        indent=1,
                    )
                )

        if rows:
            groups.append((game_version, labels.get(game_version, game_version), rows))

    return groups


def realm_count(rows: list[RealmRow]) -> int:
    """Number of actual realms in a group, ignoring the region headers."""
    return sum(1 for r in rows if not r.is_region)
