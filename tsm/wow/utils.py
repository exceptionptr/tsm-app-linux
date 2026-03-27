"""Shared WoW installation utilities."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

_GAME_VERSIONS = ("_retail_", "_classic_era_", "_classic_", "_anniversary_")

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
    """Yield (wow_root, gv_dir) for every (install × game_version) combination.

    Handles both detector-style paths (ending in a game version subdir like _retail_)
    and user-configured paths pointing directly at the WoW base directory.
    """
    for install in installs:
        wow_path = Path(install.path)
        wow_root = wow_path.parent if wow_path.name in _GAME_VERSIONS else wow_path
        for gv in _GAME_VERSIONS:
            yield wow_root, gv
