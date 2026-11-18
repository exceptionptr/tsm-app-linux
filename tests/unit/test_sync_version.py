"""SyncController triggers for the version feed check."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any

import pytest

from tsm.core.services.sync import SyncController


class FakeAuction:
    def __init__(self) -> None:
        self.events: list[str] = []

    def add_addon_listener(self, fn: Any) -> None:
        pass

    async def handle_event(self, name: str, payload: Any) -> None:
        self.events.append(name)

    async def load_user_realms(self) -> None:
        pass

    async def stop(self) -> None:
        pass


class FakeAuth:
    def __init__(self, expires_at: float | None = None) -> None:
        self.tokens = (
            None
            if expires_at is None
            else SimpleNamespace(access_token="tok", expires_at=expires_at)
        )

    def add_token_listener(self, fn: Any) -> None:
        pass


class FakeVersion:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, str | None]] = []

    async def check(self, session: Any, token: str | None = None) -> None:
        self.calls.append((session, token))


class FakeClient:
    async def session(self) -> str:
        return "session"


def _sync(auth: FakeAuth, version: FakeVersion, delay: float = 0.05) -> SyncController:
    return SyncController(
        auth,
        FakeAuction(),
        api_client=FakeClient(),
        app_version=version,  # type: ignore[arg-type]
        update_delay_fn=lambda: delay,
    )


async def _settle() -> None:
    import asyncio

    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_connect_checks_with_valid_token():
    version = FakeVersion()
    sync = _sync(FakeAuth(time.time() + 600), version)
    await sync._on_state(True)
    await _settle()
    assert version.calls == [("session", "tok")]
    await sync.stop()


@pytest.mark.asyncio
async def test_connect_without_valid_token_is_anonymous():
    version = FakeVersion()
    sync = _sync(FakeAuth(time.time() - 10), version)
    await sync._on_state(True)
    await _settle()
    assert version.calls == [("session", None)]
    await sync.stop()


@pytest.mark.asyncio
async def test_disconnect_does_not_check():
    version = FakeVersion()
    sync = _sync(FakeAuth(), version)
    await sync._on_state(False)
    await _settle()
    assert version.calls == []


@pytest.mark.asyncio
async def test_app_update_checks_once_after_delay():
    import asyncio

    version = FakeVersion()
    sync = _sync(FakeAuth(), version, delay=0.05)
    await sync._on_event("app_update", None)
    await sync._on_event("app_update", None)  # second one is not scheduled
    await _settle()
    assert version.calls == []
    await asyncio.sleep(0.15)
    assert len(version.calls) == 1
    # The timer is free again afterwards.
    await sync._on_event("app_update", None)
    await asyncio.sleep(0.15)
    assert len(version.calls) == 2
    await sync.stop()


@pytest.mark.asyncio
async def test_stop_cancels_pending_timer():
    import asyncio

    version = FakeVersion()
    sync = _sync(FakeAuth(), version, delay=0.05)
    await sync._on_event("app_update", None)
    await sync.stop()
    await asyncio.sleep(0.15)
    assert version.calls == []


@pytest.mark.asyncio
async def test_other_events_do_not_check():
    version = FakeVersion()
    sync = _sync(FakeAuth(), version)
    await sync._on_event("app_info", {})
    await _settle()
    assert version.calls == []


class FakeGroups:
    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.started = asyncio.Event()
        self.finished = False
        self.cancelled = False

    async def claim(self) -> None:
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        self.finished = True

    async def refresh(self) -> None:
        pass


@pytest.mark.asyncio
async def test_stop_does_not_cancel_a_group_send_claim_in_flight():
    groups = FakeGroups()
    sync = SyncController(
        FakeAuth(),
        FakeAuction(),
        api_client=FakeClient(),
        group_sends=groups,
    )
    await sync._on_event("group_send", None)
    await groups.started.wait()
    stopping = asyncio.ensure_future(sync.stop())
    await _settle()
    assert not groups.cancelled
    assert not stopping.done()  # waits for the claim
    groups.release.set()
    await stopping
    assert groups.finished
    assert not groups.cancelled
