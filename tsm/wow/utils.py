"""Shared WoW installation utilities."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

_GAME_VERSIONS = ("_retail_", "_classic_era_", "_classic_", "_anniversary_")

# Addon folder suffix per game version, matching the Windows TSM app convention.
# The AppHelper addon is named differently in each game client:
#   _retail_:      TradeSkillMaster_AppHelper
#   _classic_era_: TradeSkillMaster_AppHelper-Classic
#   _classic_:     TradeSkillMaster_AppHelper-Progression
#   _anniversary_: TradeSkillMaster_AppHelper-Anniversary
_APPHELPER_SUFFIX: dict[str, str] = {
    "_retail_": "",
    "_classic_era_": "-Classic",
    "_classic_": "-Progression",
    "_anniversary_": "-Anniversary",
}


def normalize_wow_base(path: Path) -> Path:
    """Return the WoW base directory.

    If path ends in a game-version subdir (e.g. _retail_), return its parent.
    Otherwise return path unchanged.
    """
    return path.parent if path.name in _GAME_VERSIONS else path


def addon_dir(base: Path, gv: str) -> Path:
    """Return the AddOns directory for a given base and game version."""
    return base / gv / "Interface" / "AddOns"


def apphelper_addon_name(gv: str) -> str:
    """Return the full addon folder name for a given game-version directory.

    e.g. '_retail_' -> 'TradeSkillMaster_AppHelper'
         '_classic_era_' -> 'TradeSkillMaster_AppHelper-Classic'
    """
    return f"TradeSkillMaster_AppHelper{_APPHELPER_SUFFIX.get(gv, '')}"


def apphelper_dir(base: Path, gv: str) -> Path:
    """Return the TradeSkillMaster_AppHelper addon directory for a given game version.

    The addon folder is always named TradeSkillMaster_AppHelper regardless of game version.
    The game version suffix only determines which game version directory to use, not
    the addon folder name itself (confirmed from the Windows app reference implementation).
    """
    return base / gv / "Interface" / "AddOns" / "TradeSkillMaster_AppHelper"


def appdata_lua_path(base: Path, gv: str) -> Path:
    """Return the AppData.lua path for a given base and game version."""
    return apphelper_dir(base, gv) / "AppData.lua"


def wtf_accounts_dir(base: Path, gv: str) -> Path:
    """Return the WTF/Account directory for a given base and game version."""
    return base / gv / "WTF" / "Account"


def installed_versions(base: Path) -> list[str]:
    """Return which game versions exist as directories under this base."""
    return [gv for gv in _GAME_VERSIONS if (base / gv).is_dir()]


def is_valid_wow_version_dir(path: Path) -> bool:
    """Return True if path is a valid WoW game-version directory.

    Checks for a WoW executable (case-insensitive) rather than requiring
    Interface/AddOns to exist, so fresh installs with no addons yet
    are still detected correctly.
    """
    if not path.is_dir():
        return False
    lower = {f.name.lower() for f in path.iterdir() if f.suffix.lower() == ".exe"}
    return "wow.exe" in lower or "wowclassic.exe" in lower


def iter_wow_gv_roots(installs) -> Generator[tuple[Path, str], None, None]:
    """Yield (wow_base, gv_dir) for every (install x game_version) combination.

    Only yields game versions whose directory actually exists under the base.
    Assumes install.path is the WoW base directory. Also handles legacy paths
    ending in a game-version subdir by normalizing them first.
    """
    for install in installs:
        base = normalize_wow_base(Path(install.path))
        for gv in installed_versions(base):
            yield base, gv
