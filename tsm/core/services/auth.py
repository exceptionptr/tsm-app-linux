"""AuthService: browser login, token lifetime, logout.

Flow (official 1.0.9 client, see tsm/api/oidc.py):
1. The login page opens in the system browser (authorization code + PKCE).
2. The resulting access token is used directly as a Bearer token by every TSM
   service, and raw as the socket's Authorization header.
3. Shortly before the access token expires it is refreshed with the offline
   refresh token, which also survives restarts in the keyring.
4. Logout revokes the refresh token.
"""

from __future__ import annotations

import asyncio
import logging
import time
import webbrowser
from collections.abc import Awaitable, Callable

import aiohttp

from tsm.api import oidc
from tsm.api.client import TSMApiClient, is_transient_error
from tsm.core.models.auth import UserSession
from tsm.storage.secrets import (
    KeyringUnavailable,
    delete_credentials,
    get_refresh_token,
    get_username,
    has_legacy_password,
    store_credentials,
)

logger = logging.getLogger(__name__)

# An app started with the desktop session can run before the network or the
# Secret Service is up. Session restore waits through these pauses (about two
# minutes in all) before it gives up and lets the login dialog appear.
RESTORE_RETRY_DELAYS = (2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0)

TokenListener = Callable[[], Awaitable[None] | None]


def _worth_retrying(exc: Exception) -> bool:
    return isinstance(exc, KeyringUnavailable) or is_transient_error(exc)


class NotAuthenticated(RuntimeError):
    """No usable login: the user has to sign in again."""


class AuthService:
    def __init__(self, api_client: TSMApiClient | None = None):
        self._client = api_client
        self._session: UserSession | None = None
        self._tokens: oidc.Tokens | None = None
        self._remember = True
        self._lock: asyncio.Lock | None = None
        self._listeners: list[TokenListener] = []
        self._lost_listeners: list[Callable[[], None]] = []
        # Set when restore found a password from the old login, so the dialog can
        # explain why the user has to sign in once more.
        self.migrated_from_password = False
        if api_client is not None:
            api_client.set_token_provider(self.access_token)

    @property
    def is_authenticated(self) -> bool:
        return self._session is not None

    @property
    def current_session(self) -> UserSession | None:
        return self._session

    @property
    def tokens(self) -> oidc.Tokens | None:
        return self._tokens

    def add_token_listener(self, fn: TokenListener) -> None:
        """Called on the async loop whenever a new access token is in place."""
        self._listeners.append(fn)

    def add_session_lost_listener(self, fn: Callable[[], None]) -> None:
        """Called when the refresh token stops working and the user must sign in."""
        self._lost_listeners.append(fn)

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def _http(self) -> aiohttp.ClientSession:
        if self._client is None:
            raise RuntimeError("API client not configured")
        return await self._client.session()

    # ------------------------------------------------------------------ #
    # Login and restore
    # ------------------------------------------------------------------ #

    async def login(
        self,
        remember_me: bool = True,
        open_url: Callable[[str], object] = webbrowser.open,
        on_url: Callable[[str], None] | None = None,
    ) -> UserSession:
        """Sign in through the browser. Raises oidc.LoginCancelled on timeout."""
        logger.info("Starting browser login")
        tokens = await oidc.browser_login(await self._http(), open_url=open_url, on_url=on_url)
        return await self._adopt(tokens, remember_me)

    async def _adopt(self, tokens: oidc.Tokens, remember_me: bool) -> UserSession:
        self._tokens = tokens
        self._remember = remember_me
        remember_failed = False
        if remember_me:
            remember_failed = not store_credentials(tokens.username, tokens.refresh_token)
        else:
            delete_credentials()
        self._session = UserSession(
            username=tokens.username,
            user_id=tokens.user_id,
            premium_tier=tokens.premium_tier,
            release_channels=tokens.release_channels,
            remember_failed=remember_failed,
        )
        if remember_failed:
            logger.warning(
                "Login successful, but it could not be saved to the keyring: "
                "you will have to log in again next time"
            )
        else:
            logger.info(
                "Logged in (tier=%s, remember=%s)", tokens.premium_tier or "free", remember_me
            )
        await self._notify()
        return self._session

    async def restore_session(self) -> bool:
        """Sign in again with the stored refresh token.

        Waits through a missing network or keyring, since both are routinely not
        ready yet when the app starts with the desktop session. Returns False
        straight away when nothing is saved or the server rejects the token.
        """
        for delay in (*RESTORE_RETRY_DELAYS, None):
            try:
                return await self._restore_once()
            except Exception as e:
                if not _worth_retrying(e):
                    raise
                if delay is None:
                    logger.warning("Giving up on session restore: %s", e)
                    return False
                logger.warning("Session restore not possible yet (%s), retrying in %.0fs", e, delay)
                await asyncio.sleep(delay)
        return False

    async def _restore_once(self) -> bool:
        """One restore attempt. Raises only for a failure that is worth retrying."""
        username = get_username()
        if not username or self._client is None:
            return False
        refresh_token = get_refresh_token(username)
        if not refresh_token:
            if has_legacy_password(username):
                logger.info("Found a password from the old login; a browser sign-in is needed")
                self.migrated_from_password = True
            return False
        logger.info("Restoring the session for %s", username)
        try:
            tokens = await oidc.refresh(await self._http(), refresh_token)
        except Exception as e:
            if is_transient_error(e):
                raise
            logger.warning("Stored login no longer accepted (%s), need to sign in again", e)
            return False
        await self._adopt(tokens, remember_me=True)
        logger.info("Session restored")
        return True

    # ------------------------------------------------------------------ #
    # Token lifetime
    # ------------------------------------------------------------------ #

    async def access_token(self) -> str:
        """A valid access token, refreshed first if it is about to expire."""
        tokens = self._tokens
        if tokens is None:
            raise NotAuthenticated("Not authenticated, please log in")
        if tokens.needs_refresh():
            await self.refresh_token()
            tokens = self._tokens
            if tokens is None:
                raise NotAuthenticated("Login expired, please log in again")
        return tokens.access_token

    async def refresh_token(self, force: bool = False) -> None:
        """Refresh the access token if it is close to expiry (or always, with force).

        A transient failure is raised so the caller can try again later. A
        rejected refresh token ends the session and tells the listeners.
        """
        async with self._get_lock():
            tokens = self._tokens
            if tokens is None:
                return
            if not force and not tokens.needs_refresh():
                return
            try:
                new = await oidc.refresh(await self._http(), tokens.refresh_token)
            except Exception as e:
                if is_transient_error(e):
                    logger.warning("Token refresh failed, will retry: %s", e)
                    raise
                logger.warning("Refresh token rejected (%s): signing out", e)
                self._tokens = None
                self._session = None
                delete_credentials()
                for fn in self._lost_listeners:
                    try:
                        fn()
                    except Exception:
                        logger.exception("Session lost listener failed")
                return
            self._tokens = new
            if self._remember and new.refresh_token != tokens.refresh_token:
                store_credentials(new.username, new.refresh_token)
            logger.debug("Access token refreshed, valid for %.0f s", new.expires_at - time.time())
        await self._notify()

    def seconds_until_refresh(self) -> float | None:
        """When the next refresh is due, for the scheduler. None when signed out."""
        if self._tokens is None:
            return None
        return max(0.0, self._tokens.expires_at - oidc.REFRESH_MARGIN_SECONDS - time.time())

    async def _notify(self) -> None:
        for fn in self._listeners:
            try:
                result = fn()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Token listener failed")

    async def ensure_authenticated(self) -> None:
        if self._session is not None:
            return
        restored = await self.restore_session()
        if not restored:
            raise NotAuthenticated("Not authenticated, please log in")

    async def logout(self) -> None:
        tokens = self._tokens
        self._tokens = None
        self._session = None
        delete_credentials()
        if tokens is not None and self._client is not None:
            await oidc.revoke(await self._http(), tokens.refresh_token)
        logger.info("Logged out")
