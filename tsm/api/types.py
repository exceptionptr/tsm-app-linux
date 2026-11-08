"""TypedDicts for the TSM backend payloads (shapes verified live 2026-11-08)."""

from __future__ import annotations

# typing_extensions, not typing: pydantic models use some of these as field
# types, and pydantic rejects typing.TypedDict on Python < 3.12.
from typing_extensions import NotRequired, TypedDict  # noqa: UP035


class AuctionHouse(TypedDict):
    auctionHouseId: int
    type: str  # "All" | "Alliance" | "Horde"
    lastModified: int


class Region(TypedDict):
    regionId: int
    name: str  # "Europe"
    regionPrefix: str  # "eu"
    gameVersion: str  # "Retail", "Wrath", "Classic Era", ..., "Forever"
    gmtOffset: NotRequired[int]
    lastModified: NotRequired[int]
    gameType: NotRequired[str]
    gameVersionType: NotRequired[str]


class Realm(TypedDict):
    realmId: int
    regionId: int
    name: str
    localizedName: str
    slug: NotRequired[str]
    locale: NotRequired[str]
    connectedRealmId: NotRequired[int]
    auctionHouses: NotRequired[list[AuctionHouse] | None]
    region: Region


class UserRealm(TypedDict):
    id: str  # "usr_rlm_..."
    userId: str
    realmId: int
    auctionHouseType: str  # "ALL" | "ALLIANCE" | "HORDE"


class GameVersionInfo(TypedDict):
    gameType: str
    label: str
    folder: str  # "_retail_"


class RealmAuctionDb(TypedDict):
    """Payload of the realm_auctiondb / realm_shopping socket events."""

    realmId: int
    auctionHouseType: str
    stringType: str
    lastModified: int | str  # the server sends both
    url: str


class RegionAuctionDb(TypedDict):
    """Payload of the region_auctiondb socket event."""

    regionId: int
    stringType: str
    lastModified: int | str
    url: str


class AddonRelease(TypedDict):
    """One entry of the addon socket event's data list."""

    addon: str  # "TradeSkillMaster" | "TradeSkillMaster_AppHelper"
    channel: str
    version: str  # "v4.15.4"
    url: str


class AppInfoMessage(TypedDict, total=False):
    id: int
    msg: str


class NewsItem(TypedDict, total=False):
    title: str
    content: str
    timestamp: int
    link: str


class AppInfoPayload(TypedDict, total=False):
    message: AppInfoMessage
    news: list[NewsItem]


class AddonVersionInfo(TypedDict):
    """Addon name and latest version, as the Addon Versions tab shows them."""

    name: str
    version_str: str
