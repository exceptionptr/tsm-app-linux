"""Push channel to app-backend-sockets: a minimal Socket.IO v4 client.

The official 1.0.9 client uses socket.io-client. The protocol it speaks over a
websocket is small enough to implement directly on aiohttp, which saves a
dependency:

    server  0{"sid":..,"pingInterval":25000,"pingTimeout":20000}   Engine.IO open
    client  40                                                    join namespace "/"
    server  40{"sid":..}                                          joined
    server  2            client  3                                ping / pong
    server  42["event", payload]                                  event
    server  41                                                    namespace kicked us
    server  44{"message":..}                                      join refused

The handshake carries the raw access token (no "Bearer ") in an Authorization
header. Right after joining, the server pushes the current data for every realm
the account follows, then pushes again whenever something changes.

Reconnects follow the official client: 5 s doubling up to 60 s after a dropped
connection, and 5 s doubling up to 300 s with jitter after the server itself
disconnects us (which is what it does on an expired or rejected token).
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

SOCKET_URL = "wss://app-backend-sockets.tradeskillmaster.com/socket.io/?EIO=4&transport=websocket"

RECONNECT_MIN = 5.0
RECONNECT_MAX = 60.0
SERVER_DISCONNECT_MAX = 300.0

EventHandler = Callable[[str, Any], Awaitable[None] | None]
StateHandler = Callable[[bool], Awaitable[None] | None]


class ServerDisconnect(RuntimeError):
    """The server closed the namespace (41) or refused to let us join (44)."""


def backoff_delay(attempt: int, maximum: float, jitter: float = 0.5) -> float:
    """Exponential backoff from RECONNECT_MIN, randomised by +-jitter."""
    base = min(maximum, RECONNECT_MIN * float(2 ** max(0, attempt)))
    return max(1.0, base * (1 + random.uniform(-jitter, jitter)))


def parse_packet(text: str) -> tuple[str, Any]:
    """Split a Socket.IO text frame into (type, payload).

    Types: "open", "ping", "pong", "close", "connect", "disconnect", "event",
    "connect_error" and "unknown". Event payloads are (name, data).
    """
    if not text:
        return "unknown", None
    eio = text[0]
    if eio == "0":
        return "open", _json(text[1:])
    if eio == "1":
        return "close", None
    if eio == "2":
        return "ping", None
    if eio == "3":
        return "pong", None
    if eio != "4" or len(text) < 2:
        return "unknown", text
    sio, body = text[1], text[2:]
    if sio == "0":
        return "connect", _json(body)
    if sio == "1":
        return "disconnect", None
    if sio == "4":
        return "connect_error", _json(body)
    if sio == "2":
        # An ack id may precede the array: 42<id>[...]. The server never asks for
        # acks, but skip one anyway rather than failing to parse.
        start = body.find("[")
        arr = _json(body[start:]) if start != -1 else None
        if isinstance(arr, list) and arr and isinstance(arr[0], str):
            return "event", (arr[0], arr[1] if len(arr) > 1 else None)
    return "unknown", text


def _json(body: str) -> Any:
    if not body:
        return None
    try:
        return json.loads(body)
    except ValueError:
        return None


async def _call(handler: Callable[..., Any] | None, *args: Any) -> None:
    if handler is None:
        return
    try:
        result = handler(*args)
        if inspect.isawaitable(result):
            await result
    except Exception:
        logger.exception("Socket handler %r failed", handler)


class TSMSocket:
    def __init__(
        self,
        session: Callable[[], Awaitable[aiohttp.ClientSession]],
        token: Callable[[], Awaitable[str]],
        on_event: EventHandler,
        on_state: StateHandler | None = None,
        url: str = SOCKET_URL,
    ) -> None:
        self._session = session
        self._token = token
        self._on_event = on_event
        self._on_state = on_state
        self._url = url
        self._task: asyncio.Task[None] | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._wake = asyncio.Event()
        self.connected = False

    # ------------------------------------------------------------------ #

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run(), name="tsm-socket")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def reconnect(self) -> None:
        """Drop the current connection (if any) and connect again right away.

        Called after a token refresh while disconnected, or after login, so the
        new token is used without waiting out the backoff.
        """
        self._wake.set()
        ws = self._ws
        if ws is not None and not ws.closed:
            await ws.close()

    # ------------------------------------------------------------------ #

    async def _set_state(self, connected: bool) -> None:
        if connected != self.connected:
            self.connected = connected
            await _call(self._on_state, connected)

    async def _run(self) -> None:
        attempt = 0
        server_attempt = 0
        while True:
            self._wake.clear()
            delay: float
            try:
                joined = await self._session_once()
                # A clean close after we were in: reconnect quickly.
                if joined:
                    server_attempt = 0
                attempt = 0 if joined else attempt + 1
                delay = backoff_delay(attempt - 1, RECONNECT_MAX) if attempt else RECONNECT_MIN
            except asyncio.CancelledError:
                await self._set_state(False)
                raise
            except ServerDisconnect as e:
                logger.warning("Socket disconnected by the server: %s", e)
                delay = backoff_delay(server_attempt, SERVER_DISCONNECT_MAX)
                server_attempt += 1
            except Exception as e:
                logger.warning("Socket connection failed: %s", e)
                delay = backoff_delay(attempt, RECONNECT_MAX)
                attempt += 1
            await self._set_state(False)
            if self._wake.is_set():
                continue
            logger.info("Socket reconnecting in %.0f s", delay)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), delay)

    async def _session_once(self) -> bool:
        """One connection from handshake to close. Returns True if we had joined."""
        session = await self._session()
        token = await self._token()
        joined = False
        async with session.ws_connect(
            self._url,
            headers={"Authorization": token},
            heartbeat=None,
            autoping=True,
            max_msg_size=0,
        ) as ws:
            self._ws = ws
            try:
                # Before the open packet arrives we have no ping interval yet.
                idle_timeout = 30.0
                while True:
                    try:
                        msg = await ws.receive(timeout=idle_timeout)
                    except TimeoutError:
                        logger.warning("Socket silent for %.0f s, reconnecting", idle_timeout)
                        return joined
                    if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                        return joined
                    if msg.type == aiohttp.WSMsgType.ERROR:
                        raise ws.exception() or ConnectionError("websocket error")
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    kind, payload = parse_packet(msg.data)
                    if kind == "open":
                        info = payload if isinstance(payload, dict) else {}
                        idle_timeout = (
                            info.get("pingInterval", 25000) + info.get("pingTimeout", 20000)
                        ) / 1000
                        await ws.send_str("40")
                    elif kind == "ping":
                        await ws.send_str("3")
                    elif kind == "connect":
                        joined = True
                        logger.info("Socket connected")
                        await self._set_state(True)
                    elif kind == "event":
                        name, data = payload
                        logger.debug("Socket event %s", name)
                        await _call(self._on_event, name, data)
                    elif kind == "connect_error":
                        msg_text = payload.get("message") if isinstance(payload, dict) else None
                        raise ServerDisconnect(msg_text or "connection refused")
                    elif kind == "disconnect":
                        raise ServerDisconnect("io server disconnect")
                    elif kind == "close":
                        return joined
            finally:
                self._ws = None
