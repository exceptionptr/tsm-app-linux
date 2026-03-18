"""AddonWriterService: orchestrates writing auction data to WoW addon files."""

from __future__ import annotations

import logging
from pathlib import Path

from tsm.core.models.auction import AuctionData
from tsm.wow.lua_writer import LuaWriter

logger = logging.getLogger(__name__)


class AddonWriterService:
    def __init__(self, wow_detector=None):
        self._detector = wow_detector
        self._lua_writer = LuaWriter()

    async def write_data(self, data: AuctionData) -> list[Path]:
        """Write auction data Lua files to all detected WoW installs."""
        written: list[Path] = []
        if self._detector is None:
            logger.warning("No WoW detector configured")
            return written

        installs = await self._detector.get_installs()
        for install in installs:
            # AppData.lua lives directly inside the AppHelper addon folder
            addon_dir = Path(install.path) / "Interface/AddOns/TradeSkillMaster_AppHelper"
            if not addon_dir.exists():
                logger.debug("AppHelper addon not found: %s", addon_dir)
                continue
            try:
                path = self._lua_writer.write_app_data(data, addon_dir)
                written.append(path)
                logger.info("Wrote AppData.lua to %s", path)
            except Exception:
                logger.exception("Failed to write AppData.lua to %s", addon_dir)
        return written
