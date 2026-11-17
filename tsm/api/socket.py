"""Push channel to app-backend-sockets: a minimal Socket.IO v4 client.

The official 1.0.14 client uses socket.io-client. The protocol it speaks is small
enough to implement directly on aiohttp, which saves a dependency. Like the
official client it starts on HTTP long polling and then upgrades to a websocket:

    client  GET  /socket.io/?EIO=4&transport=polling&t=<id>             no sid yet
    server  0{"sid":..,"upgrades":["websocket"],"pingInterval":25000,
              "pingTimeout":20000,"maxPayload":..}                       Engine.IO open
    client  POST ...&sid=<sid>   body 40                                 join namespace "/"
    server  40{"sid":..,"pid":..}                                        joined
    client  websocket ...&transport=websocket&sid=<sid>
    client  2probe   server 3probe   (polling paused)   client 5         upgrade
    server  2            client  3                                       ping / pong
    server  42["event", payload]                                         event
    server  41                                                           namespace kicked us
    server  44{"message":..}                                             join refused

A polling body may hold several packets separated by the 0x1e record separator;
the first one usually carries the initial push for every followed realm. If the
server offers no upgrade, or the upgrade fails, the connection stays on polling.

Every request carries the raw access token (no "Bearer ") in an Authorization
header; the polling requests also carry the node-XMLHttpRequest User-Agent.

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
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import aiohttp

from tsm.api.official import UA_XHR

logger = logging.getLogger(__name__)

SOCKET_URL = "https://app-backend-sockets.tradeskillmaster.com/socket.io/"

RECORD_SEPARATOR = "\x1e"
CONNECT_TIMEOUT = 20.0
CLOSE_TIMEOUT = 3.0
PROBE_TIMEOUT = 20.0
STATE_HANDLER_GRACE = 1.0

RECONNECT_MIN = 5.0
RECONNECT_MAX = 60.0
SERVER_DISCONNECT_MAX = 300.0

# The official XHR polling sends no Accept-Encoding.
POLL_SKIP_HEADERS = ("Accept-Encoding",)

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


_YEAST_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"
_yeast_state: dict[str, Any] = {"prev": "", "seed": 0}


def _yeast_encode(num: int) -> str:
    out = ""
    while True:
        out = _YEAST_ALPHABET[num % 64] + out
        num //= 64
        if num == 0:
            return out


def yeast() -> str:
    """Timestamp id like the yeast module of engine.io-client (unique per call)."""
    now = _yeast_encode(int(time.time() * 1000))
    if now != _yeast_state["prev"]:
        _yeast_state["seed"] = 0
        _yeast_state["prev"] = now
        return now
    _yeast_state["seed"] += 1
    return f"{now}.{_yeast_encode(_yeast_state['seed'])}"


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


async def _http_error(what: str, resp: aiohttp.ClientResponse) -> ConnectionError:
    """Build the error for a non-200 answer: status, content type, start of the body.

    The body is Engine.IO's error JSON ({"code":..,"message":..}); long token-like
    runs are masked so nothing secret can reach the log.
    """
    try:
        body = (await resp.text())[:200]
    except (aiohttp.ClientError, UnicodeDecodeError, TimeoutError):
        body = ""
    body = re.sub(r"[A-Za-z0-9._~+/=-]{40,}", "<masked>", body)
    ctype = resp.headers.get("Content-Type", "-")
    return ConnectionError(f"{what} answered HTTP {resp.status} ({ctype}): {body!r}")


class _State:
    """Per connection state shared by the polling and websocket phases."""

    def __init__(self) -> None:
        self.joined = False
        self.idle_timeout = 30.0
        # Engine.IO sid while the server may still hold the polling session open
        # (None once it is gone or closed by the server, or after the upgrade).
        self.sid: str | None = None


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
        self._inflight: asyncio.Task[str] | None = None
        # Set by reconnect(): checked after every handshake step so a session that
        # is still starting ends early and the next one uses the new token.
        self._wake = asyncio.Event()
        self._state_task: asyncio.Task[None] | None = None
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
        # Let the last state notification (usually "disconnected") run briefly,
        # but never wait on a slow handler.
        state_task, self._state_task = self._state_task, None
        if state_task is not None and not state_task.done():
            await asyncio.wait({state_task}, timeout=STATE_HANDLER_GRACE)
            state_task.cancel()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def reconnect(self) -> None:
        """Drop the current connection (if any) and connect again right away.

        Called after a token refresh while disconnected, or after login, so the
        new token is used without waiting out the backoff.
        """
        self._wake.set()
        inflight = self._inflight
        if inflight is not None and not inflight.done():
            inflight.cancel()
        ws = self._ws
        if ws is not None and not ws.closed:
            await ws.close()

    # ------------------------------------------------------------------ #

    async def _set_state(self, connected: bool) -> None:
        if connected != self.connected:
            self.connected = connected
            if self._on_state is None:
                return
            # Run the handler in its own task (chained, so notifications keep their
            # order): the handshake must not wait on whatever the handler does.
            previous = self._state_task
            self._state_task = asyncio.get_running_loop().create_task(
                self._notify_state(previous, connected), name="tsm-socket-state"
            )

    async def _notify_state(self, previous: asyncio.Task[None] | None, connected: bool) -> None:
        if previous is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await previous
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

    # ------------------------------------------------------------------ #
    # Transport helpers

    def _polling_url(self, sid: str | None) -> str:
        url = f"{self._url}?EIO=4&transport=polling&t={yeast()}"
        return f"{url}&sid={sid}" if sid else url

    def _websocket_url(self, sid: str) -> str:
        parts = urlsplit(self._url)
        scheme = "wss" if parts.scheme == "https" else "ws"
        query = f"EIO=4&transport=websocket&sid={sid}"
        return urlunsplit((scheme, parts.netloc, parts.path, query, ""))

    @staticmethod
    def _poll_headers(token: str) -> dict[str, str]:
        return {
            "User-Agent": UA_XHR,
            "Accept": "*/*",
            "Authorization": token,
        }

    @staticmethod
    def _log_peer(what: str, resp: aiohttp.ClientResponse) -> None:
        """Log the remote host:port of the connection, so requests that reach
        different backend instances show up as different peers."""
        conn = resp.connection
        transport = conn.transport if conn is not None else None
        peer = transport.get_extra_info("peername") if transport is not None else None
        if isinstance(peer, tuple) and len(peer) >= 2:
            logger.debug("Socket %s via %s:%s", what, peer[0], peer[1])

    async def _poll_get(
        self, session: aiohttp.ClientSession, token: str, sid: str | None, timeout: float
    ) -> str:
        async with session.get(
            self._polling_url(sid),
            headers=self._poll_headers(token),
            skip_auto_headers=POLL_SKIP_HEADERS,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if resp.status != 200:
                raise await _http_error(f"polling GET ({'poll' if sid else 'open'})", resp)
            self._log_peer("poll" if sid else "open", resp)
            return await resp.text()

    async def _poll_post(
        self, session: aiohttp.ClientSession, token: str, sid: str, body: str
    ) -> None:
        headers = self._poll_headers(token)
        headers["Content-Type"] = "text/plain;charset=UTF-8"
        async with session.post(
            self._polling_url(sid),
            data=body.encode("utf-8"),
            headers=headers,
            skip_auto_headers=POLL_SKIP_HEADERS,
            timeout=aiohttp.ClientTimeout(total=CONNECT_TIMEOUT),
        ) as resp:
            if resp.status != 200:
                raise await _http_error("polling POST", resp)
            self._log_peer("POST", resp)

    async def _handle_text(
        self,
        text: str,
        state: _State,
        send: Callable[[str], Awaitable[None]],
    ) -> bool:
        """Process every packet of a frame or polling body. True means: close."""
        for raw in text.split(RECORD_SEPARATOR):
            kind, payload = parse_packet(raw)
            if kind == "ping":
                await send("3")
            elif kind == "connect":
                state.joined = True
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
                state.sid = None
                return True
        return False

    async def _probe(
        self, session: aiohttp.ClientSession, token: str, sid: str
    ) -> aiohttp.ClientWebSocketResponse | None:
        """Open the websocket and run the 2probe/3probe exchange. None if it fails."""
        ws: aiohttp.ClientWebSocketResponse | None = None
        try:
            ws = await session.ws_connect(
                self._websocket_url(sid),
                headers={"Authorization": token},
                heartbeat=None,
                autoping=True,
                max_msg_size=0,
            )
            self._ws = ws
            await ws.send_str("2probe")
            while True:
                msg = await ws.receive(timeout=PROBE_TIMEOUT)
                if msg.type != aiohttp.WSMsgType.TEXT:
                    raise ConnectionError(f"websocket closed during probe ({msg.type.name})")
                if msg.data == "3probe":
                    return ws
        except (aiohttp.ClientError, TimeoutError, ConnectionError, OSError) as e:
            logger.warning("Websocket upgrade failed, staying on polling: %s", e)
            if ws is not None:
                with contextlib.suppress(Exception):
                    await ws.close()
            if self._ws is ws:
                self._ws = None
            return None

    async def _session_once(self) -> bool:
        """One connection from handshake to close. Returns True if we had joined."""
        session = await self._session()
        token = await self._token()
        state = _State()
        probe_task: asyncio.Task[aiohttp.ClientWebSocketResponse | None] | None = None
        try:
            first = await self._poll_get(session, token, None, CONNECT_TIMEOUT)
            if self._wake.is_set():
                return state.joined
            packets = first.split(RECORD_SEPARATOR)
            kind, info = parse_packet(packets[0])
            if kind != "open" or not isinstance(info, dict) or "sid" not in info:
                raise ConnectionError("no Engine.IO open packet")
            sid = str(info["sid"])
            state.sid = sid
            cookie_names = sorted(c.key for c in session.cookie_jar)
            logger.debug("Socket session cookie names: %s", cookie_names)
            state.idle_timeout = (
                info.get("pingInterval", 25000) + info.get("pingTimeout", 20000)
            ) / 1000
            upgrades = info.get("upgrades") or []

            async def post(body: str) -> None:
                await self._poll_post(session, token, sid, body)

            await self._poll_post(session, token, sid, "40")
            if self._wake.is_set():
                return state.joined
            if "websocket" in upgrades:
                probe_task = asyncio.get_running_loop().create_task(
                    self._probe(session, token, sid), name="tsm-socket-probe"
                )
            pending = RECORD_SEPARATOR.join(packets[1:])
            ws: aiohttp.ClientWebSocketResponse | None = None
            while ws is None:
                if pending:
                    if await self._handle_text(pending, state, post):
                        return state.joined
                    pending = ""
                if probe_task is not None and probe_task.done():
                    ws = probe_task.result()
                    probe_task = None
                    if ws is not None and ws.closed:
                        # The server abandoned the upgrade: keep polling.
                        logger.warning("Websocket closed before the upgrade, staying on polling")
                        self._ws = None
                        ws = None
                    elif ws is not None:
                        # Polling is paused (the last poll has ended): switch over.
                        try:
                            await ws.send_str("5")
                        except (aiohttp.ClientError, ConnectionError, OSError) as e:
                            logger.warning("Websocket upgrade failed, staying on polling: %s", e)
                            self._ws = None
                            with contextlib.suppress(Exception):
                                await ws.close()
                            ws = None
                        else:
                            state.sid = None  # the websocket owns the session now
                            break
                if self._wake.is_set():
                    return state.joined
                self._inflight = asyncio.get_running_loop().create_task(
                    self._poll_get(session, token, sid, state.idle_timeout),
                    name="tsm-socket-poll",
                )
                try:
                    done, _ = await asyncio.wait({self._inflight}, timeout=state.idle_timeout)
                    if not done:
                        logger.warning("Socket silent for %.0f s, reconnecting", state.idle_timeout)
                        return state.joined
                    if self._inflight.cancelled():
                        return state.joined  # reconnect() asked for a fresh connection
                    pending = self._inflight.result()
                finally:
                    self._inflight.cancel()
                    self._inflight = None
            return await self._websocket_loop(ws, state)
        except Exception:
            state.sid = None  # failed or refused: the server has dropped the session
            raise
        finally:
            outer_cancel = False
            if probe_task is not None:
                probe_task.cancel()
                try:
                    await probe_task
                except asyncio.CancelledError:
                    # Swallow the probe's own cancel, never one aimed at this task.
                    current = asyncio.current_task()
                    outer_cancel = current is not None and current.cancelling() > 0
                except Exception as e:
                    logger.debug("Websocket probe ended with an error: %s", e)
            ws_left, self._ws = self._ws, None
            if ws_left is not None and not ws_left.closed:
                with contextlib.suppress(Exception):
                    await ws_left.close()
            if state.sid is not None:
                await self._close_polling(session, token, state.sid)
            if outer_cancel:
                raise asyncio.CancelledError

    async def _close_polling(self, session: aiohttp.ClientSession, token: str, sid: str) -> None:
        """Tell the server we are leaving (Engine.IO close packet), like the official
        client does, so it does not keep a stale session around until the ping timeout
        while we reconnect."""
        headers = self._poll_headers(token)
        headers["Content-Type"] = "text/plain;charset=UTF-8"
        try:
            async with session.post(
                self._polling_url(sid),
                data=b"1",
                headers=headers,
                skip_auto_headers=POLL_SKIP_HEADERS,
                timeout=aiohttp.ClientTimeout(total=CLOSE_TIMEOUT),
            ):
                pass
        except (aiohttp.ClientError, TimeoutError, OSError) as e:
            logger.debug("Closing the polling session failed: %s", e)

    async def _websocket_loop(self, ws: aiohttp.ClientWebSocketResponse, state: _State) -> bool:
        while True:
            try:
                msg = await ws.receive(timeout=state.idle_timeout)
            except TimeoutError:
                logger.warning("Socket silent for %.0f s, reconnecting", state.idle_timeout)
                return state.joined
            if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                return state.joined
            if msg.type == aiohttp.WSMsgType.ERROR:
                raise ws.exception() or ConnectionError("websocket error")
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            if await self._handle_text(msg.data, state, ws.send_str):
                return state.joined
