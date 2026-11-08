"""Auction data models.

AppData.lua holds one LoadData() entry per (tag, realm or region), see
tsm/wow/lua_writer.py. Tags seen from the live socket (2026-11-08):

    APP_INFO                            - global version, news and message
    AUCTIONDB_NON_COMMODITY_DATA        - per realm auction house prices
    AUCTIONDB_NON_COMMODITY_HISTORICAL  - per realm historical prices
    AUCTIONDB_NON_COMMODITY_SCAN_STAT   - per realm scan stats
    AUCTIONDB_COMMODITY_DATA            - region commodity prices (retail)
    AUCTIONDB_COMMODITY_HISTORICAL      - region commodity historical
    AUCTIONDB_COMMODITY_SCAN_STAT       - region commodity scan stats
    AUCTIONDB_REGION_STAT               - region item stats
    AUCTIONDB_REGION_SALE               - region sale data
    AUCTIONDB_REGION_HISTORICAL         - region historical
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from tsm.api.types import AddonVersionInfo


class AppInfo(BaseModel):
    """APP_INFO entry: application version and last sync time."""

    version: str
    last_sync: int  # unix timestamp
    message_id: int = 0
    message_text: str = ""
    news: list[dict[str, object]] = Field(default_factory=list)


class RealmStatus(BaseModel):
    """Per realm or region sync status for the Realm Data tab."""

    display_name: str  # e.g. "EU-Tarren Mill" or "EU"
    is_region: bool
    auctiondb_status: str  # "Up to date" | "Updating..." | "Waiting" | "Outdated"
    last_updated: int  # newest timestamp written to AppData.lua (0 = never)
    game_version: str = "retail"  # GameVersion.key: retail, bcc, classic, ...
    region: str = ""  # AppData region key: "EU", "BCC-EU", "HC-EU", ...
    name: str = ""  # AppData realm key: "Tarren Mill", "Everlook-Horde"
    # Server side identity, needed to remove the realm again.
    user_realm_id: str = ""
    realm_id: int = 0
    auction_house_type: str = ""  # "ALL" | "HORDE" | "ALLIANCE"
    # Newest data the server has for it (auction house or region lastModified).
    server_last_modified: int = 0


class AuctionData(BaseModel):
    """What one sync pass produced, for the UI."""

    app_info: AppInfo | None = None
    realm_statuses: list[RealmStatus] = Field(default_factory=list)
    # Addon releases from the socket, as [{name, version_str}].
    addon_versions: list[AddonVersionInfo] = Field(default_factory=list)
    # Number of AppData entries written in this pass.
    written: int = 0
    # None  = not checked yet / no game-version dirs found.
    # []    = every installed game version has its AppHelper addon folder.
    # [gv]  = these game versions are installed but their AppHelper folder is absent.
    apphelper_missing_gv: list[str] | None = None

    @property
    def last_sync(self) -> int:
        return self.app_info.last_sync if self.app_info else 0


class RealmData(BaseModel):
    """Simplified realm data used for SQLite caching."""

    realm_slug: str
    region: str
    blobs: dict[str, str] = Field(default_factory=dict)
    last_updated: int  # unix timestamp of most recent blob
