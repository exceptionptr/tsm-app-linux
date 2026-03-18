"""WoWDetectorService: find WoW installs on Linux."""

from __future__ import annotations

import asyncio
import logging

from tsm.core.models.config import WoWInstall
from tsm.wow.detector import find_wow_installs

logger = logging.getLogger(__name__)


class WoWDetectorService:
    def __init__(self):
        self._installs: list[WoWInstall] = []
        self._custom_paths: list[str] = []

    async def scan(self) -> list[WoWInstall]:
        """Scan filesystem for WoW installs."""
        logger.info("Scanning for WoW installs")
        loop = asyncio.get_event_loop()
        installs = await loop.run_in_executor(None, find_wow_installs)
        self._installs = installs
        logger.info("Found %d WoW install(s)", len(installs))
        return installs

    async def get_installs(self) -> list[WoWInstall]:
        """Return cached list; scan if empty."""
        if not self._installs:
            await self.scan()
        return self._installs

    def add_custom_path(self, path: str) -> None:
        self._custom_paths.append(path)
