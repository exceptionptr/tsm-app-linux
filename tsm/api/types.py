"""TypedDicts for TSM API request/response shapes."""

from __future__ import annotations

from typing import TypedDict


class OIDCTokenResponse(TypedDict):
    """Keycloak OpenID Connect token response."""

    access_token: str
    token_type: str
    expires_in: int
    scope: str


class UserInfo(TypedDict):
    """TSM session + user data returned by the /v2/auth endpoint."""

    session: str
    userId: int
    endpointSubdomains: dict[str, str]


class AppDataString(TypedDict):
    """Single downloadable data blob entry inside an appDataStrings map."""

    url: str
    lastModified: int


class AddonVersionInfo(TypedDict):
    """Addon name + version from the status API ``addons`` list."""

    name: str
    version_str: str


class AddonMessage(TypedDict, total=False):
    """Optional broadcast message embedded in the status response."""

    id: int
    msg: str


class RealmEntry(TypedDict, total=False):
    """Realm or region entry within a status response realm list."""

    id: int
    name: str
    region: str
    appDataStrings: dict[str, AppDataString]


# Functional-form TypedDict required because some keys contain hyphens.
StatusResponse = TypedDict(
    "StatusResponse",
    {
        "addons": list[AddonVersionInfo],
        "addonMessage": AddonMessage,
        "appVersion": int,
        "realms": list[RealmEntry],
        "regions": list[RealmEntry],
        "realms-Progression": list[RealmEntry],
        "regions-Progression": list[RealmEntry],
        "extraClassicRealms": list[RealmEntry],
        "extraClassicRegions": list[RealmEntry],
        "extraAnniversaryRealms": list[RealmEntry],
        "extraAnniversaryRegions": list[RealmEntry],
    },
    total=False,
)
