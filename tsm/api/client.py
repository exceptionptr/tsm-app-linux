"""TSM REST client for the backend the official 1.0.14 desktop app uses.

Replaces the legacy app-server /v2 API (HMAC-signed query strings, plain HTTP,
per-session endpointSubdomains). Every service here is HTTPS with a verified
certificate and takes the Keycloak access token as a Bearer header.

    realm-api        GET  /v2/realms, /v2/regions     realm and region catalogue
    desktop-backend  GET  /game-versions              folders and labels per game
                     GET  /user-realms?userIds=<sub>  realms the account follows
                     POST /user-realms                follow a realm auction house
                     DELETE /user-realms/<id>         stop following one
    addon-version    GET  /channels                   labels for beta channels

Header sets follow a capture of the official client, per channel: its REST worker
scripts use node-fetch, its blob downloads and machine-name calls use Node's
undici. See node_fetch_headers() and undici_headers().

Auction data itself is not fetched here: the socket (tsm/api/socket.py) pushes a
presigned download URL for every blob, which download() then fetches.
"""

from __future__ import annotations

import asyncio
import contextlib
import gzip
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp
from aiohttp.compression_utils import HAS_BROTLI

from tsm.api.http import AUTO, NODE_SSL, UNDICI_SSL, OrderedRequest, raw_url
from tsm.api.official import UA_NODE_FETCH, UA_UNDICI
from tsm.api.types import GameVersionInfo, Realm, Region, UserRealm

logger = logging.getLogger(__name__)

REALM_API = "https://realm-api.tradeskillmaster.com"
DESKTOP_BACKEND = "https://desktop-backend.tradeskillmaster.com"
ADDON_VERSION_API = "https://addon-version.tradeskillmaster.com"

MAX_RETRIES = 3
RETRY_DELAY = 2.0

TokenProvider = Callable[[], Awaitable[str]]


class TSMApiError(RuntimeError):
    """A TSM service answered with an error status."""

    def __init__(self, status: int, message: str, endpoint: str = "") -> None:
        super().__init__(f"{status} {message} ({endpoint})" if endpoint else f"{status} {message}")
        self.status = status
        self.message = message


def is_transient_error(exc: BaseException) -> bool:
    """True when a failure says nothing about the credentials or the request.

    No network yet, a timeout, a dropped connection, a 5xx or a 429 can all pass
    on their own, so waiting and trying again is right. A 4xx is the server
    answering no, and asking again gives the same answer.
    """
    if isinstance(exc, TSMApiError):
        return exc.status >= 500 or exc.status in (408, 429)
    if isinstance(exc, aiohttp.ClientResponseError):
        return exc.status >= 500 or exc.status in (408, 429)
    return isinstance(exc, aiohttp.ClientError | TimeoutError)


def _accept_encoding(official: str) -> str:
    """The official Accept-Encoding minus br when aiohttp cannot decode it."""
    if HAS_BROTLI:
        return official
    return ", ".join(e for e in official.split(", ") if e != "br")


def node_fetch_headers(token: str | None = None) -> dict[str, str]:
    """Headers of the official node-fetch channel (REST services, addon zip).

    Order as captured: accept, accept-encoding, authorization, content-length and
    content-type (bodies only), user-agent, then Host and Connection capitalised.
    AUTO entries fix a position, aiohttp fills the value (see tsm/api/http.py).
    """
    headers = {
        "Accept": "*/*",
        "Accept-Encoding": _accept_encoding("gzip, deflate, br"),
    }
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    headers["Content-Length"] = AUTO
    headers["Content-Type"] = AUTO
    headers["User-Agent"] = UA_NODE_FETCH
    headers["Host"] = AUTO
    headers["Connection"] = AUTO
    return headers


def undici_headers(token: str | None = None) -> dict[str, str]:
    """Headers of the official undici channel (presigned downloads, machine names).

    Order as captured: host, connection: keep-alive, Authorization, content-type,
    accept, accept-language, sec-fetch-mode, user-agent, accept-encoding,
    content-length. Names are lower case except Authorization. The official client
    adds sentry-trace and baggage after accept-encoding; this app never does.
    """
    headers: dict[str, str] = {"host": AUTO, "connection": AUTO}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    headers.update(
        {
            "content-type": AUTO,
            "accept": "*/*",
            "accept-language": "*",
            "sec-fetch-mode": "cors",
            "user-agent": UA_UNDICI,
            "accept-encoding": _accept_encoding("br, gzip, deflate"),
            "content-length": AUTO,
        }
    )
    return headers


def _gunzip_if_needed(raw: bytes) -> bytes:
    if raw[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(raw)
        except OSError:
            return raw
    return raw


class TSMApiClient:
    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._token_provider: TokenProvider | None = None

    # ------------------------------------------------------------------ #
    # Session
    # ------------------------------------------------------------------ #

    async def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # No default headers: every channel builder sends its own full set and
            # OrderedRequest adds nothing (no User-Agent, Accept or Accept-Encoding).
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=120, sock_read=60),
                request_class=OrderedRequest,
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def set_token_provider(self, provider: TokenProvider | None) -> None:
        """Coroutine returning a valid access token, refreshing it if needed."""
        self._token_provider = provider

    async def _token(self) -> str:
        if self._token_provider is None:
            raise RuntimeError("Not authenticated")
        return await self._token_provider()

    # ------------------------------------------------------------------ #
    # Core request
    # ------------------------------------------------------------------ #

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json_body: Any = None,
        endpoint: str = "",
        undici: bool = False,
    ) -> Any:
        """Authenticated JSON request with retries on transient failures.

        Sends the node-fetch header set, or the undici one with undici=True.
        """
        session = await self.session()
        build = undici_headers if undici else node_fetch_headers
        for attempt in range(MAX_RETRIES):
            headers = build(await self._token())
            try:
                async with session.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                    ssl=UNDICI_SSL if undici else NODE_SSL,
                ) as resp:
                    if resp.status >= 400:
                        msg = resp.reason or ""
                        with contextlib.suppress(Exception):
                            body = await resp.json(content_type=None)
                            if isinstance(body, dict) and isinstance(body.get("message"), str):
                                msg = body["message"]
                        err = TSMApiError(resp.status, msg, endpoint or url)
                        if not is_transient_error(err) or attempt == MAX_RETRIES - 1:
                            raise err
                        delay = RETRY_DELAY * (attempt + 1)
                        retry_after = resp.headers.get("Retry-After")
                        if retry_after:
                            with contextlib.suppress(ValueError):
                                delay = max(delay, float(retry_after))
                        logger.warning("%s failed (attempt %d): %s", endpoint, attempt + 1, err)
                        await asyncio.sleep(delay)
                        continue
                    if "application/json" in resp.headers.get("content-type", ""):
                        return await resp.json(content_type=None)
                    return await resp.text()
            except (aiohttp.ClientError, TimeoutError) as e:
                if attempt == MAX_RETRIES - 1:
                    raise
                logger.warning("%s network error (attempt %d): %s", endpoint, attempt + 1, e)
                await asyncio.sleep(RETRY_DELAY * (attempt + 1))
        raise RuntimeError("All retries exhausted")

    # ------------------------------------------------------------------ #
    # Catalogue
    # ------------------------------------------------------------------ #

    async def realms(self) -> list[Realm]:
        data = await self.request("GET", f"{REALM_API}/v2/realms", endpoint="realm-api /v2/realms")
        items: list[Realm] = data.get("items", [])
        return items

    async def regions(self) -> list[Region]:
        data = await self.request(
            "GET", f"{REALM_API}/v2/regions", endpoint="realm-api /v2/regions"
        )
        items: list[Region] = data.get("items", [])
        return items

    async def game_versions(self) -> list[GameVersionInfo]:
        data: list[GameVersionInfo] = await self.request(
            "GET", f"{DESKTOP_BACKEND}/game-versions", endpoint="game versions"
        )
        return data

    async def release_channel_labels(self) -> list[dict[str, str]]:
        """[{name, label}] for the channels the account may use. [] when not allowed."""
        try:
            data: list[dict[str, str]] = await self.request(
                "GET", f"{ADDON_VERSION_API}/channels", endpoint="release channels"
            )
        except TSMApiError as e:
            if e.status == 403:
                return []
            raise
        return data

    # ------------------------------------------------------------------ #
    # User realms
    # ------------------------------------------------------------------ #

    async def user_realms(self, user_id: str) -> list[UserRealm]:
        data = await self.request(
            "GET",
            f"{DESKTOP_BACKEND}/user-realms",
            params={"userIds": user_id},
            endpoint="user realms GET",
        )
        items: list[UserRealm] = data.get("items", []) if isinstance(data, dict) else []
        return items

    async def add_user_realm(self, user_id: str, realm_id: int, auction_house_type: str) -> None:
        await self.request(
            "POST",
            f"{DESKTOP_BACKEND}/user-realms",
            json_body={
                "realmId": realm_id,
                "userId": user_id,
                "auctionHouseType": auction_house_type.upper(),
            },
            endpoint="user realms POST",
        )

    async def delete_user_realm(self, user_realm_id: str) -> None:
        await self.request(
            "DELETE",
            f"{DESKTOP_BACKEND}/user-realms/{user_realm_id}",
            endpoint="user realms DELETE",
        )

    # ------------------------------------------------------------------ #
    # Group sends, machine names, backups
    # ------------------------------------------------------------------ #

    async def claim_group_sends(self, game_types: list[str]) -> list[Any]:
        data = await self.request(
            "POST",
            f"{DESKTOP_BACKEND}/group-sends/claim",
            json_body={"gameTypes": game_types},
            endpoint="group sends claim",
        )
        return data if isinstance(data, list) else []

    async def local_machine_names(self, system_ids: list[str]) -> list[dict[str, Any]]:
        data = await self.request(
            "GET",
            f"{DESKTOP_BACKEND}/local-machine-name",
            params={"systemIds": ",".join(system_ids)},
            endpoint="local machine names GET",
            undici=True,
        )
        items: list[dict[str, Any]] = data.get("items", []) if isinstance(data, dict) else []
        return items

    async def set_local_machine_name(self, system_id: str, name: str) -> None:
        await self.request(
            "POST",
            f"{DESKTOP_BACKEND}/local-machine-name",
            json_body={"systemId": system_id, "localMachineName": name},
            endpoint="local machine names POST",
            undici=True,
        )

    async def remote_backups(self) -> Any:
        return await self.request(
            "GET", f"{DESKTOP_BACKEND}/backups", endpoint="remote backups"
        )

    # ------------------------------------------------------------------ #
    # Downloads (presigned, no auth header)
    # ------------------------------------------------------------------ #

    async def download_addon_zip(self, url: str) -> bytes | None:
        """Fetch an addon zip the way the official installer does (node-fetch headers)."""
        return await self.download(url, headers=node_fetch_headers(), node_fetch=True)

    async def download(
        self,
        url: str,
        attempts: int = 6,
        *,
        headers: dict[str, str] | None = None,
        node_fetch: bool = False,
    ) -> bytes | None:
        """Fetch a presigned blob URL. Returns None on 404 (superseded data).

        Sends the undici headers without Authorization or Range, as the official
        worker does, unless headers says otherwise. The URL goes out byte for byte.
        node_fetch selects the TLS context of the node-fetch channel (addon zip)
        instead of the undici one.

        Retries 408, 429 and 5xx with backoff like the official worker. The body
        is gunzipped when it still carries the gzip magic: AuctionDB blobs are
        gzip files, and a Content-Encoding header may or may not have unpacked
        them already.
        """
        session = await self.session()
        headers = headers if headers is not None else undici_headers()
        tls = NODE_SSL if node_fetch else UNDICI_SSL
        delay = 1.0
        last: BaseException | None = None
        for attempt in range(1, attempts + 1):
            try:
                async with session.get(
                    raw_url(url),
                    headers=headers,
                    ssl=tls,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    if resp.status == 404:
                        return None
                    if resp.status == 200:
                        return _gunzip_if_needed(await resp.read())
                    last = aiohttp.ClientResponseError(
                        resp.request_info,
                        resp.history,
                        status=resp.status,
                        message=resp.reason or "",
                    )
                    if resp.status not in (408, 429) and resp.status < 500:
                        raise last
            except aiohttp.ClientResponseError:
                raise
            except (aiohttp.ClientError, TimeoutError) as e:
                last = e
            if attempt < attempts:
                await asyncio.sleep(min(30.0, delay))
                delay *= 2
        assert last is not None
        raise last
