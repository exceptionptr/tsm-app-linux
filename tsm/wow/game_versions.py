"""The one table of WoW game versions the app knows about.

Every per-game-version lookup (folder, UI key, label, account suffix, the
realm-api region mapping) derives from GAME_VERSIONS below, so adding a game
version is a one-line change. Before this existed the same four-entry dict was
copied into eight modules, which is how a new client gets half supported.

Kept free of Qt imports so it can be used from tests and worker code.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GameVersion:
    folder: str  # directory under the WoW base, e.g. "_retail_"
    key: str  # stable id stored in config and the realm snapshot
    label: str  # fallback display name; the game-versions API can override it
    account_suffix: str  # suffix the Windows app appends to account names


# Display order: the same order the official app sorts its game versions in.
GAME_VERSIONS: tuple[GameVersion, ...] = (
    GameVersion("_retail_", "retail", "Retail", ""),
    GameVersion("_classic_", "bcc", "Progression", "-Progression"),
    GameVersion("_anniversary_", "anniversary", "Anniversary", "-Anniversary"),
    GameVersion("_classic_era_", "classic", "Classic Era", "-Classic"),
    GameVersion("_forever_", "forever", "Forever", "-Forever"),
)

FOLDERS: tuple[str, ...] = tuple(gv.folder for gv in GAME_VERSIONS)
BY_FOLDER: dict[str, GameVersion] = {gv.folder: gv for gv in GAME_VERSIONS}
BY_KEY: dict[str, GameVersion] = {gv.key: gv for gv in GAME_VERSIONS}
SUFFIX_BY_FOLDER: dict[str, str] = {gv.folder: gv.account_suffix for gv in GAME_VERSIONS}

# realm-api region.gameVersion -> (game version folder, AppData region key prefix).
#
# From the official 1.0.9 client. Several server-side game modes share one client
# folder (Hardcore and Season of Discovery both run in _classic_era_), and the
# prefix keeps their region data apart inside that folder's AppData.lua.
# "Season of Mastery" maps to _classic_era_ in the client but has no prefix, so the
# client skips its data; it is left out here for the same result.
REGION_GAME_VERSIONS: dict[str, tuple[str, str]] = {
    "Retail": ("_retail_", ""),
    "Wrath": ("_classic_", "BCC-"),
    "Classic Era": ("_classic_era_", "Classic-"),
    "Classic Era - Hardcore": ("_classic_era_", "HC-"),
    "Season of Discovery": ("_classic_era_", "SoD-"),
    "Classic Era - Fresh": ("_anniversary_", "Fresh-"),
    "Forever": ("_forever_", "Forever-"),
}


def folder_for_region(game_version: str) -> str | None:
    """Game version folder for a realm-api region gameVersion, or None if unsupported."""
    entry = REGION_GAME_VERSIONS.get(game_version)
    return entry[0] if entry else None


def region_key(game_version: str, region_prefix: str) -> str | None:
    """AppData.lua key for a region, e.g. ("Wrath", "eu") -> "BCC-EU"."""
    entry = REGION_GAME_VERSIONS.get(game_version)
    if entry is None:
        return None
    return entry[1] + region_prefix.upper()


def realm_key(localized_name: str, auction_house_type: str) -> str:
    """AppData.lua key for a realm auction house.

    A shared auction house is keyed by the bare realm name; a faction one gets the
    faction appended, e.g. ("Everlook", "HORDE") -> "Everlook-Horde".
    """
    if auction_house_type.upper() == "ALL":
        return localized_name
    t = auction_house_type
    return f"{localized_name}-{t[:1].upper()}{t[1:].lower()}"


def label_for_key(key: str) -> str:
    gv = BY_KEY.get(key)
    return gv.label if gv else key
