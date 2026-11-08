"""SyncController: the socket, the token refresh timer and the routing between them.

Started after login (once the WoW installs are known) and stopped on logout:

    socket event --> AuctionDataService.handle_event --> AppData.lua
                                         \\--> addon releases --> UpdateService
    token refresh (90 s before expiry) --> socket reconnect if it is down

The socket only reads the token when it connects, so a refreshed token
matters for the next reconnect; nothing has to happen while it is connected.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any

from tsm.api.client import is_transient_error
from tsm.api.socket import TSMSocket

logger = logging.getLogger(__name__)

TOKEN_RETRY_SECONDS = 30.0


class SyncController:
    def __init__(
        self,
        auth: Any,
        auction: Any,
        updater: Any = None,
        api_client: Any = None,
        addon_notify_fn: Callable[[str], None] | None = None,
        connection_fn: Callable[[bool], None] | None = None,
        socket_factory: Callable[..., TSMSocket] = TSMSocket,
    ) -> None:
        self._auth = auth
        self._auction = auction
        self._updater = updater
        self._client = api_client
        self._addon_notify_fn = addon_notify_fn
        self._connection_fn = connection_fn
        self._socket_factory = socket_factory
        self._socket: TSMSocket | None = None
        self._refresh_task: asyncio.Task[None] | None = None
        self._started = False
        auction.reconnect = self.reconnect
        auction.add_addon_listener(self._on_addons)
        auth.add_token_listener(self._on_token)

    @property
    def connected(self) -> bool:
        return self._socket is not None and self._socket.connected

    async def start(self) -> None:
        if self._started:
            return
        session = self._auth.current_session
        if session is None:
            logger.warning("SyncController.start without a session")
            return
        self._started = True
        self._refresh_task = asyncio.ensure_future(self._refresh_loop())
        try:
            await self._auction.start(session.user_id)
        except Exception:
            # Catalogue or user realms unavailable: the socket still delivers data
            # for realms we know from the cache, and a reconnect retries the rest.
            logger.exception("Loading realms failed")
        assert self._client is not None
        self._socket = self._socket_factory(
            self._client.session, self._auth.access_token, self._on_event, self._on_state
        )
        self._socket.start()

    async def stop(self) -> None:
        self._started = False
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            with contextlib.suppress(BaseException):
                await self._refresh_task
            self._refresh_task = None
        if self._socket is not None:
            await self._socket.stop()
            self._socket = None
        await self._auction.stop()

    async def reconnect(self) -> None:
        if self._socket is not None:
            await self._socket.reconnect()

    # ------------------------------------------------------------------ #

    async def _on_event(self, name: str, payload: Any) -> None:
        await self._auction.handle_event(name, payload)

    async def _on_state(self, connected: bool) -> None:
        if self._connection_fn is not None:
            self._connection_fn(connected)
        if connected:
            # The server pushes everything on connect; reload what it is pushed for.
            with contextlib.suppress(Exception):
                await self._auction.load_user_realms()

    async def _on_token(self) -> None:
        if self._socket is not None and not self._socket.connected:
            await self._socket.reconnect()

    async def _on_addons(self, releases: list[Any]) -> None:
        if self._updater is None:
            return
        try:
            updated = await self._updater.check_and_update(releases)
        except Exception:
            logger.exception("Addon update failed")
            return
        if updated and self._addon_notify_fn is not None:
            self._addon_notify_fn(f"TSM addon(s) updated: {', '.join(updated)}")

    async def _refresh_loop(self) -> None:
        while True:
            wait = self._auth.seconds_until_refresh()
            if wait is None:
                return
            await asyncio.sleep(max(1.0, wait))
            try:
                await self._auth.refresh_token()
            except Exception as e:
                if not is_transient_error(e):
                    logger.exception("Token refresh failed")
                await asyncio.sleep(TOKEN_RETRY_SECONDS)
