"""Tests for AuthService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from tsm.core.services.auth import RESTORE_RETRY_DELAYS, AuthService
from tsm.storage.secrets import KeyringUnavailable


@pytest.mark.asyncio
async def test_not_authenticated_initially():
    svc = AuthService()
    assert not svc.is_authenticated


@pytest.mark.asyncio
async def test_login_success():
    mock_client = MagicMock()
    mock_client.auth.get_oidc_token = AsyncMock(return_value={"access_token": "oidc_tok"})
    mock_client.auth.authenticate = AsyncMock(return_value={"session": "sess123", "userId": 42})
    mock_client.set_user_info = MagicMock()

    with patch("tsm.core.services.auth.store_credentials") as mock_store:
        svc = AuthService(mock_client)
        session = await svc.login("user@example.com", "password123")

    assert session.username == "user@example.com"
    mock_store.assert_called_once_with("user@example.com", "password123")


@pytest.mark.asyncio
async def test_logout_clears_session():
    mock_client = MagicMock()
    mock_client.auth.get_oidc_token = AsyncMock(return_value={"access_token": "tok"})
    mock_client.auth.authenticate = AsyncMock(return_value={"session": "s", "userId": 1})
    mock_client.set_user_info = MagicMock()

    with (
        patch("tsm.core.services.auth.store_credentials"),
        patch("tsm.core.services.auth.delete_credentials"),
    ):
        svc = AuthService(mock_client)
        await svc.login("u", "p")
        assert svc.is_authenticated
        await svc.logout()
        assert not svc.is_authenticated


@pytest.mark.asyncio
async def test_restore_session_success():
    mock_client = MagicMock()
    mock_client.auth.get_oidc_token = AsyncMock(return_value={"access_token": "oidc_tok"})
    mock_client.auth.authenticate = AsyncMock(return_value={"session": "s", "userId": 5})
    mock_client.set_user_info = MagicMock()

    with (
        patch("tsm.core.services.auth.get_username", return_value="user@example.com"),
        patch("tsm.core.services.auth.get_password", return_value="pass"),
    ):
        svc = AuthService(mock_client)
        restored = await svc.restore_session()

    assert restored is True
    assert svc.is_authenticated
    assert svc.current_session is not None
    assert svc.current_session.username == "user@example.com"


@pytest.mark.asyncio
async def test_restore_session_no_username():
    svc = AuthService(MagicMock())
    with patch("tsm.core.services.auth.get_username", return_value=None):
        restored = await svc.restore_session()
    assert restored is False


def _rejected(status: int) -> aiohttp.ClientResponseError:
    return aiohttp.ClientResponseError(request_info=MagicMock(), history=(), status=status)


def _restore_client(*oidc_results):
    client = MagicMock()
    client.auth.get_oidc_token = AsyncMock(side_effect=list(oidc_results))
    client.auth.authenticate = AsyncMock(return_value={"session": "s", "userId": 5})
    client.set_user_info = MagicMock()
    return client


def _stored(username="user@example.com", password="pass"):
    return (
        patch("tsm.core.services.auth.get_username", return_value=username),
        patch("tsm.core.services.auth.get_password", return_value=password),
    )


@pytest.mark.asyncio
async def test_restore_waits_for_the_network():
    client = _restore_client(
        aiohttp.ClientConnectionError("no route"),
        aiohttp.ClientConnectionError("no route"),
        {"access_token": "tok"},
    )
    user, password = _stored()
    with user, password, patch("tsm.core.services.auth.asyncio.sleep", new=AsyncMock()) as sleep:
        restored = await AuthService(client).restore_session()

    assert restored is True
    assert [c.args[0] for c in sleep.await_args_list] == [2.0, 4.0]


@pytest.mark.asyncio
async def test_restore_waits_through_a_server_error():
    client = _restore_client(_rejected(503), {"access_token": "tok"})
    user, password = _stored()
    with user, password, patch("tsm.core.services.auth.asyncio.sleep", new=AsyncMock()) as sleep:
        restored = await AuthService(client).restore_session()

    assert restored is True
    assert sleep.await_count == 1


@pytest.mark.asyncio
async def test_restore_does_not_retry_rejected_credentials():
    client = _restore_client(_rejected(401))
    user, password = _stored()
    with user, password, patch("tsm.core.services.auth.asyncio.sleep", new=AsyncMock()) as sleep:
        restored = await AuthService(client).restore_session()

    assert restored is False
    sleep.assert_not_awaited()
    assert client.auth.get_oidc_token.await_count == 1


@pytest.mark.asyncio
async def test_restore_gives_up_when_the_network_never_comes_back():
    client = _restore_client(*[aiohttp.ClientConnectionError("down")] * 20)
    user, password = _stored()
    with user, password, patch("tsm.core.services.auth.asyncio.sleep", new=AsyncMock()) as sleep:
        restored = await AuthService(client).restore_session()

    assert restored is False
    assert sleep.await_count == len(RESTORE_RETRY_DELAYS)
    assert client.auth.get_oidc_token.await_count == len(RESTORE_RETRY_DELAYS) + 1


@pytest.mark.asyncio
async def test_restore_waits_for_the_keyring():
    client = _restore_client({"access_token": "tok"})
    with (
        patch(
            "tsm.core.services.auth.get_username",
            side_effect=[KeyringUnavailable("not up"), "user@example.com"],
        ),
        patch("tsm.core.services.auth.get_password", return_value="pass"),
        patch("tsm.core.services.auth.asyncio.sleep", new=AsyncMock()) as sleep,
    ):
        restored = await AuthService(client).restore_session()

    assert restored is True
    assert sleep.await_count == 1


@pytest.mark.asyncio
async def test_restore_without_saved_login_does_not_wait():
    with (
        patch("tsm.core.services.auth.get_username", return_value=None),
        patch("tsm.core.services.auth.asyncio.sleep", new=AsyncMock()) as sleep,
    ):
        restored = await AuthService(MagicMock()).restore_session()

    assert restored is False
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_login_reports_a_login_the_keyring_would_not_keep():
    client = _restore_client({"access_token": "tok"})
    with patch("tsm.core.services.auth.store_credentials", return_value=False):
        session = await AuthService(client).login("user@example.com", "pw", remember_me=True)

    assert session.remember_failed is True


@pytest.mark.asyncio
async def test_login_is_not_a_failure_when_remember_was_not_asked_for():
    client = _restore_client({"access_token": "tok"})
    with (
        patch("tsm.core.services.auth.store_credentials", return_value=False),
        patch("tsm.core.services.auth.delete_credentials"),
    ):
        session = await AuthService(client).login("user@example.com", "pw", remember_me=False)

    assert session.remember_failed is False


@pytest.mark.asyncio
async def test_refresh_skips_quietly_while_the_keyring_is_unavailable():
    client = _restore_client()
    with patch("tsm.core.services.auth.get_username", side_effect=KeyringUnavailable("down")):
        await AuthService(client).refresh_token()

    client.auth.get_oidc_token.assert_not_awaited()
