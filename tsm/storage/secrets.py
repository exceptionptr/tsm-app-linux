"""Keyring wrapper for storing auth credentials securely.

Uses the system keychain (KWallet on KDE, GNOME Keyring on GNOME,
or keyrings.alt file-based fallback) to store the TSM username and the
offline refresh token of the browser login, so the app can sign in again on
next startup without showing the login dialog. The password itself is never
seen by the app since the move to the browser login.

Versions before the browser login stored the password under "password:<username>". It is
deleted on the next save or logout.

An app started with the desktop session can run before the Secret Service is
up. keyring chooses its backend once per process, so if that moment is too
early it settles on a backend that fails every call and stays on it. Every
call here therefore detects the backend again after a failure and tries once
more before it gives up.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

SERVICE_NAME = "tsm-app"
USERNAME_KEY = "username"
PASSWORD_PREFIX = "password:"  # legacy, only ever deleted
REFRESH_PREFIX = "refresh:"

_T = TypeVar("_T")


class KeyringUnavailable(Exception):
    """The keyring cannot be reached right now, which is not the same as empty.

    Raised by the getters so a caller can tell "nothing saved" from "the Secret
    Service is not up yet" and wait instead of asking the user to log in.
    """


def _call(operation: Callable[[], _T]) -> _T:
    """Run a keyring operation, detecting the backend again after a failure.

    A locked keyring is passed through untouched: the user has just dismissed
    the unlock prompt, and trying again would only ask them a second time.
    """
    import keyring.core
    from keyring.errors import KeyringLocked

    try:
        return operation()
    except KeyringLocked:
        raise
    except Exception as first:
        logger.info("Keyring call failed (%s), detecting the backend again", first)
    keyring.core.init_backend()
    try:
        return operation()
    except KeyringLocked:
        raise
    except Exception as e:
        raise KeyringUnavailable(str(e)) from e


def store_credentials(username: str, refresh_token: str) -> bool:
    """Save the login. Returns False when it could not be saved."""
    import keyring

    try:
        old = _call(lambda: keyring.get_password(SERVICE_NAME, USERNAME_KEY))
        _call(lambda: keyring.set_password(SERVICE_NAME, USERNAME_KEY, username))
        _call(lambda: keyring.set_password(SERVICE_NAME, REFRESH_PREFIX + username, refresh_token))
    except Exception:
        logger.exception("Failed to store credentials in keyring")
        return False
    for name in {username, old} - {None}:
        _delete(PASSWORD_PREFIX + str(name))
    if old and old != username:
        _delete(REFRESH_PREFIX + old)
    return True


def get_username() -> str | None:
    """The saved username, or None when nothing is saved.

    Raises KeyringUnavailable when the keyring cannot be reached.
    """
    import keyring

    try:
        return _call(lambda: keyring.get_password(SERVICE_NAME, USERNAME_KEY))
    except KeyringUnavailable:
        raise
    except Exception:
        logger.exception("Failed to get username from keyring")
        return None


def get_refresh_token(username: str) -> str | None:
    """The saved refresh token, or None when nothing is saved.

    Raises KeyringUnavailable when the keyring cannot be reached.
    """
    import keyring

    try:
        return _call(lambda: keyring.get_password(SERVICE_NAME, REFRESH_PREFIX + username))
    except KeyringUnavailable:
        raise
    except Exception:
        logger.exception("Failed to get the refresh token from keyring")
        return None


def has_legacy_password(username: str) -> bool:
    """True when an old version left a password behind (used to explain the re-login)."""
    import keyring

    try:
        return bool(keyring.get_password(SERVICE_NAME, PASSWORD_PREFIX + username))
    except Exception:
        return False


def _delete(key: str) -> None:
    import keyring

    with contextlib.suppress(Exception):
        keyring.delete_password(SERVICE_NAME, key)


def delete_credentials() -> None:
    try:
        import keyring

        username = keyring.get_password(SERVICE_NAME, USERNAME_KEY)
        if username:
            _delete(PASSWORD_PREFIX + username)
            _delete(REFRESH_PREFIX + username)
        keyring.delete_password(SERVICE_NAME, USERNAME_KEY)
    except Exception:
        logger.debug("No credentials to delete from keyring")
