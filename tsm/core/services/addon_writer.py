"""AddonWriterService: orchestrates writing auction data to WoW addon files."""

from __future__ import annotations

import logging
from pathlib import Path

from tsm.core.models.auction import AuctionData
from tsm.core.services.wow_detector import WoWDetectorService
from tsm.wow.lua_writer import LuaWriter
from tsm.wow.utils import apphelper_dir as ah_dir
from tsm.wow.utils import installed_versions

logger = logging.getLogger(__name__)


class AddonWriterService:
    def __init__(self, wow_detector: WoWDetectorService | None = None):
        self._detector = wow_detector
        self._lua_writer = LuaWriter()

    def get_detector(self) -> WoWDetectorService | None:
        """Return the WoW detector service."""
        return self._detector

    @property
    def installs(self):
        """Return cached WoW installs from the detector."""
        return self._detector.installs if self._detector is not None else []

    async def write_data(self, data: AuctionData) -> list[Path]:
        """Write auction data Lua files to all detected WoW installs."""
        written: list[Path] = []
        if self._detector is None:
            logger.warning("No WoW detector configured")
            return written

        installs = await self._detector.get_installs()
        for install in installs:
            base = Path(install.path)
            for gv in installed_versions(base):
                addon_folder = ah_dir(base, gv)
                if not addon_folder.exists():
                    logger.debug("AppHelper addon not found: %s", addon_folder)
                    continue
                try:
                    path = self._lua_writer.write_app_data(data, addon_folder, gv_dir=gv)
                    written.append(path)
                    logger.info("Wrote AppData.lua to %s", path)
                except Exception:
                    logger.exception("Failed to write AppData.lua to %s", addon_folder)
        return written
