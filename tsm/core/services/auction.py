"""AuctionDataService: fetch auction data using the real TSM API flow.

Real flow (from MainThread.pyc):
1. Call status endpoint → returns dict with "realms", "regions", etc.
2. Get AppData per game version, only show realms if AppHelper is installed.
3. For each TAG where lastModified > local last_update, raw_download(url).
4. Write downloaded blob into AppData.lua via AppDataFile.

Status API keys → game version mapping:
  "realms"                → _retail_    (game_version API param: "retail")
  "realms-Progression"    → _classic_   (game_version API param: "bcc")
  "extraClassicRealms"    → _classic_era_
  "extraAnniversaryRealms"→ _anniversary_
  (same pattern for regions/extraClassicRegions/extraAnniversaryRegions)
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import cast

from tsm.api.client import TSMApiClient
from tsm.api.types import AppDataString, RealmEntry
from tsm.core.models.auction import AppInfo, AuctionData, RealmData, RealmStatus
from tsm.core.services.addon_writer import AddonWriterService
from tsm.storage.auction_cache import AuctionCache
from tsm.wow.lua_writer import AppDataFile

logger = logging.getLogger(__name__)

_REALM_LAST_UPDATED_TAG = "AUCTIONDB_NON_COMMODITY_DATA"
_REGION_LAST_UPDATED_TAG = "AUCTIONDB_REGION_STAT"

# Maps (status_key, regions_key, game_version_dir, api_game_version, is_classic_extra)
_REALM_CONFIGS = [
    # (realms_key, regions_key, gv_dir, api_gv, display_region_transform)
    ("realms", "regions", "_retail_", "retail", None),
    (
        "realms-Progression",
        "regions-Progression",
        "_classic_",
        "bcc",
        lambda r: r.replace("BCC-", "Progression-"),
    ),
    ("extraClassicRealms", "extraClassicRegions", "_classic_era_", "classic", None),
    ("extraAnniversaryRealms", "extraAnniversaryRegions", "_anniversary_", "anniversary", None),
]


class AuctionDataService:
    def __init__(
        self,
        api_client: TSMApiClient | None = None,
        cache: AuctionCache | None = None,
        addon_writer: AddonWriterService | None = None,
    ):
        self._client = api_client
        self._cache = cache
        self._addon_writer = addon_writer

    async def refresh_all_realms(self) -> AuctionData:
        """Fetch all stale realm/region data and write to AppData.lua files."""
        if self._client is None:
            logger.warning("No API client configured")
            return AuctionData(app_info=AppInfo(version=41402, last_sync=int(time.time())))

        logger.info("Fetching status from TSM API")
        result = await self._client.status.get()

        addon_msg = result.get("addonMessage", {})
        data = AuctionData(
            app_info=AppInfo(
                version=result.get("appVersion", 41402),
                last_sync=int(time.time()),
                message_id=addon_msg.get("id", 0),
                message_text=addon_msg.get("msg", ""),
            )
        )

        data.addon_versions = result.get("addons", [])

        existing = self._get_existing_app_data_files()

        # Guard: no valid WoW version directories found. Return without last_sync so
        # the viewmodel does not flag AppHelper as missing - this is a transient state
        # (detection pending) rather than a confirmed AppHelper absence.
        if not any(existing.values()):
            logger.info("No valid WoW game-version directory found, realm list will be empty")
            return AuctionData(addon_versions=data.addon_versions)

        loop = asyncio.get_running_loop()
        detector = self._addon_writer.get_detector() if self._addon_writer is not None else None
        installs = detector.installs if detector is not None else []

        for realms_key, regions_key, gv_dir, api_gv, region_transform in _REALM_CONFIGS:
            app_data = existing.get(gv_dir)
            if not app_data:
                continue  # AppHelper not installed for this game version, skip

            # Classic Era and Anniversary: only include realms the user has active
            # characters on.  Mirrors the Windows app's get_active_*_factionrealms()
            # filter so users who only play retail are not shown hundreds of extra rows.
            active_factionrealms: set[tuple[str, str]] | None = None
            if gv_dir in ("_classic_era_", "_anniversary_"):
                from tsm.wow.accounts import get_active_factionrealms

                active: set[tuple[str, str]] = set()
                for install in installs:
                    active |= await loop.run_in_executor(
                        None, get_active_factionrealms, install, gv_dir
                    )
                if not active:
                    # No characters on this game version - skip all rows for it
                    logger.debug("No active %s characters found, skipping realm list", gv_dir)
                    continue
                active_factionrealms = active

            # Process realms, dynamic key access requires cast (key is a runtime variable)
            for realm in cast(list[RealmEntry], result.get(realms_key, [])):
                name = realm.get("name", "")
                region = realm.get("region", "")

                # Character filter: "Classic-US" -> "US", match against active set
                if active_factionrealms is not None:
                    region_code = region.split("-")[-1]
                    if (region_code, name) not in active_factionrealms:
                        continue

                strings = realm.get("appDataStrings", {})
                # Apply display-name transform (BCC-EU → Progression-EU)
                disp_region = region_transform(region) if region_transform else region
                display = f"{disp_region}-{name}" if disp_region else name
                pending = _pending_strings(strings, name, app_data)
                adb_status = "Updating..." if pending else "Up to date"
                last_updated = _local_timestamp(app_data, _REALM_LAST_UPDATED_TAG, name)

                rs = RealmStatus(
                    display_name=display,
                    is_region=False,
                    auctiondb_status=adb_status,
                    last_updated=last_updated,
                    game_version=api_gv,
                    region=region,
                    name=name,
                )
                data.realm_statuses.append(rs)
                await self._process_entry(name, pending, data, gv_dir=gv_dir)
                if pending:
                    rs.auctiondb_status = "Up to date"
                    # Only update the display timestamp when the primary display tag was
                    # actually downloaded.  If other tags updated (e.g. SCAN_STAT) but
                    # NON_COMMODITY_DATA was unchanged, keep the existing _local_timestamp
                    # value so the column matches what is stored in AppData.lua.
                    if _REALM_LAST_UPDATED_TAG in pending:
                        rs.last_updated = pending[_REALM_LAST_UPDATED_TAG]["lastModified"]

            # Process regions, dynamic key access requires cast (key is a runtime variable)
            active_regions = (
                {r[0] for r in active_factionrealms} if active_factionrealms is not None else None
            )
            for region_rec in cast(list[RealmEntry], result.get(regions_key, [])):
                name = region_rec.get("name", "")

                # Character filter: only include regions the user has active realms in
                if active_regions is not None:
                    region_code = name.split("-")[-1]  # "Classic-US" -> "US"
                    if region_code not in active_regions:
                        continue

                strings = region_rec.get("appDataStrings", {})
                pending = _pending_strings(strings, name, app_data)

                adb_status = "Updating..." if pending else "Up to date"
                last_updated = _local_timestamp(app_data, _REGION_LAST_UPDATED_TAG, name)

                rg = RealmStatus(
                    display_name=name,
                    is_region=True,
                    auctiondb_status=adb_status,
                    last_updated=last_updated,
                    game_version=api_gv,
                    region=name,
                    name=name,
                )
                data.realm_statuses.append(rg)
                await self._process_entry(name, pending, data, gv_dir=gv_dir)
                if pending:
                    rg.auctiondb_status = "Up to date"
                    # Mirror realm logic: only update when REGION_STAT itself was downloaded.
                    if _REGION_LAST_UPDATED_TAG in pending:
                        rg.last_updated = pending[_REGION_LAST_UPDATED_TAG]["lastModified"]

        if self._addon_writer:
            await self._addon_writer.write_data(data)

        if self._cache and data.realm_statuses:
            await self._cache.save_snapshot(data.realm_statuses)

        return data

    async def _process_entry(
        self,
        name: str,
        pending: dict[str, AppDataString],
        data: AuctionData,
        gv_dir: str = "",
    ) -> None:
        for tag, info in pending.items():
            blob = await self._download_blob(info["url"], tag, name)
            if blob:
                data.add_entry(tag, name, blob, info["lastModified"], gv_dir=gv_dir)

    async def _download_blob(self, url: str, tag: str, name: str) -> str | None:
        logger.info("Downloading %s / %s", tag, name)
        if self._client is None:
            return None
        try:
            blob = await self._client.raw_download(url)
            if "<html>" in blob:
                logger.error("Got HTML response for %s/%s", tag, name)
                return None
            return blob
        except Exception:
            logger.exception("Failed to download %s/%s", tag, name)
            return None

    def _get_existing_app_data_files(self) -> dict[str, list[AppDataFile]]:
        """Return {game_version_dir: [AppDataFile, ...]} for each game version.

        Collects one AppDataFile per WoW install per game version. Multiple
        files arise when the user has more than one WoW installation (e.g. two
        different Wine prefixes). Callers use the minimum timestamp across all
        files so that a re-download is triggered when any install is behind.

        Uses the cached install list from WoWDetectorService without triggering
        a filesystem scan. Detection is handled by the scheduler at startup.
        """
        from tsm.wow.utils import appdata_lua_path, apphelper_dir

        result: dict[str, list[AppDataFile]] = {
            "_retail_": [],
            "_classic_era_": [],
            "_classic_": [],
            "_anniversary_": [],
        }
        detector = self._addon_writer.get_detector() if self._addon_writer is not None else None
        if detector is None:
            return result
        installs = detector.installs  # sync: no scan triggered here
        for install in installs:
            base = Path(install.path)
            for gv in result:
                # Gate on the AppHelper addon folder existing, not just the game-version
                # directory. Mirrors Windows get_app_data() which returns None when
                # AppHelper is absent, skipping sync for that game version entirely.
                # AppDataFile still handles a missing AppData.lua gracefully so that
                # AppData.lua is created on first run after AppHelper is installed.
                if apphelper_dir(base, gv).is_dir():
                    result[gv].append(AppDataFile(appdata_lua_path(base, gv)))
        return result

    async def remove_realm(self, game_version: str, region: str, name: str) -> None:
        if self._client is None:
            return
        await self._client.realms.remove(game_version, region, name)

    async def add_realm(self, game_version: str, realm_id: int) -> None:
        if self._client is None:
            return
        await self._client.realms.add(game_version, realm_id)

    async def get_snapshot(self) -> tuple[list[RealmStatus], int]:
        """Load last-known realm list from DB for immediate display at startup.

        Returns (statuses, saved_at) where saved_at is the unix timestamp of the
        last successful sync, use this for staleness, not per-realm last_updated.
        """
        if self._cache is None:
            return [], 0
        return await self._cache.load_snapshot()

    async def get_cached_realms(self) -> list[RealmData]:
        if self._cache is None:
            return []
        return await self._cache.get_all()


def _pending_strings(
    strings: dict[str, AppDataString], name: str, app_data_files: list[AppDataFile]
) -> dict[str, AppDataString]:
    """Return only the appDataStrings entries newer than local timestamp.

    Uses the minimum timestamp across all WoW installs for the same game
    version, ensuring a re-download when any install is behind.
    """
    pending = {}
    for tag, info in strings.items():
        last_modified = info["lastModified"]
        local_ts = min((f.last_update(tag, name) for f in app_data_files), default=0)
        if last_modified > local_ts:
            pending[tag] = info
    return pending


def _local_timestamp(app_data_files: list[AppDataFile], tag: str, name: str) -> int:
    """Return the minimum last-update timestamp across all WoW installs."""
    return min((f.last_update(tag, name) for f in app_data_files), default=0)
