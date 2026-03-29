"""TOML config read/write."""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path

from tsm.core.models.config import AppConfig
from tsm.wow.utils import normalize_wow_base

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".config" / "tsm-app"
CONFIG_FILE = CONFIG_DIR / "config.toml"
DATA_DIR = Path.home() / ".local" / "share" / "tsm-app"


class ConfigStore:
    def __init__(self, config_path: Path = CONFIG_FILE):
        self._path = config_path

    def load(self) -> AppConfig:
        if not self._path.exists():
            logger.info("No config file found, using defaults")
            return AppConfig()
        try:
            with open(self._path, "rb") as f:
                data = tomllib.load(f)
            _migrate(data)
            return AppConfig(**data)
        except Exception:
            logger.exception("Failed to load config, using defaults")
            return AppConfig()

    def save(self, config: AppConfig) -> None:
        try:
            import tomli_w
        except ImportError:
            logger.warning("tomli-w not installed, cannot save config")
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "wb") as f:
            tomli_w.dump(config.model_dump(), f)
        logger.info("Config saved to %s", self._path)


def _migrate(data: dict) -> None:
    """Mutate raw TOML data in-place to apply any format migrations.

    v1.1.3: wow_installs list[{path, version?}] -> wow_path string.
    Takes the first valid entry from the old list and normalizes it to the
    WoW base directory. Subsequent entries are silently dropped (multi-install
    was an edge case not supported by the single-path UI).
    """
    if "wow_installs" not in data:
        return
    raw_list = data.pop("wow_installs")
    if "wow_path" in data:
        # wow_path already present (manually edited config); keep it
        return
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        raw_path = item.get("path", "")
        if raw_path:
            data["wow_path"] = str(normalize_wow_base(Path(raw_path)))
            logger.info("Migrated wow_installs -> wow_path: %s", data["wow_path"])
            return
