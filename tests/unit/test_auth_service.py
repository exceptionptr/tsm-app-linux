"""Tests for AuthService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tsm.core.services.auth import AuthService


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
