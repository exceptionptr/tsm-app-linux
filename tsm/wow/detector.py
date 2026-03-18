"""Find WoW installations on Linux (native, Wine, Lutris, Steam)."""

from __future__ import annotations

import logging
from pathlib import Path

from tsm.core.models.config import WoWInstall

logger = logging.getLogger(__name__)

# Static fallback paths to check even without Lutris config
COMMON_BASE_PATHS = [
    Path.home() / ".wine/drive_c/Program Files (x86)/World of Warcraft",
    Path.home() / ".wine/drive_c/Program Files/World of Warcraft",
    Path.home() / "Games/world-of-warcraft",
    Path.home() / "Games/World of Warcraft",
    Path("/mnt/games/World of Warcraft"),
    Path("/opt/games/World of Warcraft"),
    Path.home() / ".local/share/Steam/steamapps/common/World of Warcraft",
    Path.home()
    / "snap/wine-platform-5-stable/common/.wine/drive_c/Program Files (x86)/World of Warcraft",
]

WOW_VERSIONS = ["_retail_", "_classic_", "_classic_era_", "_classic_ptr_", "_retail_ptr_"]

LUTRIS_GAMES_DIR = Path.home() / ".local/share/lutris/games"


def _lutris_base_paths() -> list[Path]:
    """Extract WoW base paths from Lutris game config files."""
    paths: list[Path] = []
    if not LUTRIS_GAMES_DIR.is_dir():
        return paths
    try:
        import yaml  # noqa: F401 - checked at runtime
    except ImportError:
        logger.debug("PyYAML not installed; skipping Lutris config parsing")
        return paths

    for yml in LUTRIS_GAMES_DIR.glob("*.yml"):
        try:
            with open(yml) as f:
                cfg = yaml.safe_load(f)
            # Lutris game config stores the wine prefix under game.prefix
            game_section = cfg.get("game", {})
            prefix = game_section.get("prefix")
            if not prefix:
                continue
            prefix_path = Path(prefix)
            # Look for WoW under both Program Files variants inside the prefix
            for pf in ["Program Files (x86)", "Program Files"]:
                candidate = prefix_path / "drive_c" / pf / "World of Warcraft"
                if candidate.is_dir():
                    paths.append(candidate)
                    logger.debug("Lutris config %s → WoW base: %s", yml.name, candidate)
        except Exception:
            logger.debug("Failed to parse Lutris config: %s", yml)

    return paths


def find_wow_installs(extra_paths: list[Path] | None = None) -> list[WoWInstall]:
    """Scan common Linux paths and Lutris configs for WoW installations."""
    base_paths = list(COMMON_BASE_PATHS)
    base_paths.extend(_lutris_base_paths())
    if extra_paths:
        base_paths.extend(extra_paths)

    found: list[WoWInstall] = []
    seen: set[str] = set()

    for base in base_paths:
        if not base.exists():
            continue
        for version in WOW_VERSIONS:
            p = base / version
            addons_dir = p / "Interface" / "AddOns"
            if addons_dir.is_dir():
                key = str(p.resolve())
                if key not in seen:
                    seen.add(key)
                    found.append(WoWInstall(path=str(p.resolve()), version=version))
                    logger.info("Found WoW install: %s (%s)", p, version)

    if not found:
        logger.info("No WoW installs found in common paths")
    return found


def find_wow_accounts(wow_install: WoWInstall) -> list[str]:
    """Enumerate WoW accounts under WTF/Account/."""
    wtf_accounts = Path(wow_install.path) / "WTF" / "Account"
    if not wtf_accounts.is_dir():
        return []
    return [
        d.name for d in wtf_accounts.iterdir() if d.is_dir() and d.name not in ("SavedVariables",)
    ]


def get_apphelper_data_path(wow_install: WoWInstall) -> Path:
    """Return the path to AppData.lua inside TradeSkillMaster_AppHelper."""
    return (
        Path(wow_install.path)
        / "Interface"
        / "AddOns"
        / "TradeSkillMaster_AppHelper"
        / "AppData.lua"
    )
