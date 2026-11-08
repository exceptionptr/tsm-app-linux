"""Tests for AuthService (browser login, refresh token lifetime)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from tsm.api.oidc import OIDCError, Tokens
from tsm.core.services.auth import RESTORE_RETRY_DELAYS, AuthService, NotAuthenticated
from tsm.storage.secrets import KeyringUnavailable

M = "tsm.core.services.auth"


def _tokens(refresh: str = "r1", ttl: float = 300, sub: str = "u-1") -> Tokens:
    return Tokens(
        access_token="a-" + refresh,
        refresh_token=refresh,
        expires_at=time.time() + ttl,
        claims={
            "sub": sub,
            "preferred_username": "someone",
            "realm_access": {"roles": ["premium-platinum"]},
        },
    )


def _client() -> MagicMock:
    client = MagicMock()
    client.session = AsyncMock(return_value=MagicMock())
    return client


def _saved(username: str | None = "someone", token: str | None = "stored"):
    return (
        patch(f"{M}.get_username", return_value=username),
        patch(f"{M}.get_refresh_token", return_value=token),
    )


@pytest.mark.asyncio
async def test_not_authenticated_initially():
    svc = AuthService()
    assert not svc.is_authenticated
    with pytest.raises(NotAuthenticated):
        await svc.access_token()


@pytest.mark.asyncio
async def test_registers_itself_as_token_provider():
    client = _client()
    svc = AuthService(client)
    client.set_token_provider.assert_called_once_with(svc.access_token)


@pytest.mark.asyncio
async def test_login_stores_the_refresh_token():
    with (
        patch(f"{M}.oidc.browser_login", new=AsyncMock(return_value=_tokens())),
        patch(f"{M}.store_credentials", return_value=True) as store,
    ):
        svc = AuthService(_client())
        session = await svc.login()
    store.assert_called_once_with("someone", "r1")
    assert session.user_id == "u-1"
    assert session.premium_tier == "platinum"
    assert session.realm_limit is None
    assert await svc.access_token() == "a-r1"


@pytest.mark.asyncio
async def test_login_without_remember_deletes_saved_login():
    with (
        patch(f"{M}.oidc.browser_login", new=AsyncMock(return_value=_tokens())),
        patch(f"{M}.store_credentials") as store,
        patch(f"{M}.delete_credentials") as delete,
    ):
        await AuthService(_client()).login(remember_me=False)
    store.assert_not_called()
    delete.assert_called_once()


@pytest.mark.asyncio
async def test_remember_failed_is_reported():
    with (
        patch(f"{M}.oidc.browser_login", new=AsyncMock(return_value=_tokens())),
        patch(f"{M}.store_credentials", return_value=False),
    ):
        session = await AuthService(_client()).login()
    assert session.remember_failed


@pytest.mark.asyncio
async def test_expiring_token_is_refreshed_on_use_and_rotation_saved():
    with (
        patch(f"{M}.oidc.browser_login", new=AsyncMock(return_value=_tokens(ttl=30))),
        patch(f"{M}.oidc.refresh", new=AsyncMock(return_value=_tokens("r2"))) as refresh,
        patch(f"{M}.store_credentials", return_value=True) as store,
    ):
        svc = AuthService(_client())
        listener = AsyncMock()
        await svc.login()
        svc.add_token_listener(listener)
        assert await svc.access_token() == "a-r2"
    refresh.assert_awaited_once()
    assert store.call_args_list[-1].args == ("someone", "r2")
    listener.assert_awaited_once()


@pytest.mark.asyncio
async def test_rejected_refresh_signs_out_and_tells_listeners():
    lost = MagicMock()
    with (
        patch(f"{M}.oidc.browser_login", new=AsyncMock(return_value=_tokens(ttl=30))),
        patch(f"{M}.oidc.refresh", new=AsyncMock(side_effect=OIDCError("Token is not active"))),
        patch(f"{M}.store_credentials", return_value=True),
        patch(f"{M}.delete_credentials") as delete,
    ):
        svc = AuthService(_client())
        svc.add_session_lost_listener(lost)
        await svc.login()
        with pytest.raises(NotAuthenticated):
            await svc.access_token()
    assert not svc.is_authenticated
    lost.assert_called_once()
    delete.assert_called_once()


@pytest.mark.asyncio
async def test_transient_refresh_failure_keeps_the_session():
    with (
        patch(f"{M}.oidc.browser_login", new=AsyncMock(return_value=_tokens(ttl=30))),
        patch(f"{M}.oidc.refresh", new=AsyncMock(side_effect=aiohttp.ClientConnectionError())),
        patch(f"{M}.store_credentials", return_value=True),
    ):
        svc = AuthService(_client())
        await svc.login()
        with pytest.raises(aiohttp.ClientConnectionError):
            await svc.refresh_token()
    assert svc.is_authenticated


@pytest.mark.asyncio
async def test_seconds_until_refresh_keeps_the_margin():
    with (
        patch(f"{M}.oidc.browser_login", new=AsyncMock(return_value=_tokens(ttl=300))),
        patch(f"{M}.store_credentials", return_value=True),
    ):
        svc = AuthService(_client())
        assert svc.seconds_until_refresh() is None
        await svc.login()
    wait = svc.seconds_until_refresh()
    assert wait is not None and 205 <= wait <= 210


@pytest.mark.asyncio
async def test_logout_revokes_and_forgets():
    with (
        patch(f"{M}.oidc.browser_login", new=AsyncMock(return_value=_tokens())),
        patch(f"{M}.oidc.revoke", new=AsyncMock()) as revoke,
        patch(f"{M}.store_credentials", return_value=True),
        patch(f"{M}.delete_credentials") as delete,
    ):
        svc = AuthService(_client())
        await svc.login()
        await svc.logout()
    assert not svc.is_authenticated
    assert revoke.await_args.args[1] == "r1"
    delete.assert_called_once()


# ── Restore ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_restore_session_success():
    user, token = _saved()
    with (
        user,
        token,
        patch(f"{M}.oidc.refresh", new=AsyncMock(return_value=_tokens("r2"))) as refresh,
        patch(f"{M}.store_credentials", return_value=True),
    ):
        svc = AuthService(_client())
        assert await svc.restore_session() is True
    assert refresh.await_args.args[1] == "stored"
    assert svc.current_session is not None
    assert svc.current_session.user_id == "u-1"


@pytest.mark.asyncio
async def test_restore_without_saved_login_does_not_wait():
    user, token = _saved(username=None)
    with user, token, patch(f"{M}.asyncio.sleep", new=AsyncMock()) as sleep:
        assert await AuthService(_client()).restore_session() is False
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_restore_notices_a_password_from_the_old_login():
    user, token = _saved(token=None)
    with user, token, patch(f"{M}.has_legacy_password", return_value=True):
        svc = AuthService(_client())
        assert await svc.restore_session() is False
    assert svc.migrated_from_password


@pytest.mark.asyncio
async def test_restore_waits_for_the_network():
    user, token = _saved()
    refresh = AsyncMock(
        side_effect=[aiohttp.ClientConnectionError(), aiohttp.ClientConnectionError(), _tokens()]
    )
    with (
        user,
        token,
        patch(f"{M}.oidc.refresh", new=refresh),
        patch(f"{M}.store_credentials", return_value=True),
        patch(f"{M}.asyncio.sleep", new=AsyncMock()) as sleep,
    ):
        assert await AuthService(_client()).restore_session() is True
    assert [c.args[0] for c in sleep.await_args_list] == [2.0, 4.0]


@pytest.mark.asyncio
async def test_restore_does_not_retry_a_rejected_token():
    user, token = _saved()
    with (
        user,
        token,
        patch(f"{M}.oidc.refresh", new=AsyncMock(side_effect=OIDCError("invalid_grant"))),
        patch(f"{M}.asyncio.sleep", new=AsyncMock()) as sleep,
    ):
        assert await AuthService(_client()).restore_session() is False
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_restore_gives_up_when_the_network_never_comes_back():
    user, token = _saved()
    refresh = AsyncMock(side_effect=aiohttp.ClientConnectionError())
    with (
        user,
        token,
        patch(f"{M}.oidc.refresh", new=refresh),
        patch(f"{M}.asyncio.sleep", new=AsyncMock()) as sleep,
    ):
        assert await AuthService(_client()).restore_session() is False
    assert sleep.await_count == len(RESTORE_RETRY_DELAYS)
    assert refresh.await_count == len(RESTORE_RETRY_DELAYS) + 1


@pytest.mark.asyncio
async def test_restore_waits_for_the_keyring():
    with (
        patch(f"{M}.get_username", side_effect=[KeyringUnavailable("x"), "someone"]),
        patch(f"{M}.get_refresh_token", return_value="stored"),
        patch(f"{M}.oidc.refresh", new=AsyncMock(return_value=_tokens())),
        patch(f"{M}.store_credentials", return_value=True),
        patch(f"{M}.asyncio.sleep", new=AsyncMock()) as sleep,
    ):
        assert await AuthService(_client()).restore_session() is True
    assert sleep.await_count == 1
