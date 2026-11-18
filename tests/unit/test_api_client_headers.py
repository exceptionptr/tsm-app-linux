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
from tsm.api import oidc
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
                "raw": [(k.decode(), v.decode()) for k, v in request.raw_headers],
                "raw_path": request.raw_path,
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


def _names(raw: list[tuple[str, str]]) -> list[str]:
    return [k for k, _ in raw]


def _lower(raw: list[tuple[str, str]]) -> dict[str, str]:
    return {k.lower(): v for k, v in raw}


def _check_no_sentry(raw: list[tuple[str, str]]) -> None:
    assert not {"sentry-trace", "baggage"} & set(_lower(raw))


def _node_fetch_order(*, body: bool, token: bool = True) -> list[str]:
    names = ["Accept", "Accept-Encoding"]
    if token:
        names.append("Authorization")
    if body:
        names += ["Content-Length", "Content-Type"]
    return [*names, "User-Agent", "Host", "Connection"]


def _undici_order(*, body: bool, token: bool, content_type: bool = False) -> list[str]:
    names = ["host", "connection"]
    if token:
        names.append("Authorization")
    if content_type:
        names.append("content-type")
    names += ["accept", "accept-language", "sec-fetch-mode", "user-agent", "accept-encoding"]
    if body:
        names.append("content-length")
    return names


def _check_node_fetch(
    raw: list[tuple[str, str]], *, body: bool = False, token: bool = True
) -> None:
    assert _names(raw) == _node_fetch_order(body=body, token=token)
    h = _lower(raw)
    assert h["user-agent"] == "node-fetch"
    assert h["accept"] == "*/*"
    assert h["accept-encoding"] == NODE_FETCH_AE
    assert h["connection"] == "keep-alive"
    if token:
        assert h["authorization"] == "Bearer tok"
    _check_no_sentry(raw)


def _check_undici(
    raw: list[tuple[str, str]],
    *,
    body: bool = False,
    token: bool = False,
    content_type: bool = False,
) -> None:
    assert _names(raw) == _undici_order(body=body, token=token, content_type=content_type)
    h = _lower(raw)
    assert h["user-agent"] == "node"
    assert h["accept"] == "*/*"
    assert h["accept-language"] == "*"
    assert h["sec-fetch-mode"] == "cors"
    assert h["accept-encoding"] == UNDICI_AE
    assert h["connection"] == "keep-alive"
    _check_no_sentry(raw)


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
    for s in rec.seen[:4]:
        _check_node_fetch(s["raw"])
    # DELETE has no body: node-fetch sends no Content-Length for it.
    _check_node_fetch(rec.seen[4]["raw"])


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
        _check_node_fetch(s["raw"], body=True)
        assert _lower(s["raw"])["content-type"] == "application/json"
        assert _lower(s["raw"])["content-length"] == str(len(s["body"]))


async def test_machine_names_use_undici(server, monkeypatch):
    base, rec = server
    c = await _client(monkeypatch, base)
    await c.local_machine_names(["a", "b"])
    await c.set_local_machine_name("a", "Box")
    await c.close()
    get, post = rec.seen
    assert get["query"] == {"systemIds": "a,b"}
    assert json.loads(post["body"]) == {"systemId": "a", "localMachineName": "Box"}
    _check_undici(get["raw"], token=True)
    _check_undici(post["raw"], body=True, token=True, content_type=True)
    assert _lower(post["raw"])["content-type"] == "application/json"
    assert _lower(get["raw"])["authorization"] == "Bearer tok"


async def test_presigned_download_has_no_auth_and_no_range(server, monkeypatch):
    base, rec = server
    c = TSMApiClient()
    assert await c.download(f"{base}/blob/x?verify=abc") == b"{x=1}"
    await c.close()
    (s,) = rec.seen
    _check_undici(s["raw"])
    assert "range" not in _lower(s["raw"])
    assert s["query"] == {"verify": "abc"}


async def test_presigned_download_url_goes_out_byte_for_byte(server):
    base, rec = server
    c = TSMApiClient()
    query = "verify=a%2Bb%2Fc%3D%3D&X-Amz-Signature=AbC%2fdE=&t=1"
    await c.download(f"{base}/blob/x?{query}")
    await c.close()
    (s,) = rec.seen
    assert s["raw_path"] == f"/blob/x?{query}"


async def test_revoke_goes_out_in_undici_order(server, monkeypatch):
    base, rec = server
    monkeypatch.setattr(oidc, "AUTH_BASE", base)
    c = TSMApiClient()
    await oidc.revoke(await c.session(), "r-old")
    await c.close()
    (s,) = rec.seen
    _check_undici(s["raw"], body=True, content_type=True)
    assert _lower(s["raw"])["content-type"] == "application/x-www-form-urlencoded;charset=UTF-8"


async def test_addon_zip_download_uses_node_fetch_without_auth(server):
    base, rec = server
    c = TSMApiClient()
    await c.download_addon_zip(f"{base}/blob/zip")
    await c.close()
    (s,) = rec.seen
    _check_node_fetch(s["raw"], token=False)
    assert "range" not in _lower(s["raw"])


def test_br_is_not_advertised_without_decoder(monkeypatch):
    monkeypatch.setattr(mod, "HAS_BROTLI", False)
    assert mod.node_fetch_headers()["Accept-Encoding"] == "gzip, deflate"
    assert mod.undici_headers()["accept-encoding"] == "gzip, deflate"


async def test_download_tls_context_follows_the_channel(server, monkeypatch):
    base, _rec = server
    seen: list[Any] = []
    orig = mod.aiohttp.ClientSession.get

    def spy(self, url, **kwargs):
        seen.append(kwargs["ssl"])
        return orig(self, url, **kwargs)

    monkeypatch.setattr(mod.aiohttp.ClientSession, "get", spy)
    c = TSMApiClient()
    await c.download(f"{base}/blob/x")
    await c.download_addon_zip(f"{base}/blob/zip")
    await c.close()
    assert seen == [mod.UNDICI_SSL, mod.NODE_SSL]
