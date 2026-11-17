"""Socket.IO v4 client against a fake Engine.IO server (polling open, upgrade, ping/pong)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import aiohttp
import pytest
from aiohttp import web

from tsm.api import socket as sock
from tsm.api.official import OFFICIAL_APP_VERSION, UA_CHROMIUM, UA_XHR
from tsm.api.socket import TSMSocket, backoff_delay, parse_packet, yeast


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


def test_yeast_is_unique_per_call():
    ids = {yeast() for _ in range(50)}
    assert len(ids) == 50


class FakeEngineIO:
    """Engine.IO v4 server: polling open, namespace connect, optional websocket upgrade."""

    def __init__(
        self,
        upgrades: list[str],
        after_connect: list[str],
        ws_ok: bool = True,
        ws_script: Any = None,
        refuse: bool = False,
        affinity: bool = False,
    ) -> None:
        self.upgrades = upgrades
        self.after_connect = after_connect
        self.ws_ok = ws_ok
        self.ws_script = ws_script
        self.refuse = refuse
        # Like a load balancer with session affinity: the open response sets a cookie
        # and every later request without it is answered HTTP 400.
        self.affinity = affinity
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.requests: list[tuple[str, str, dict[str, str], str]] = []
        self.posts: list[str] = []
        self.peers: list[int] = []  # client port of every polling GET/POST
        self.ws_frames: list[str] = []
        self.connects = 0
        self.open_gets = 0
        self.gets_open_at_5: int | None = None
        self.runner: web.AppRunner | None = None
        self.url = ""

    async def handler(self, request: web.Request) -> web.StreamResponse:
        q = request.query
        headers = dict(request.headers)
        if self.affinity and "sid" in q and request.cookies.get("lb") != "node1":
            return web.Response(
                status=400, text='{"code":1,"message":"Session ID unknown"}',
                content_type="application/json",
            )
        if q["transport"] == "websocket":
            self.requests.append(("WS", request.query_string, headers, ""))
            if not self.ws_ok:
                return web.Response(status=400)
            return await self._websocket(request)
        if request.method == "POST":
            body = await request.text()
            self.requests.append(("POST", request.query_string, headers, body))
            self.peers.append(request.transport.get_extra_info("peername")[1])  # type: ignore[union-attr,index]
            self.posts.append(body)
            if body == "1":
                return web.Response(text="ok")
            if body == "40":
                reply = '44{"message":"Unauthorized"}' if self.refuse else "40" + RS_JOIN
                self.queue.put_nowait(reply)
            return web.Response(text="ok")
        self.requests.append(("GET", request.query_string, headers, ""))
        self.peers.append(request.transport.get_extra_info("peername")[1])  # type: ignore[union-attr,index]
        if "sid" not in q:
            self.connects += 1
            info = {
                "sid": "sid1",
                "upgrades": self.upgrades,
                "pingInterval": 25000,
                "pingTimeout": 20000,
                "maxPayload": 1000000,
            }
            resp = web.Response(text="0" + json.dumps(info))
            if self.affinity:
                resp.set_cookie("lb", "node1")
            return resp
        self.open_gets += 1
        try:
            return web.Response(text=await self.queue.get())
        finally:
            self.open_gets -= 1

    async def _websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.ws_frames.append(await ws.receive_str())  # 2probe
        await ws.send_str("3probe")
        self.queue.put_nowait("6")  # flushes the pending poll like engine.io
        self.ws_frames.append(await ws.receive_str())  # 5
        self.gets_open_at_5 = self.open_gets
        if self.ws_script is not None:
            await self.ws_script(ws, self)
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                self.ws_frames.append(msg.data)
        return ws

    async def start(self) -> None:
        app = web.Application()
        app.router.add_route("*", "/socket.io/", self.handler)
        self.runner = web.AppRunner(app, handler_cancellation=True)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        self.url = f"http://127.0.0.1:{port}/socket.io/"

    async def stop(self) -> None:
        if self.runner is not None:
            await self.runner.cleanup()


RS_JOIN = "\x1e".join(
    [
        '{"sid":"n","pid":"p"}',
        '42["app_info",{"a":1}]',
        '42["realm_auctiondb",{"realmId":300}]',
    ]
)


async def _until(cond, tries=150):
    for _ in range(tries):
        if cond():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached")


async def _run_socket(server: FakeEngineIO, token_value: str = "raw-token"):
    events: list[tuple[str, object]] = []
    states: list[bool] = []
    # unsafe=True: the fake server listens on an IP, where aiohttp stores no cookies otherwise.
    session = aiohttp.ClientSession(
        headers={"User-Agent": "node-fetch"}, cookie_jar=aiohttp.CookieJar(unsafe=True)
    )

    async def get_session():
        return session

    async def token():
        return token_value

    s = TSMSocket(
        get_session, token, lambda n, p: events.append((n, p)), states.append, url=server.url
    )
    return s, session, events, states


@pytest.mark.asyncio
async def test_polling_open_connect_first_body_events_and_upgrade():
    async def script(ws, server):
        await ws.send_str("2")
        await ws.send_str("42" + json.dumps(["region_auctiondb", {"regionId": 1}]))

    server = FakeEngineIO(["websocket"], [], ws_script=script)
    await server.start()
    s, session, events, states = await _run_socket(server)
    try:
        s.start()
        await _until(lambda: ("region_auctiondb", {"regionId": 1}) in events)
        await _until(lambda: "3" in server.ws_frames)
        # Packets of the first polling body are all delivered, in order.
        assert events[:2] == [("app_info", {"a": 1}), ("realm_auctiondb", {"realmId": 300})]
        assert states == [True]
        assert s.connected
        # Upgrade sequence on the websocket, then the pong.
        assert server.ws_frames == ["2probe", "5", "3"]
        assert server.gets_open_at_5 == 0  # polling is paused when "5" goes out
        kinds = [r[0] for r in server.requests]
        assert kinds[:2] == ["GET", "POST"]
        assert "WS" in kinds
        # Open request: no sid, EIO 4, polling, timestamp id, official headers.
        _, query, headers, _ = server.requests[0]
        assert query.startswith("EIO=4&transport=polling&t=")
        assert "sid=" not in query
        assert headers["User-Agent"] == UA_XHR
        assert headers["Accept"] == "*/*"
        assert headers["Authorization"] == "raw-token"  # no "Bearer "
        assert headers.get("Connection", "").lower() != "close"
        # Official XHR polling sends no Accept-Encoding (GET and POST alike).
        for req in server.requests:
            if req[0] in ("GET", "POST"):
                assert "accept-encoding" not in {k.lower() for k in req[2]}
        # Namespace connect: body 40, sid after t, text/plain.
        _, query, headers, body = server.requests[1]
        assert body == "40"
        assert query.split("&")[:2] == ["EIO=4", "transport=polling"]
        assert query.endswith("&sid=sid1")
        assert headers["Content-Type"].startswith("text/plain")
        assert headers["User-Agent"] == UA_XHR
        assert headers["Authorization"] == "raw-token"
        # Websocket handshake: sid and the raw token.
        ws_req = next(r for r in server.requests if r[0] == "WS")
        assert ws_req[1] == "EIO=4&transport=websocket&sid=sid1"
        assert ws_req[2]["Authorization"] == "raw-token"
    finally:
        await s.stop()
        await session.close()
        await server.stop()
    assert states == [True, False]


@pytest.mark.asyncio
async def test_stays_on_polling_without_upgrade_and_answers_ping_by_post():
    server = FakeEngineIO([], [])
    await server.start()
    s, session, events, _ = await _run_socket(server)
    try:
        s.start()
        await _until(lambda: len(events) == 2)
        server.queue.put_nowait("2")
        await _until(lambda: "3" in server.posts)
        server.queue.put_nowait("42" + json.dumps(["app_info", {"b": 2}]))
        await _until(lambda: ("app_info", {"b": 2}) in events)
        assert not any(r[0] == "WS" for r in server.requests)
    finally:
        await s.stop()
        await session.close()
        await server.stop()


@pytest.mark.asyncio
async def test_polling_phase_uses_one_connection():
    server = FakeEngineIO([], [])
    await server.start()
    s, session, events, _ = await _run_socket(server)
    try:
        s.start()
        await _until(lambda: len(events) == 2)
        server.queue.put_nowait("2")
        await _until(lambda: "3" in server.posts)
        server.queue.put_nowait("42" + json.dumps(["app_info", {"b": 2}]))
        await _until(lambda: ("app_info", {"b": 2}) in events)
        await _until(lambda: server.open_gets == 1)
        # open GET, POST 40, polls and the pong POST all share one TCP connection.
        assert len(server.peers) >= 5
        assert len(set(server.peers)) == 1
    finally:
        await s.stop()
        await session.close()
        await server.stop()


@pytest.mark.asyncio
async def test_failed_upgrade_falls_back_to_polling():
    server = FakeEngineIO(["websocket"], [], ws_ok=False)
    await server.start()
    s, session, events, _ = await _run_socket(server)
    try:
        s.start()
        await _until(lambda: len(events) == 2)
        await _until(lambda: any(r[0] == "WS" for r in server.requests))
        await asyncio.sleep(0.1)
        server.queue.put_nowait("42" + json.dumps(["app_info", {"c": 3}]))
        await _until(lambda: ("app_info", {"c": 3}) in events)
        assert s.connected
        assert server.connects == 1  # no reconnect needed
    finally:
        await s.stop()
        await session.close()
        await server.stop()


@pytest.mark.asyncio
async def test_server_disconnect_backs_off_and_reconnect_skips_the_wait(monkeypatch):
    server = FakeEngineIO(["websocket"], [], refuse=True)
    monkeypatch.setattr(sock, "backoff_delay", lambda *_a, **_k: 60.0)
    await server.start()
    s, session, _, states = await _run_socket(server, "t")
    try:
        s.start()
        await _until(lambda: server.connects == 1)
        await asyncio.sleep(0.2)
        assert server.connects == 1  # waiting out the 60 s backoff
        assert states == []
        await s.reconnect()
        await _until(lambda: server.connects == 2)
    finally:
        await s.stop()
        await session.close()
        await server.stop()


def test_official_identity():
    assert OFFICIAL_APP_VERSION == "1.0.14"
    assert "TradeSkillMaster/1.0.14" in UA_CHROMIUM


@pytest.mark.asyncio
async def test_reconnect_while_on_polling_opens_a_new_connection(monkeypatch):
    monkeypatch.setattr(sock, "backoff_delay", lambda *_a, **_k: 60.0)
    server = FakeEngineIO([], [])
    await server.start()
    s, session, events, _ = await _run_socket(server)
    try:
        s.start()
        await _until(lambda: len(events) == 2)
        assert server.connects == 1
        await s.reconnect()
        await _until(lambda: server.connects == 2)
    finally:
        await s.stop()
        await session.close()
        await server.stop()


@pytest.mark.asyncio
async def test_namespace_disconnect_41_backs_off(monkeypatch):
    monkeypatch.setattr(sock, "backoff_delay", lambda *_a, **_k: 60.0)
    server = FakeEngineIO([], [])
    await server.start()
    s, session, events, states = await _run_socket(server)
    try:
        s.start()
        await _until(lambda: len(events) == 2)
        server.queue.put_nowait("41")
        await _until(lambda: states == [True, False])
        await asyncio.sleep(0.2)
        assert server.connects == 1  # waiting out the backoff
        assert not s.connected
    finally:
        await s.stop()
        await session.close()
        await server.stop()


@pytest.mark.asyncio
async def test_probe_closed_by_server_keeps_polling(monkeypatch):
    class ClosedWs:
        closed = True

        async def close(self) -> None:
            return None

    async def fake_probe(self, session, token, sid):
        return ClosedWs()

    monkeypatch.setattr(TSMSocket, "_probe", fake_probe)
    server = FakeEngineIO(["websocket"], [])
    await server.start()
    s, session, events, _ = await _run_socket(server)
    try:
        s.start()
        await _until(lambda: len(events) == 2)
        server.queue.put_nowait("42" + json.dumps(["app_info", {"d": 4}]))
        await _until(lambda: ("app_info", {"d": 4}) in events)
        assert s.connected
        assert server.connects == 1  # kept the polling session
        assert "5" not in server.ws_frames
    finally:
        await s.stop()
        await session.close()
        await server.stop()


@pytest.mark.asyncio
async def test_affinity_cookie_is_replayed_on_poll_post_and_websocket():
    server = FakeEngineIO(["websocket"], [], affinity=True)
    await server.start()
    s, session, events, _ = await _run_socket(server)
    try:
        s.start()
        await _until(lambda: len(events) == 2)
        await _until(lambda: "5" in server.ws_frames)
        assert server.connects == 1
        assert [r[0] for r in server.requests][:3] == ["GET", "POST", "WS"]
        for req in server.requests[1:]:
            assert "lb=node1" in req[2]["Cookie"]
    finally:
        await s.stop()
        await session.close()
        await server.stop()


@pytest.mark.asyncio
async def test_http_error_names_status_content_type_and_body(caplog):
    server = FakeEngineIO([], [], affinity=True)
    await server.start()
    session = aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar())

    async def get_session():
        return session

    async def token():
        return "t"

    s = TSMSocket(get_session, token, lambda *_: None, url=server.url)
    try:
        with caplog.at_level("WARNING", logger="tsm.api.socket"):
            s.start()
            await _until(lambda: any("answered HTTP 400" in r.message for r in caplog.records))
        msg = next(r.message for r in caplog.records if "answered HTTP 400" in r.message)
        assert "polling POST" in msg
        assert "application/json" in msg
        assert "Session ID unknown" in msg
    finally:
        await s.stop()
        await session.close()
        await server.stop()


@pytest.mark.asyncio
async def test_reconnect_on_polling_sends_the_close_packet(monkeypatch):
    monkeypatch.setattr(sock, "backoff_delay", lambda *_a, **_k: 60.0)
    server = FakeEngineIO([], [])
    await server.start()
    s, session, events, _ = await _run_socket(server)
    try:
        s.start()
        await _until(lambda: len(events) == 2)
        await s.reconnect()
        await _until(lambda: "1" in server.posts)
        await _until(lambda: server.connects == 2)
    finally:
        await s.stop()
        await session.close()
        await server.stop()
