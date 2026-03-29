"""Auction data pydantic models.

The real AppData.lua format uses LoadData() calls:
    select(2, ...).LoadData("TAG","RealmOrRegion",[[return {downloadTime=N,...}]])

Data tags observed from a real AppData.lua:
    APP_INFO                        - Global version/sync metadata
    AUCTIONDB_NON_COMMODITY_DATA    - Per-realm item price data
    AUCTIONDB_NON_COMMODITY_HISTORICAL - Per-realm historical prices
    AUCTIONDB_NON_COMMODITY_SCAN_STAT  - Per-realm scan stats
    AUCTIONDB_COMMODITY_DATA        - Region-wide commodity prices
    AUCTIONDB_COMMODITY_HISTORICAL  - Region-wide commodity historical
    AUCTIONDB_COMMODITY_SCAN_STAT   - Region-wide commodity scan stats
    AUCTIONDB_REGION_STAT           - Region-wide item stats
    AUCTIONDB_REGION_SALE           - Region-wide sale data
    AUCTIONDB_REGION_HISTORICAL     - Region-wide historical
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from tsm.api.types import AddonVersionInfo


class AppHelperEntry(BaseModel):
    """A single LoadData() entry in AppData.lua."""

    tag: str  # e.g. "AUCTIONDB_NON_COMMODITY_DATA"
    realm_or_region: str  # e.g. "Blackhand" or "EU"
    # Raw Lua string blob as returned by the API, written verbatim inside [[...]]
    data_blob: str
    download_time: int  # unix timestamp, extracted from data_blob for display
    # Game version directory this entry belongs to (e.g. "_retail_", "_classic_era_")
    gv_dir: str = ""


class AppInfo(BaseModel):
    """APP_INFO entry: application version and last sync time."""

    version: int
    last_sync: int  # unix timestamp
    message_id: int = 0
    message_text: str = ""


class RealmStatus(BaseModel):
    """Per-realm/region sync status for UI display."""

    display_name: str  # e.g. "EU-Tarren Mill" or "EU"
    is_region: bool
    auctiondb_status: str  # "Up to date" | "Updating..."
    last_updated: int  # unix timestamp from local AppData.lua (0 = never)
    # Fields needed to call realms2/remove API
    game_version: str = "retail"  # "retail" | "progression"
    region: str = ""  # e.g. "EU"
    name: str = ""  # e.g. "Tarren Mill"


class AuctionData(BaseModel):
    """All auction data to write into AppData.lua."""

    app_info: AppInfo | None = None
    # Keyed by (tag, realm_or_region) → data blob string
    entries: dict[tuple[str, str], AppHelperEntry] = Field(default_factory=dict)
    # All server realms/regions with their current sync status
    realm_statuses: list[RealmStatus] = Field(default_factory=list)
    # Addon versions from status API: [{name, version_str}, ...]
    addon_versions: list[AddonVersionInfo] = Field(default_factory=list)

    def add_entry(
        self,
        tag: str,
        realm_or_region: str,
        data_blob: str,
        download_time: int,
        gv_dir: str = "",
    ) -> None:
        self.entries[(tag, realm_or_region)] = AppHelperEntry(
            tag=tag,
            realm_or_region=realm_or_region,
            data_blob=data_blob,
            download_time=download_time,
            gv_dir=gv_dir,
        )

    @property
    def last_sync(self) -> int:
        if self.app_info:
            return self.app_info.last_sync
        if self.entries:
            return max(e.download_time for e in self.entries.values())
        return 0


class RealmData(BaseModel):
    """Simplified realm data used for UI display and SQLite caching."""

    realm_slug: str
    region: str
    # Raw data blobs keyed by tag, stored as-is from API, written verbatim to Lua
    blobs: dict[str, str] = Field(default_factory=dict)
    last_updated: int  # unix timestamp of most recent blob


class PriceData(BaseModel):
    item_id: int
    min_buyout: int
    quantity: int
    num_auctions: int
