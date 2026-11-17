"""Headers and bodies TSMApiClient sends per channel, seen by a real local server."""

from __future__ import annotations

import gzip
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.compression_utils import HAS_BROTLI

import tsm.api.client as mod
from tsm.api.client import TSMApiClient

NODE_FETCH_AE = "gzip, deflate, br" if HAS_BROTLI else "gzip, deflate"
UNDICI_AE = "br, gzip, deflate" if HAS_BROTLI else "gzip, deflate"


class Recorder:
    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []


@pytest_asyncio.fixture
async def server() -> AsyncIterator[tuple[str, Recorder]]:
    rec = Recorder()

    async def handler(request: web.Request) -> web.Response:
        body = await request.read()
        rec.seen.append(
            {
                "method": request.method,
                "path": request.path,
                "query": dict(request.query),
                "headers": dict(request.headers),
                "body": body,
            }
        )
        if request.path.startswith("/blob"):
            return web.Response(body=gzip.compress(b"{x=1}"))
        return web.json_response([])

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    yield f"http://127.0.0.1:{port}", rec
    await runner.cleanup()


async def _client(monkeypatch: pytest.MonkeyPatch, base: str) -> TSMApiClient:
    for name in ("REALM_API", "DESKTOP_BACKEND", "ADDON_VERSION_API"):
        monkeypatch.setattr(mod, name, base)
    c = TSMApiClient()

    async def token() -> str:
        return "tok"

    c.set_token_provider(token)
    return c


def _check_node_fetch(h: dict[str, str]) -> None:
    assert h["User-Agent"] == "node-fetch"
    assert h["Accept"] == "*/*"
    assert h["Accept-Encoding"] == NODE_FETCH_AE
    assert h["Authorization"] == "Bearer tok"
    assert "Accept-Language" not in h
    assert "Sec-Fetch-Mode" not in h


def _check_undici(h: dict[str, str]) -> None:
    assert h["User-Agent"] == "node"
    assert h["Accept"] == "*/*"
    assert h["Accept-Language"] == "*"
    assert h["Sec-Fetch-Mode"] == "cors"
    assert h["Accept-Encoding"] == UNDICI_AE


async def test_rest_get_channels_use_node_fetch(server, monkeypatch):
    base, rec = server
    c = await _client(monkeypatch, base)
    await c.game_versions()
    await c.user_realms("u1")
    await c.release_channel_labels()
    await c.remote_backups()
    await c.delete_user_realm("abc")
    await c.close()
    assert [s["path"] for s in rec.seen] == [
        "/game-versions",
        "/user-realms",
        "/channels",
        "/backups",
        "/user-realms/abc",
    ]
    assert rec.seen[1]["query"] == {"userIds": "u1"}
    for s in rec.seen:
        _check_node_fetch(s["headers"])
        assert "Content-Type" not in s["headers"]


async def test_post_user_realms_body_and_content_headers(server, monkeypatch):
    base, rec = server
    c = await _client(monkeypatch, base)
    await c.add_user_realm("u1", 138, "all")
    await c.claim_group_sends(["forever", "retail"])
    await c.close()
    follow, claim = rec.seen
    assert follow["method"] == "POST" and follow["path"] == "/user-realms"
    assert follow["body"] == b'{"realmId": 138, "userId": "u1", "auctionHouseType": "ALL"}'
    assert list(json.loads(follow["body"])) == ["realmId", "userId", "auctionHouseType"]
    assert claim["path"] == "/group-sends/claim"
    assert json.loads(claim["body"]) == {"gameTypes": ["forever", "retail"]}
    for s in (follow, claim):
        _check_node_fetch(s["headers"])
        assert s["headers"]["Content-Type"] == "application/json"
        assert s["headers"]["Content-Length"] == str(len(s["body"]))


async def test_machine_names_use_undici(server, monkeypatch):
    base, rec = server
    c = await _client(monkeypatch, base)
    await c.local_machine_names(["a", "b"])
    await c.set_local_machine_name("a", "Box")
    await c.close()
    get, post = rec.seen
    assert get["query"] == {"systemIds": "a,b"}
    assert json.loads(post["body"]) == {"systemId": "a", "localMachineName": "Box"}
    for s in (get, post):
        _check_undici(s["headers"])
        assert s["headers"]["Authorization"] == "Bearer tok"


async def test_presigned_download_has_no_auth_and_no_range(server, monkeypatch):
    base, rec = server
    c = TSMApiClient()
    assert await c.download(f"{base}/blob/x?verify=abc") == b"{x=1}"
    await c.close()
    (s,) = rec.seen
    _check_undici(s["headers"])
    assert "Authorization" not in s["headers"]
    assert "Range" not in s["headers"]
    assert s["query"] == {"verify": "abc"}


async def test_addon_zip_download_uses_node_fetch_without_auth(server):
    base, rec = server
    c = TSMApiClient()
    await c.download_addon_zip(f"{base}/blob/zip")
    await c.close()
    (s,) = rec.seen
    assert s["headers"]["User-Agent"] == "node-fetch"
    assert s["headers"]["Accept-Encoding"] == NODE_FETCH_AE
    assert "Authorization" not in s["headers"]
    assert "Range" not in s["headers"]


def test_br_is_not_advertised_without_decoder(monkeypatch):
    monkeypatch.setattr(mod, "HAS_BROTLI", False)
    assert mod.node_fetch_headers()["Accept-Encoding"] == "gzip, deflate"
    assert mod.undici_headers()["Accept-Encoding"] == "gzip, deflate"
