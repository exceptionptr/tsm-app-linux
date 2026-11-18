"""AppVersion against a local server standing in for the update feed."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import aiohttp
import pytest_asyncio
from aiohttp import web

import tsm.api.app_version as mod
from tsm.api.app_version import AppVersion, load_staging_id
from tsm.api.http import OrderedRequest
from tsm.api.official import OFFICIAL_APP_VERSION, UA_CHROMIUM


class Feed:
    def __init__(self) -> None:
        self.body = "version: 1.0.15\nfiles:\n  - url: x\n"
        self.status = 200
        self.delay = 0.0
        self.seen: list[dict[str, Any]] = []


@pytest_asyncio.fixture
async def feed() -> AsyncIterator[tuple[str, Feed]]:
    state = Feed()

    async def handler(request: web.Request) -> web.Response:
        state.seen.append(
            {
                "raw": [(k.decode(), v.decode()) for k, v in request.raw_headers],
                "query": request.query_string,
            }
        )
        if state.delay:
            await asyncio.sleep(state.delay)
        return web.Response(status=state.status, text=state.body)

    app = web.Application()
    app.router.add_get("/latest-linux.yml", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    port = runner.addresses[0][1]
    yield f"http://127.0.0.1:{port}/latest-linux.yml", state
    await runner.cleanup()


@pytest_asyncio.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession(request_class=OrderedRequest) as s:
        yield s


def _av(tmp_path: Path, url: str) -> AppVersion:
    return AppVersion(tmp_path / ".updaterId", url)


async def test_default_until_answered(tmp_path: Path) -> None:
    av = _av(tmp_path, "http://x")
    assert av.version == OFFICIAL_APP_VERSION
    assert not av.from_feed
    assert av.chromium_user_agent() == UA_CHROMIUM


async def test_newer_version_taken(
    tmp_path: Path, feed: tuple[str, Feed], session: aiohttp.ClientSession
) -> None:
    url, _ = feed
    av = _av(tmp_path, url)
    await av.check(session)
    assert av.version == "1.0.15"
    assert av.from_feed
    assert "TradeSkillMaster/1.0.15 " in av.chromium_user_agent()


async def test_older_version_also_taken(
    tmp_path: Path, feed: tuple[str, Feed], session: aiohttp.ClientSession
) -> None:
    url, state = feed
    state.body = "version: 0.9.1\n"
    av = _av(tmp_path, url)
    await av.check(session)
    assert av.version == "0.9.1"


async def test_garbage_keeps_value(
    tmp_path: Path, feed: tuple[str, Feed], session: aiohttp.ClientSession
) -> None:
    url, state = feed
    av = _av(tmp_path, url)
    for body in ("hello", "version: 1.0\n", "version: 1.0.x\n", "version: 1.0.14-beta\n"):
        state.body = body
        await av.check(session)
        assert av.version == OFFICIAL_APP_VERSION
        assert not av.from_feed


async def test_server_error_keeps_value(
    tmp_path: Path, feed: tuple[str, Feed], session: aiohttp.ClientSession
) -> None:
    url, state = feed
    av = _av(tmp_path, url)
    await av.check(session)
    state.status = 500
    state.body = "version: 2.0.0\n"
    await av.check(session)
    assert av.version == "1.0.15"


async def test_timeout_keeps_value(
    tmp_path: Path,
    feed: tuple[str, Feed],
    session: aiohttp.ClientSession,
    monkeypatch: Any,
) -> None:
    url, state = feed
    monkeypatch.setattr(mod, "CHECK_TIMEOUT", 0.2)
    state.delay = 1.0
    av = _av(tmp_path, url)
    await av.check(session)
    assert av.version == OFFICIAL_APP_VERSION
    assert not av.from_feed


async def test_header_order_and_bearer(
    tmp_path: Path, feed: tuple[str, Feed], session: aiohttp.ClientSession
) -> None:
    url, state = feed
    av = _av(tmp_path, url)
    await av.check(session, "tok")
    await av.check(session)
    with_token, anonymous = state.seen
    names = [k for k, _ in with_token["raw"]]
    assert names == [
        "Host",
        "x-user-staging-id",
        "authorization",
        "user-agent",
        "cache-control",
        "sec-fetch-site",
        "sec-fetch-mode",
        "sec-fetch-dest",
        "accept-encoding",
        "accept-language",
        "priority",
    ]
    values = dict(with_token["raw"])
    assert values["authorization"] == "Bearer tok"
    assert values["user-agent"] == "electron-builder"
    assert values["cache-control"] == "no-cache"
    assert "authorization" not in [k for k, _ in anonymous["raw"]]
    assert with_token["query"].startswith("noCache=")
    assert len(with_token["query"]) == len("noCache=") + 9


async def test_staging_id_persists(
    tmp_path: Path, feed: tuple[str, Feed], session: aiohttp.ClientSession
) -> None:
    url, state = feed
    await _av(tmp_path, url).check(session)
    await _av(tmp_path, url).check(session)
    ids = [dict(s["raw"])["x-user-staging-id"] for s in state.seen]
    assert ids[0] == ids[1]
    assert str(uuid.UUID(ids[0], version=4)) == ids[0]
    assert (tmp_path / ".updaterId").read_text().strip() == ids[0]


def test_invalid_staging_id_replaced(tmp_path: Path) -> None:
    p = tmp_path / ".updaterId"
    p.write_text("not-a-uuid")
    new = load_staging_id(p)
    assert str(uuid.UUID(new)) == new
    assert load_staging_id(p) == new


async def test_check_during_check_is_queued_once(
    tmp_path: Path, feed: tuple[str, Feed], session: aiohttp.ClientSession
) -> None:
    url, state = feed
    state.delay = 0.2
    av = _av(tmp_path, url)
    await asyncio.gather(*(av.check(session) for _ in range(4)))
    assert len(state.seen) == 2


def test_parse_version_accepts_only_ascii_digits() -> None:
    from tsm.api.app_version import parse_version

    assert parse_version("version: 1.0.15\n") == "1.0.15"
    assert parse_version("version: 10.20.300\n") == "10.20.300"
    # Arabic-indic digits are \d in str patterns but are not a version.
    assert parse_version("version: ١.٠.١٤\n") is None
