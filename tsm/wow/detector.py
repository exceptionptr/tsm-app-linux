"""Find WoW installations on Linux (native, Wine, Lutris, Steam)."""

from __future__ import annotations

import logging
from pathlib import Path

from tsm.wow.utils import is_valid_wow_version_dir

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

# All known game versions including PTR variants used only for detection
WOW_VERSIONS = [
    "_retail_",
    "_classic_",
    "_classic_era_",
    "_anniversary_",
    "_classic_ptr_",
    "_retail_ptr_",
]

LUTRIS_GAMES_DIR = Path.home() / ".local/share/lutris/games"

FAUGUS_PREFIX_DIR = Path.home() / "Faugus"
FAUGUS_GAMES_JSON = Path.home() / ".config" / "faugus-launcher" / "games.json"


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
                    logger.debug("Lutris config %s -> WoW base: %s", yml.name, candidate)
        except Exception:
            logger.debug("Failed to parse Lutris config: %s", yml)

    return paths


def _faugus_base_paths() -> list[Path]:
    """Extract WoW base paths from Faugus Launcher prefixes."""
    paths: list[Path] = []
    seen: set[str] = set()

    # Dynamic: read games.json for per-game custom prefix paths
    if FAUGUS_GAMES_JSON.is_file():
        try:
            import json

            games = json.loads(FAUGUS_GAMES_JSON.read_text(encoding="utf-8"))
            for game in games if isinstance(games, list) else []:
                prefix = game.get("prefix") if isinstance(game, dict) else None
                if not prefix:
                    continue
                for pf in ["Program Files (x86)", "Program Files"]:
                    candidate = Path(prefix) / "drive_c" / pf / "World of Warcraft"
                    key = str(candidate)
                    if key not in seen:
                        seen.add(key)
                        paths.append(candidate)
                        logger.debug("Faugus games.json prefix -> WoW base: %s", candidate)
        except Exception:
            logger.debug("Failed to parse Faugus games.json")

    # Static fallback: scan all subdirs of ~/Faugus/
    if FAUGUS_PREFIX_DIR.is_dir():
        for prefix_dir in FAUGUS_PREFIX_DIR.iterdir():
            if not prefix_dir.is_dir():
                continue
            for pf in ["Program Files (x86)", "Program Files"]:
                candidate = prefix_dir / "drive_c" / pf / "World of Warcraft"
                key = str(candidate)
                if key not in seen:
                    seen.add(key)
                    paths.append(candidate)
                    logger.debug("Faugus prefix %s -> WoW base: %s", prefix_dir.name, candidate)

    return paths


def find_wow_base(extra_paths: list[Path] | None = None) -> str | None:
    """Scan common Linux paths and launcher configs for a WoW installation.

    Returns the WoW base directory path as a string, or None if not found.
    The first matching installation wins; auto-detection is opportunistic.
    """
    base_paths = list(COMMON_BASE_PATHS)
    base_paths.extend(_lutris_base_paths())
    base_paths.extend(_faugus_base_paths())
    if extra_paths:
        base_paths.extend(extra_paths)

    for base in base_paths:
        if not base.exists():
            continue
        for version in WOW_VERSIONS:
            if is_valid_wow_version_dir(base / version):
                resolved = str(base.resolve())
                logger.info("Found WoW install: %s", resolved)
                return resolved

    logger.info("No WoW install found in common paths")
    return None
