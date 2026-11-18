"""The official client version, read from the public update feed.

The official client asks desktop-backend for ``latest-linux.yml`` (electron-updater,
generic provider) at start, on every socket connect and after an ``app_update``
event, and reports the version it finds. This app does the same and reports the
feed's version 1:1 wherever a version is sent. Nothing is ever downloaded.

The built-in version is used until the feed has answered successfully in this run.
The request goes out over aiohttp (HTTP/1.1) with the electron-updater header set in
the captured order; the official client uses Chromium's network stack over h2.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from pathlib import Path

import aiohttp
from aiohttp import compression_utils
from aiohttp.compression_utils import HAS_BROTLI

from tsm.api.http import AUTO
from tsm.api.official import OFFICIAL_APP_VERSION, chromium_user_agent_for

logger = logging.getLogger(__name__)

FEED_URL = "https://desktop-backend.tradeskillmaster.com/app-updates/release/latest-linux.yml"
UA_UPDATER = "electron-builder"
CHECK_TIMEOUT = 3.0

_VERSION_LINE = re.compile(
    r"^version:\s*['\"]?([0-9]+\.[0-9]+\.[0-9]+)['\"]?\s*$", re.MULTILINE | re.ASCII
)
_BASE32 = "0123456789abcdefghijklmnopqrstuv"


def _base32(n: int) -> str:
    """``Date.now().toString(32)``."""
    if n == 0:
        return "0"
    digits = []
    while n:
        n, r = divmod(n, 32)
        digits.append(_BASE32[r])
    return "".join(reversed(digits))


def parse_version(text: str) -> str | None:
    """The ``version:`` of a latest-linux.yml, only when it is a plain X.Y.Z."""
    m = _VERSION_LINE.search(text)
    return m.group(1) if m else None


def load_staging_id(path: Path) -> str:
    """The per-install staging id (electron-updater ``.updaterId``): reuse or recreate."""
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if str(uuid.UUID(existing)) == existing.lower():
            return existing
    except (OSError, ValueError):
        pass
    new = str(uuid.uuid4())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new, encoding="utf-8")
    except OSError:
        logger.warning("app_version: cannot persist the staging id", exc_info=True)
    return new


def updater_headers(staging_id: str, token: str | None) -> dict[str, str]:
    """electron-updater headers in captured order (Chromium net, lower case)."""
    headers = {"Host": AUTO, "x-user-staging-id": staging_id}
    if token is not None:
        headers["authorization"] = "Bearer " + token
    encodings = ["gzip", "deflate"]
    if HAS_BROTLI:
        encodings.append("br")
    if getattr(compression_utils, "HAS_ZSTD", False):
        encodings.append("zstd")
    accept_encoding = ", ".join(encodings)
    headers.update(
        {
            "user-agent": UA_UPDATER,
            "cache-control": "no-cache",
            "sec-fetch-site": "none",
            "sec-fetch-mode": "no-cors",
            "sec-fetch-dest": "empty",
            "accept-encoding": accept_encoding,
            "accept-language": "en-US",
            "priority": "u=4, i",
        }
    )
    return headers


class AppVersion:
    """Current official version: built-in until the feed has answered."""

    def __init__(self, updater_id_path: Path, feed_url: str = FEED_URL) -> None:
        self._id_path = updater_id_path
        self._feed_url = feed_url
        self._version = OFFICIAL_APP_VERSION
        self._from_feed = False
        self._staging_id: str | None = None
        self._running = False
        self._queued: tuple[aiohttp.ClientSession, str | None] | None = None

    @property
    def version(self) -> str:
        return self._version

    @property
    def from_feed(self) -> bool:
        return self._from_feed

    def chromium_user_agent(self) -> str:
        return chromium_user_agent_for(self._version)

    async def check(self, session: aiohttp.ClientSession, token: str | None = None) -> None:
        """Ask the feed. A check that starts while one runs is queued once."""
        if self._running:
            self._queued = (session, token)
            return
        self._running = True
        try:
            nxt: tuple[aiohttp.ClientSession, str | None] | None = (session, token)
            while nxt is not None:
                self._queued = None
                await self._fetch(*nxt)
                nxt = self._queued
        finally:
            self._running = False

    async def _fetch(self, session: aiohttp.ClientSession, token: str | None) -> None:
        if self._staging_id is None:
            self._staging_id = load_staging_id(self._id_path)
        url = f"{self._feed_url}?noCache={_base32(int(time.time() * 1000))}"
        headers = updater_headers(self._staging_id, token)
        try:
            timeout = aiohttp.ClientTimeout(total=CHECK_TIMEOUT)
            async with session.get(url, headers=headers, timeout=timeout) as resp:
                if resp.status != 200:
                    logger.warning("app_version: feed answered HTTP %d", resp.status)
                    return
                text = await resp.text()
        except (aiohttp.ClientError, TimeoutError, UnicodeError):
            logger.warning("app_version: feed not reachable", exc_info=True)
            return
        version = parse_version(text)
        if version is None:
            logger.warning("app_version: feed has no well-formed version")
            return
        if version != self._version:
            logger.info("app_version: %s -> %s (feed)", self._version, version)
        self._version = version
        self._from_feed = True
