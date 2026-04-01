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
        """Write auction data Lua files to all detected WoW installs.

        Also sets data.apphelper_missing_gv:
          None  - no game-version directories found to check
          []    - every installed game version has its AppHelper addon folder
          [gv]  - these game-version dirs exist but their AppHelper folder is absent
        """
        written: list[Path] = []
        if self._detector is None:
            logger.warning("No WoW detector configured")
            return written

        # Per-gv: True once the AppHelper folder is found in at least one install.
        # Only populated for gv dirs that were actually found on disk.
        gv_found: dict[str, bool] = {}

        installs = await self._detector.get_installs()
        for install in installs:
            base = Path(install.path)
            for gv in installed_versions(base):
                addon_folder = ah_dir(base, gv)
                if not addon_folder.exists():
                    logger.debug("AppHelper addon not found: %s", addon_folder)
                    if gv not in gv_found:
                        gv_found[gv] = False
                    continue
                gv_found[gv] = True
                try:
                    path = self._lua_writer.write_app_data(data, addon_folder, gv_dir=gv)
                    written.append(path)
                    logger.info("Wrote AppData.lua to %s", path)
                except Exception:
                    logger.exception("Failed to write AppData.lua to %s", addon_folder)

        if not gv_found:
            # No game-version directories scanned at all - leave as None.
            return written

        data.apphelper_missing_gv = [gv for gv, found in gv_found.items() if not found]
        return written
