"""Keyring wrapper for storing auth credentials securely.

Uses the system keychain (KWallet on KDE, GNOME Keyring on GNOME,
or keyrings.alt file-based fallback) to store the TSM username and
password so the app can re-authenticate on next startup without
showing the login dialog.
"""

from __future__ import annotations

import contextlib
import logging

logger = logging.getLogger(__name__)

SERVICE_NAME = "tsm-app"
USERNAME_KEY = "username"
PASSWORD_PREFIX = "password:"


def store_credentials(username: str, password: str) -> None:
    try:
        import keyring

        keyring.set_password(SERVICE_NAME, USERNAME_KEY, username)
        keyring.set_password(SERVICE_NAME, PASSWORD_PREFIX + username, password)
    except Exception:
        logger.exception("Failed to store credentials in keyring")


def get_username() -> str | None:
    try:
        import keyring

        return keyring.get_password(SERVICE_NAME, USERNAME_KEY)
    except Exception:
        logger.exception("Failed to get username from keyring")
        return None


def get_password(username: str) -> str | None:
    try:
        import keyring

        return keyring.get_password(SERVICE_NAME, PASSWORD_PREFIX + username)
    except Exception:
        logger.exception("Failed to get password from keyring")
        return None


def delete_credentials() -> None:
    try:
        import keyring

        username = keyring.get_password(SERVICE_NAME, USERNAME_KEY)
        if username:
            with contextlib.suppress(Exception):
                keyring.delete_password(SERVICE_NAME, PASSWORD_PREFIX + username)
        keyring.delete_password(SERVICE_NAME, USERNAME_KEY)
    except Exception:
        logger.debug("No credentials to delete from keyring")
