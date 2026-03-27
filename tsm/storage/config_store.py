"""TOML config read/write."""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path

from tsm.core.models.config import AppConfig

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
        data = config.model_dump()
        # Convert WoWInstall objects to dicts for TOML serialization
        if "wow_installs" in data:
            data["wow_installs"] = [
                w if isinstance(w, dict) else w.model_dump() for w in data["wow_installs"]
            ]
        with open(self._path, "wb") as f:
            tomli_w.dump(data, f)
        logger.info("Config saved to %s", self._path)
