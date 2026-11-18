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
import random
import time
from collections.abc import Callable
from typing import Any

from tsm.api.app_version import AppVersion
from tsm.api.client import is_transient_error
from tsm.api.socket import TSMSocket

logger = logging.getLogger(__name__)

TOKEN_RETRY_SECONDS = 30.0
# The official client waits 300000 * Math.random() ms after an app_update event.
UPDATE_CHECK_MAX_DELAY = 300.0
# stop() waits this long for a group-send claim in flight instead of cancelling it.
GROUP_SYNC_STOP_WAIT = 10.0


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
        app_version: AppVersion | None = None,
        update_delay_fn: Callable[[], float] = lambda: random.uniform(0, UPDATE_CHECK_MAX_DELAY),
        group_sends: Any = None,
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
        self._app_version = app_version
        self._group_sends = group_sends
        self._update_delay_fn = update_delay_fn
        self._update_timer: asyncio.TimerHandle | None = None
        self._check_tasks: set[asyncio.Task[None]] = set()
        self._group_tasks: set[asyncio.Task[None]] = set()
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
        self._spawn_group_sync(claim=False)
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
        if self._update_timer is not None:
            self._update_timer.cancel()
            self._update_timer = None
        for task in list(self._check_tasks):
            task.cancel()
        self._check_tasks.clear()
        # A claim in flight must finish and persist: the server hands each send out once.
        if self._group_tasks:
            await asyncio.wait(set(self._group_tasks), timeout=GROUP_SYNC_STOP_WAIT)
            self._group_tasks.clear()
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
        if name == "app_update":
            self._schedule_version_check()
        elif name == "group_send":
            self._spawn_group_sync(claim=True)
            return
        await self._auction.handle_event(name, payload)

    def _schedule_version_check(self) -> None:
        """Check the feed 0 to 300 s from now; at most one check is pending."""
        if self._app_version is None or self._update_timer is not None:
            return
        loop = asyncio.get_running_loop()
        self._update_timer = loop.call_later(max(0.0, self._update_delay_fn()), self._timer_fired)

    def _timer_fired(self) -> None:
        self._update_timer = None
        self._spawn_version_check()

    def _spawn_version_check(self) -> None:
        if self._app_version is None:
            return
        task = asyncio.ensure_future(self._check_version())
        self._check_tasks.add(task)
        task.add_done_callback(self._check_tasks.discard)

    def _spawn_group_sync(self, claim: bool) -> None:
        """Claim (socket connect, group_send) or only refresh (start) the group sends."""
        if self._group_sends is None:
            return
        fn = self._group_sends.claim if claim else self._group_sends.refresh
        task = asyncio.ensure_future(fn())
        self._group_tasks.add(task)
        task.add_done_callback(self._group_tasks.discard)

    async def _check_version(self) -> None:
        assert self._app_version is not None and self._client is not None
        tokens = self._auth.tokens
        valid = tokens is not None and tokens.expires_at > time.time()
        token = tokens.access_token if tokens is not None and valid else None
        try:
            await self._app_version.check(await self._client.session(), token)
        except Exception:
            logger.exception("Version check failed")

    async def _on_state(self, connected: bool) -> None:
        if self._connection_fn is not None:
            self._connection_fn(connected)
        if connected:
            self._spawn_version_check()
            self._spawn_group_sync(claim=True)
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
