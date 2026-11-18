"""Pure helpers for the embedded Chromium login window (no Qt imports).

The official client signs in inside an Electron window. These values and checks
make our QtWebEngine window behave the same on the wire: the callback is caught
before it reaches the network, navigation stays on the auth origin, and the
client hints carry the official Chromium identity.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit

from tsm.api.official import OFFICIAL_CHROMIUM_VERSION

AUTH_ORIGIN = "https://id.tradeskillmaster.com"
CALLBACK_URL = "http://localhost/auth/callback"

_MAJOR = OFFICIAL_CHROMIUM_VERSION.split(".")[0]
# The low-entropy brand list of the captured official request, in its order.
# QWebEngineClientHints has no setter for it, so an interceptor writes it.
SEC_CH_UA = f'"Not?A_Brand";v="24", "Chromium";v="{_MAJOR}"'
CLIENT_PLATFORM = "Linux"
ACCEPT_LANGUAGE = "en-US"
FULL_VERSION_LIST = {"Not?A_Brand": "24.0.0.0", "Chromium": OFFICIAL_CHROMIUM_VERSION}


def is_callback_url(url: str) -> bool:
    """True for the OAuth callback (http://localhost/auth/callback, any query)."""
    parts = urlsplit(url)
    return (
        parts.scheme == "http"
        and parts.hostname == "localhost"
        and parts.port is None
        and parts.path == "/auth/callback"
    )


def parse_callback(url: str) -> dict[str, str] | None:
    """The query of the callback URL (code, state, error ...), or None for any other URL."""
    if not is_callback_url(url):
        return None
    return dict(parse_qsl(urlsplit(url).query))


def is_allowed_navigation(url: str) -> bool:
    """Main-frame navigations may only stay on the auth origin (or be the callback)."""
    if is_callback_url(url):
        return True
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname == "id.tradeskillmaster.com" and (
        parts.port in (None, 443)
    )
