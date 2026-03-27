"""WoWDetectorService: find WoW installs on Linux."""

from __future__ import annotations

import asyncio
import logging

from tsm.core.models.config import WoWInstall
from tsm.wow.detector import find_wow_installs

logger = logging.getLogger(__name__)


class WoWDetectorService:
    def __init__(self, skip_scan: bool = False):
        self._installs: list[WoWInstall] = []
        self._skip_scan = skip_scan

    @property
    def installs(self) -> list[WoWInstall]:
        """Return cached list of detected WoW installs."""
        return self._installs

    async def scan(self) -> list[WoWInstall]:
        """Scan filesystem for WoW installs."""
        logger.info("Scanning for WoW installs")
        loop = asyncio.get_running_loop()
        installs = await loop.run_in_executor(None, find_wow_installs)
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
