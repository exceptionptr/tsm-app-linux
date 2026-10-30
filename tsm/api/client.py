"""TSM API aiohttp client: reverse-engineered from AppAPI.pyc.

Authentication flow (from decompiled source):
1. POST https://id.tradeskillmaster.com/realms/app/protocol/openid-connect/token
   form data: username, password, client_id=legacy-desktop-app, grant_type=password,
              code="", redirect_uri="", scope=openid
   → returns {\"access_token\": \"...\", ...}

2. POST http://app-server.tradeskillmaster.com/v2/auth
   body: {\"token\": \"<access_token>\"}
   query: session, version, time, token (HMAC)
   → returns user_info dict with session, userId, isPremium, endpointSubdomains

3. All subsequent calls: http://{subdomain}.tradeskillmaster.com/v2/{endpoint_parts}
   query params: session, version, time, token(HMAC), channel
   HMAC token = SHA256(\"{version}:{time}:{SECRET}\")
   tsm_version is sent on /v2/status only, carrying the installed
   TradeSkillMaster addon version. The subdomain comes from endpointSubdomains,
   which the server assigns per session: status lands on app-server while addon
   lands on app-server4 or app-server5, and each one rejects endpoints it was
   not assigned.

AppData download flow:
- Call status endpoint → returns realm/region list with appDataStrings
- Each appDataStrings entry has {\"url\": \"...\", \"lastModified\": timestamp}
- Compare lastModified vs local cache; download from url if stale
- Write raw data string into AppData.lua via LoadData() format
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from gzip import GzipFile
from hashlib import sha256
from io import BytesIO
from typing import Any

import aiohttp

from tsm.api.types import (
    OIDCTokenResponse,
    RealmEntry,
    StatusResponse,
    UserInfo,
)

logger = logging.getLogger(__name__)


class TSMApiError(RuntimeError):
    """The API answered HTTP 200 with {"success": false, "error": ...}.

    The server uses this envelope for every rejection: an expired or unknown
    session, a route the contacted subdomain does not serve, a malformed query.
    The message is generic ("Invalid request."), so it never identifies which.
    """


def is_transient_error(exc: BaseException) -> bool:
    """True when a failure says nothing about the credentials or the request.

    No network yet, a timeout, a dropped connection, a 5xx or a 429 can all pass
    on their own, so waiting and trying again is right. A 4xx is the server
    answering no, and asking again gives the same answer.
    """
    if isinstance(exc, aiohttp.ClientResponseError):
        return exc.status >= 500 or exc.status == 429
    return isinstance(exc, aiohttp.ClientError | TimeoutError)


APP_VERSION = 41402  # From _version.pyc: VERSION = 41402
HMAC_SECRET = "3FB1CC5EDC5B43F21CB8ACC23B42B703"  # From AppAPI.pyc
OIDC_URL = "https://id.tradeskillmaster.com/realms/app/protocol/openid-connect/token"
APP_SERVER = "http://app-server.tradeskillmaster.com/v2"
MAX_RETRIES = 3
RETRY_DELAY = 2.0


def _hmac_token(current_time: int) -> str:
    """Compute request authentication token."""
    raw = f"{APP_VERSION}:{current_time}:{HMAC_SECRET}"
    return sha256(raw.encode("utf-8")).hexdigest()


def _query_params(
    session: str = "", channel: str = "", tsm_version: str = ""
) -> dict[str, str | int]:
    t = int(time.time())
    params: dict[str, str | int] = {
        "session": session,
        "version": APP_VERSION,
        "time": t,
        "token": _hmac_token(t),
    }
    if channel:
        params["channel"] = channel
    if tsm_version:
        params["tsm_version"] = tsm_version
    return params


class TSMApiClient:
    """Full TSM API client matching the original AppAPI.py behaviour."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._user_info: UserInfo = {"session": "", "userId": 0, "endpointSubdomains": {}}
        self._endpoint_subdomains: dict[str, str] = {}
        self._reauth: Callable[[], Awaitable[None]] | None = None
        self._reauth_lock = asyncio.Lock()
        self._session_generation = 0
        self.auth = AuthAPI(self)
        self.status = StatusAPI(self)
        self.addon = AddonAPI(self)
        self.realms = RealmsAPI(self)

    # ------------------------------------------------------------------ #
    # Session management
    # ------------------------------------------------------------------ #

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=120),
                connector=aiohttp.TCPConnector(),
                headers={"User-Agent": f"TSMApplication/{APP_VERSION}"},
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------ #
    # Core request helpers
    # ------------------------------------------------------------------ #

    def _subdomain_for(self, endpoint: str) -> str:
        if endpoint in ("auth", "log", "realms2"):
            return "app-server"
        sub = self._endpoint_subdomains.get(endpoint)
        if not sub:
            raise RuntimeError(
                f"Endpoint '{endpoint}' not in endpointSubdomains, not authenticated?"
            )
        return sub

    async def api_request(
        self,
        *parts: str,
        data: dict[str, Any] | str | bytes | None = None,
        channel: str = "",
        tsm_version: str = "",
    ) -> Any:
        """Make a request to http://{subdomain}.tradeskillmaster.com/v2/{parts}.

        A rejected request is retried once after re-authenticating, so a session
        the server no longer accepts recovers in place instead of leaving the
        app broken until it is restarted.
        """
        endpoint = parts[0]
        req_headers: dict[str, str] = {}
        body = None

        if data is not None:
            if isinstance(data, dict):
                raw = json.dumps(data).encode("utf-8")
                req_headers["Content-Type"] = "application/json"
            elif isinstance(data, str):
                raw = data.encode("utf-8")
                req_headers["Content-Type"] = "text/plain"
            else:
                raw = data
                req_headers["Content-Type"] = "application/octet-stream"

            # Gzip everything except raw bytes
            if not isinstance(data, bytes):
                buf = BytesIO()
                with GzipFile(fileobj=buf, mode="wb") as gz:
                    gz.write(raw)
                body = buf.getvalue()
                req_headers["Content-Encoding"] = "gzip"
            else:
                body = raw

        method = "POST" if data is not None else "GET"

        try:
            return await self._send(parts, method, body, req_headers, channel, tsm_version)
        except TSMApiError as e:
            if not await self._try_reauth(endpoint, e):
                raise
        return await self._send(parts, method, body, req_headers, channel, tsm_version)

    async def _try_reauth(self, endpoint: str, error: TSMApiError) -> bool:
        """Log in again after a rejection. Returns True if the caller should retry.

        The auth endpoint is excluded so the login inside the callback cannot
        recurse, which is also what keeps it from deadlocking on the lock. When
        several requests are rejected at once only the first logs in; the others
        wait and then retry against the session it produced.
        """
        if self._reauth is None or endpoint == "auth":
            return False

        generation = self._session_generation
        async with self._reauth_lock:
            if self._session_generation != generation:
                return True  # another caller already refreshed the session
            logger.warning("API rejected the request (%s), re-authenticating", error)
            try:
                await self._reauth()
            except Exception:
                logger.exception("Re-authentication failed")
                return False
        return True

    async def _send(
        self,
        parts: tuple[str, ...],
        method: str,
        body: bytes | None,
        req_headers: dict[str, str],
        channel: str,
        tsm_version: str,
    ) -> Any:
        """One request plus the transient-failure retries.

        The URL and query params are built here rather than by the caller: a
        re-authentication in between changes both the session token and the
        subdomain this endpoint is served from.
        """
        subdomain = self._subdomain_for(parts[0])
        url = "http://{}.tradeskillmaster.com/v2/{}".format(subdomain, "/".join(parts))
        params = _query_params(self._user_info.get("session", ""), channel, tsm_version)
        session = await self._get_session()

        for attempt in range(MAX_RETRIES):
            try:
                async with session.request(
                    method, url, params=params, data=body, headers=req_headers
                ) as resp:
                    resp.raise_for_status()
                    ct = resp.headers.get("content-type", "")
                    if "application/json" in ct:
                        payload = await resp.json(content_type=None)
                        # Every /v2 endpoint wraps its answer in {"success": ...}.
                        # Only an explicit false is an error: a response without
                        # the key is passed through rather than rejected.
                        if isinstance(payload, dict) and payload.get("success") is False:
                            raise TSMApiError(payload.get("error", payload))
                        return payload
                    if "application/zip" in ct or "application/octet-stream" in ct:
                        return await resp.read()
                    # text/plain or other
                    return await resp.text()
            except aiohttp.ClientResponseError as e:
                if 400 <= e.status < 500 and e.status != 429:
                    raise
                if attempt == MAX_RETRIES - 1:
                    raise
                delay = RETRY_DELAY * (attempt + 1)
                if e.status == 429:
                    retry_after = e.headers.get("Retry-After") if e.headers else None
                    if retry_after:
                        with contextlib.suppress(ValueError):
                            delay = max(float(retry_after), delay)
                logger.warning("API request failed (attempt %d): %s", attempt + 1, e)
                await asyncio.sleep(delay)
            except aiohttp.ClientError as e:
                if attempt == MAX_RETRIES - 1:
                    raise
                logger.warning("Network error (attempt %d): %s", attempt + 1, e)
                await asyncio.sleep(RETRY_DELAY * (attempt + 1))

        raise RuntimeError("All retries exhausted")

    async def raw_download(self, url: str) -> str:
        """Download a raw data URL (CDN). Returns decompressed text."""
        session = await self._get_session()
        # Try https first if given http
        urls = [url]
        if url.startswith("http://"):
            urls.insert(0, url.replace("http://", "https://", 1))

        last_exc: Exception | None = None
        for attempt_url in urls:
            try:
                async with session.get(attempt_url, allow_redirects=True) as resp:
                    resp.raise_for_status()
                    raw = await resp.read()
                    # aiohttp auto-decompresses Content-Encoding:gzip responses.
                    # Only manually decompress if magic bytes indicate it wasn't.
                    if raw[:2] == b"\x1f\x8b":
                        return GzipFile(fileobj=BytesIO(raw)).read().decode("utf-8")
                    return raw.decode("utf-8")
            except Exception as e:
                last_exc = e
                continue
        raise RuntimeError(f"raw_download failed for {url}: {last_exc}")

    async def fetch_bytes(self, url: str) -> bytes:
        """Fetch raw bytes from an arbitrary URL (e.g. CDN redirect for addon zip)."""
        session = await self._get_session()
        async with session.get(url, allow_redirects=True) as resp:
            resp.raise_for_status()
            return await resp.read()

    # ------------------------------------------------------------------ #
    # User info accessors
    # ------------------------------------------------------------------ #

    @property
    def session_token(self) -> str:
        return self._user_info["session"]

    def set_user_info(self, user_info: UserInfo) -> None:
        self._user_info = user_info
        self._endpoint_subdomains = user_info["endpointSubdomains"]
        self._session_generation += 1

    def set_reauth_callback(self, callback: Callable[[], Awaitable[None]] | None) -> None:
        """Register a coroutine that logs in again and refreshes the user info.

        A rejected request is retried once after calling it. Both things that
        make the server reject us are cured by a fresh /v2/auth: the session
        token expires, and endpointSubdomains is handed out per session, so a
        subdomain that stops serving an endpoint is only corrected by logging
        in again.
        """
        self._reauth = callback


class AuthAPI:
    def __init__(self, client: TSMApiClient):
        self._c = client

    async def get_oidc_token(self, username: str, password: str) -> OIDCTokenResponse:
        """Step 1: Get OpenID Connect token from Keycloak."""
        from urllib.parse import urlencode

        session = await self._c._get_session()
        # Must be sent as application/x-www-form-urlencoded, aiohttp's data=dict
        # sends multipart/form-data which Keycloak rejects with 401.
        payload = urlencode(
            {
                "username": username,
                "password": password,
                "client_id": "legacy-desktop-app",
                "grant_type": "password",
                "code": "",
                "redirect_uri": "",
                "scope": "openid",
            }
        ).encode("utf-8")
        async with session.post(
            OIDC_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as resp:
            resp.raise_for_status()
            result: OIDCTokenResponse = await resp.json(content_type=None)
            return result

    async def authenticate(self, access_token: str) -> UserInfo:
        """Step 2: Exchange OIDC token for TSM session + user info."""
        result: UserInfo = await self._c.api_request("auth", data={"token": access_token})
        self._c.set_user_info(result)
        return result

    async def login(self, username: str, password: str) -> UserInfo:
        """Full login: OIDC → TSM session."""
        oidc = await self.get_oidc_token(username, password)
        return await self.authenticate(oidc["access_token"])


class StatusAPI:
    def __init__(self, client: TSMApiClient):
        self._c = client

    async def get(self, channel: str = "release", tsm_version: str = "") -> StatusResponse:
        """Fetch status including realm/region lists with appDataStrings URLs."""
        result: StatusResponse = await self._c.api_request(
            "status", channel=channel, tsm_version=tsm_version
        )
        return result


class AddonAPI:
    def __init__(self, client: TSMApiClient):
        self._c = client

    async def download(self, name: str, channel: str = "release") -> bytes:
        """Download an addon zip.

        ``name`` carries the game-version suffix ("", "-Classic", "-Progression",
        "-Anniversary"); the server resolves it to the package for that client.

        The endpoint takes no ``tsm_version`` parameter. The original Windows
        client sends ``tsm_version`` only on /v2/status, where it carries the
        installed TradeSkillMaster addon version (AppAPI.py:171 vs :175).
        """
        result = await self._c.api_request("addon", name, channel=channel)
        if isinstance(result, bytes):
            return result
        if isinstance(result, dict):
            # The endpoint has answered with a JSON {"url": ...} CDN redirect in
            # the past instead of the zip bytes; follow it when it does.
            url = (
                result.get("url")
                or result.get("download_url")
                or result.get("downloadUrl")
                or result.get("zip_url")
                or result.get("zipUrl")
            )
            if not url:
                raise ValueError(f"Addon download returned JSON with no URL: {result}")
            return await self._c.fetch_bytes(url)
        raise TypeError(f"Unexpected addon download response type: {type(result).__name__}")

    async def get_status(self, channel: str = "release", tsm_version: str = "") -> StatusResponse:
        """Get status response (includes addon versions and realm data URLs)."""
        result: StatusResponse = await self._c.api_request(
            "status", channel=channel, tsm_version=tsm_version
        )
        return result


class RealmsAPI:
    def __init__(self, client: TSMApiClient):
        self._c = client

    async def list(self) -> dict[str, list[RealmEntry]]:
        result: dict[str, list[RealmEntry]] = await self._c.api_request("realms2", "list")
        return result

    async def add(self, game_version: str, realm_id: int) -> dict[str, object]:
        result: dict[str, object] = await self._c.api_request(
            "realms2", "add", game_version, str(realm_id)
        )
        return result

    async def remove(self, game_version: str, region: str, realm: str) -> dict[str, object]:
        result: dict[str, object] = await self._c.api_request(
            "realms2", "remove", game_version, region, realm
        )
        return result
