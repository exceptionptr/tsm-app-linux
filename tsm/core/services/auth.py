"""AuthService: login, session management, logout.

Real auth flow (from AppAPI.pyc + MainThread.pyc):
1. POST OIDC token endpoint with email+password → access_token
2. POST app-server/v2/auth with {token: access_token} → session + user_info
3. All subsequent API calls use session + HMAC token as query params
4. On next startup: re-authenticate using stored email+password

Original stores email plaintext + encrypted password in QSettings.
We use keyring for secure credential storage instead.
"""

from __future__ import annotations

import logging

from tsm.api.client import TSMApiClient
from tsm.core.models.auth import UserSession
from tsm.storage.secrets import (
    delete_credentials,
    get_password,
    get_username,
    store_credentials,
)

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, api_client: TSMApiClient | None = None):
        self._client = api_client
        self._session: UserSession | None = None

    @property
    def is_authenticated(self) -> bool:
        return self._session is not None

    @property
    def current_session(self) -> UserSession | None:
        return self._session

    async def login(self, username: str, password: str, remember_me: bool = True) -> UserSession:
        """Full two-step TSM login: OIDC → TSM session."""
        logger.info("Logging in as %s", username)
        if self._client is None:
            raise RuntimeError("API client not configured")

        oidc = await self._client.auth.get_oidc_token(username, password)
        access_token = oidc["access_token"]
        await self._client.auth.authenticate(access_token)

        self._session = UserSession(username=username)
        if remember_me:
            store_credentials(username, password)
        else:
            delete_credentials()
        logger.info("Login successful (remember=%s)", remember_me)
        return self._session

    async def restore_session(self) -> bool:
        """Try to restore session using stored credentials (email+password)."""
        username = get_username()
        if not username:
            return False
        password = get_password(username)
        if not password:
            return False
        if self._client is None:
            return False
        logger.info("Attempting session restore for %s", username)
        try:
            oidc = await self._client.auth.get_oidc_token(username, password)
            access_token = oidc["access_token"]
            await self._client.auth.authenticate(access_token)
            self._session = UserSession(username=username)
            logger.info("Session restored")
            return True
        except Exception:
            logger.warning("Stored credentials invalid — need to re-login")
            return False

    async def refresh_token(self) -> None:
        """Re-authenticate using stored credentials. Called by scheduler."""
        username = get_username()
        if not username:
            logger.debug("refresh_token: no stored credentials, skipping")
            return
        password = get_password(username)
        if not password:
            return
        logger.info("Re-authenticating to refresh session")
        try:
            await self.login(username, password, remember_me=True)
        except Exception:
            logger.exception("Token refresh failed")
            raise

    async def ensure_authenticated(self) -> None:
        if self._session is not None:
            return
        restored = await self.restore_session()
        if not restored:
            raise RuntimeError("Not authenticated — please log in")

    async def logout(self) -> None:
        self._session = None
        if self._client:
            self._client.set_user_info({"session": "", "userId": 0, "endpointSubdomains": {}})
        delete_credentials()
        logger.info("Logged out")
