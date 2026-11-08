"""Shared WoW installation utilities."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from tsm.wow.game_versions import FOLDERS, SUFFIX_BY_FOLDER

# Kept as a name for the modules that import it; the list itself lives in
# tsm/wow/game_versions.py.
_GAME_VERSIONS = FOLDERS

# Addon folder suffix per game version, matching the old Windows TSM app. Only
# used to recognise legacy per-client package names; TSM 4.15 ships one
# multi-toc package named TradeSkillMaster_AppHelper for every client.
_APPHELPER_SUFFIX: dict[str, str] = SUFFIX_BY_FOLDER


def normalize_wow_base(path: Path) -> Path:
    """Return the WoW base directory.

    If path ends in a game-version subdir (e.g. _retail_), return its parent.
    Otherwise return path unchanged.
    """
    return path.parent if path.name in _GAME_VERSIONS else path


def addon_dir(base: Path, gv: str) -> Path:
    """Return the AddOns directory for a given base and game version."""
    return base / gv / "Interface" / "AddOns"


def apphelper_addon_name(gv: str) -> str:  # noqa: ARG001
    """The AppHelper folder name. TSM 4.15 uses one name for every game version."""
    return "TradeSkillMaster_AppHelper"


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
    """Return which game versions are installed under this base.

    A game version is considered installed only if its directory exists AND
    contains a WoW executable - a directory left behind after uninstalling
    via Battle.net will not match.
    """
    return [gv for gv in _GAME_VERSIONS if is_valid_wow_version_dir(base / gv)]


def is_valid_wow_version_dir(path: Path) -> bool:
    """Return True if path is a valid WoW game-version directory.

    Accepts either a WoW executable (Wow.exe, WowClassic.exe, or whatever a new
    client calls its own, matched case-insensitively) or WTF/Config.wtf, which
    is what the official 1.0.9 client checks. Interface/AddOns is not required,
    so a fresh install with no addons yet is still detected.
    """
    if not path.is_dir():
        return False
    try:
        for f in path.iterdir():
            n = f.name.lower()
            if n.endswith(".exe") and n.startswith("wow") and "launcher" not in n:
                return True
    except OSError:
        return False
    return (path / "WTF" / "Config.wtf").is_file()


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
