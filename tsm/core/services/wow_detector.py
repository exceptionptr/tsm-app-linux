"""WoWDetectorService: find WoW installs on Linux."""

from __future__ import annotations

import asyncio
import logging

from tsm.core.models.config import WoWInstall
from tsm.wow.detector import find_wow_base

logger = logging.getLogger(__name__)


class WoWDetectorService:
    def __init__(self, skip_scan: bool = False):
        self._installs: list[WoWInstall] = []
        self._skip_scan = skip_scan
        self._from_config: bool = False

    @property
    def installs(self) -> list[WoWInstall]:
        """Return cached list of detected WoW installs.

        Each WoWInstall.path is the WoW base directory (e.g.
        /home/user/Games/world-of-warcraft). Game-version paths are derived
        on demand using tsm.wow.utils helpers (apphelper_dir, appdata_lua_path, etc.).
        """
        return self._installs

    async def scan(self) -> list[WoWInstall]:
        """Scan filesystem for WoW installs."""
        logger.info("Scanning for WoW installs")
        loop = asyncio.get_running_loop()
        base = await loop.run_in_executor(None, find_wow_base)
        installs = [WoWInstall(path=base)] if base else []
        # Only update the cached list if set_installs() has not already loaded
        # validated paths from config. This prevents a startup race where the
        # config-loaded installs get overwritten by a concurrent auto-scan that
        # completes after _resolve_wow_installs() has run.
        if not self._from_config:
            self._installs = installs
        logger.info("Found %d WoW install(s)", len(installs))
        return installs

    async def get_installs(self) -> list[WoWInstall]:
        """Return cached list; scan if empty (unless skip_scan is set)."""
        if not self._installs and not self._skip_scan:
            await self.scan()
        return self._installs

    def set_installs(self, installs: list[WoWInstall]) -> None:
        """Pre-populate the install list (e.g. validated entries from config)."""
        self._installs = list(installs)
        self._from_config = True
