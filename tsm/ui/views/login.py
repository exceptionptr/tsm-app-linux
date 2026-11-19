"""Helpers for the messages around the TSM login window.

Like the official client, the app opens the TSM login window by itself (see
AppWindow.show_login). When that does not lead to a login, the app stays in the
tray; these helpers decide what counts as a plain close and word the errors.
"""

from __future__ import annotations

import re


def login_was_closed(raw: str) -> bool:
    """True when the login ended because its window was closed or the app is quitting."""
    low = raw.lower()
    return "window was closed" in low or "application is shutting down" in low


def format_auth_error(raw: str) -> str:
    """Turn an exception string into a concise user-facing message."""
    low = raw.lower()
    if login_was_closed(raw):
        return "The login window was closed."
    if "timed out" in low and "login" in low:
        return "The sign-in was not completed in time. Please try again."
    m = re.match(r"^(\d{3})\b", raw)
    if m:
        code = int(m.group(1))
        if code == 429:
            return "Too many login attempts. Please wait and try again."
        if code >= 500:
            return f"TSM server error ({code}). Please try again later."
        return f"Login failed (HTTP {code})."
    if any(k in low for k in ("connect", "timeout", "network", "ssl", "name resolution")):
        return "Unable to reach TSM servers. Check your internet connection."
    if raw and len(raw) < 160:
        return f"Login failed: {raw}"
    return "Login failed. Please try again."
