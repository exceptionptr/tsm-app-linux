"""Socket.IO v4 client against a local websocket server speaking the protocol."""

from __future__ import annotations

import asyncio
import json

import aiohttp
import pytest
from aiohttp import web

from tsm.api import socket as sock
from tsm.api.socket import TSMSocket, backoff_delay, parse_packet


def test_parse_packets():
    assert parse_packet('0{"sid":"x","pingInterval":1}')[0] == "open"
    assert parse_packet("2") == ("ping", None)
    assert parse_packet('40{"sid":"y"}') == ("connect", {"sid": "y"})
    assert parse_packet("41") == ("disconnect", None)
    assert parse_packet('44{"message":"no"}') == ("connect_error", {"message": "no"})
    assert parse_packet('42["app_info",{"a":1}]') == ("event", ("app_info", {"a": 1}))
    assert parse_packet('4217["x",2]') == ("event", ("x", 2))
    assert parse_packet("")[0] == "unknown"


def test_backoff_grows_and_caps():
    assert 2.5 <= backoff_delay(0, 60) <= 7.5
    assert backoff_delay(10, 60, jitter=0) == 60
    assert backoff_delay(10, 300, jitter=0) == 300


async def _server(handler):
    app = web.Application()
    app.router.add_get("/socket.io/", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    return runner, f"ws://127.0.0.1:{port}/socket.io/?EIO=4&transport=websocket"


@pytest.mark.asyncio
async def test_handshake_ping_and_events():
    seen_auth: list[str] = []
    got_pong = asyncio.Event()
    done = asyncio.Event()

    async def handler(request):
        seen_auth.append(request.headers.get("Authorization", ""))
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_str('0{"sid":"s","upgrades":[],"pingInterval":25000,"pingTimeout":20000}')
        assert (await ws.receive_str()) == "40"
        await ws.send_str('40{"sid":"n"}')
        await ws.send_str("2")
        assert (await ws.receive_str()) == "3"
        got_pong.set()
        await ws.send_str("42" + json.dumps(["realm_auctiondb", {"realmId": 300}]))
        await asyncio.wait_for(done.wait(), 5)
        return ws

    runner, url = await _server(handler)
    events: list[tuple[str, object]] = []
    states: list[bool] = []
    session = aiohttp.ClientSession()

    async def get_session():
        return session

    async def token():
        return "raw-token"

    s = TSMSocket(get_session, token, lambda n, p: events.append((n, p)), states.append, url=url)
    try:
        s.start()
        for _ in range(100):
            if events:
                break
            await asyncio.sleep(0.02)
        assert got_pong.is_set()
        assert events == [("realm_auctiondb", {"realmId": 300})]
        assert states == [True]
        assert s.connected
        assert seen_auth == ["raw-token"]  # no "Bearer " prefix
    finally:
        done.set()
        await s.stop()
        await session.close()
        await runner.cleanup()
    assert states == [True, False]


@pytest.mark.asyncio
async def test_server_disconnect_backs_off_and_reconnect_skips_the_wait(monkeypatch):
    connects = 0

    async def handler(request):
        nonlocal connects
        connects += 1
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_str('0{"sid":"s","pingInterval":25000,"pingTimeout":20000}')
        await ws.receive_str()
        await ws.send_str('44{"message":"Unauthorized"}')
        return ws

    monkeypatch.setattr(sock, "backoff_delay", lambda *_a, **_k: 60.0)
    runner, url = await _server(handler)
    session = aiohttp.ClientSession()

    async def get_session():
        return session

    async def token():
        return "t"

    s = TSMSocket(get_session, token, lambda *_: None, url=url)
    try:
        s.start()
        for _ in range(100):
            if connects == 1:
                break
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.1)
        assert connects == 1  # waiting out the 60 s backoff
        await s.reconnect()
        for _ in range(100):
            if connects == 2:
                break
            await asyncio.sleep(0.02)
        assert connects == 2
    finally:
        await s.stop()
        await session.close()
        await runner.cleanup()
