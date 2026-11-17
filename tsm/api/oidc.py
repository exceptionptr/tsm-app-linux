"""TSM account login: OpenID Connect authorization code flow with PKCE.

Matches the official 1.0.14 client (keycloak-js inside Electron): same authorize
parameters in the same order, same PKCE, state and nonce formats, and the token,
refresh and revoke requests with the headers the official channels send (the
token calls come from Chromium, the revoke call from undici). We differ in one
point: we hand the login page to the system browser and catch the redirect on a
loopback listener (RFC 8252) instead of embedding a browser. The official
redirect_uri has no port (http://localhost/auth/callback) and cannot be bound
without privileges, so redirect_uri() puts the ephemeral listener port in.
Keycloak accepts http://localhost:<any port>/auth/callback for the desktop-app
client (probed 2026-11-08: 127.0.0.1 and other paths are rejected).

The desktop-app client refuses the password grant ("Client not allowed for
direct access grants"), so the browser is the only way in. In exchange the app
never sees the password: it keeps an offline refresh token instead.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import secrets
import time
import uuid
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

import aiohttp
from aiohttp import web
from aiohttp.compression_utils import HAS_BROTLI

from tsm.api.official import UA_CHROMIUM, UA_UNDICI

logger = logging.getLogger(__name__)

AUTH_BASE = "https://id.tradeskillmaster.com/realms/app/protocol/openid-connect"
CLIENT_ID = "desktop-app"
SCOPE = "openid roles profile email tsm-profile offline_access"
CALLBACK_PATH = "/auth/callback"
# The official client refreshes when fewer than 90 s of validity remain.
REFRESH_MARGIN_SECONDS = 90
LOGIN_TIMEOUT_SECONDS = 600
PKCE_VERIFIER_LENGTH = 96
_PKCE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"

_DONE_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>TSM</title>
<style>body{{font-family:sans-serif;background:#1e1e1e;color:#ddd;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0}}</style></head>
<body><div><h2>{title}</h2><p>{text}</p></div></body></html>"""


class OIDCError(RuntimeError):
    """The identity server refused a request (bad grant, revoked token, ...)."""


class LoginCancelled(RuntimeError):
    """The browser login was abandoned or timed out."""


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def redirect_uri(port: int | None = None) -> str:
    """The OAuth redirect URI, the one place it is built.

    The official client uses http://localhost/auth/callback (no port, Electron
    intercepts it in its own window). A system browser needs a listener, which
    cannot bind port 80 unprivileged, so the listener's ephemeral port is added.
    ``port=None`` gives the official form (used for the logout redirect).
    """
    host = "http://localhost" if port is None else f"http://localhost:{port}"
    return host + CALLBACK_PATH


def _pkce_verifier() -> str:
    """96 characters from A-Za-z0-9 (random byte mod 62), like keycloak-js."""
    return "".join(_PKCE_ALPHABET[b % 62] for b in secrets.token_bytes(PKCE_VERIFIER_LENGTH))


def _encode(params: list[tuple[str, str]]) -> str:
    """Query or form encoding like encodeURIComponent (space is %20, not +)."""
    return urlencode(params, quote_via=quote)


def build_authorize_url(redirect: str, state: str, nonce: str, challenge: str) -> str:
    """Authorize URL with the parameters and order of keycloak-js 1.0.14."""
    return f"{AUTH_BASE}/auth?" + _encode(
        [
            ("client_id", CLIENT_ID),
            ("redirect_uri", redirect),
            ("state", state),
            ("response_mode", "query"),
            ("response_type", "code"),
            ("scope", SCOPE),
            ("nonce", nonce),
            ("code_challenge", challenge),
            ("code_challenge_method", "S256"),
        ]
    )


def build_logout_url(id_token: str) -> str:
    """Keycloak logout URL as the official client navigates to it."""
    return f"{AUTH_BASE}/logout?" + _encode(
        [
            ("client_id", CLIENT_ID),
            ("post_logout_redirect_uri", redirect_uri()),
            ("id_token_hint", id_token),
        ]
    )


def _accept_encoding(official: str) -> str:
    """The official Accept-Encoding minus what aiohttp cannot decode."""
    allowed = ("gzip", "deflate") + (("br",) if HAS_BROTLI else ())
    return ", ".join(e for e in official.split(", ") if e in allowed)


def chromium_token_headers() -> dict[str, str]:
    """Headers of the renderer fetch that posts to the token endpoint (no Origin)."""
    return {
        "User-Agent": UA_CHROMIUM,
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Accept-Encoding": _accept_encoding("gzip, deflate, br, zstd"),
        "Accept-Language": "en-US",
    }


def undici_revoke_headers() -> dict[str, str]:
    """Headers of the main-process undici fetch that posts to the revoke endpoint."""
    return {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Accept": "*/*",
        "Accept-Language": "*",
        "Sec-Fetch-Mode": "cors",
        "User-Agent": UA_UNDICI,
        "Accept-Encoding": _accept_encoding("br, gzip, deflate"),
    }


def decode_jwt(token: str) -> dict[str, Any]:
    """Claims of a JWT, unverified. Only used to read our own token's claims."""
    try:
        payload = token.split(".")[1]
        decoded: dict[str, Any] = json.loads(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        )
        return decoded
    except (IndexError, ValueError) as e:
        raise OIDCError(f"Malformed token: {e}") from e


@dataclass
class Tokens:
    access_token: str
    refresh_token: str
    expires_at: float  # unix time the access token stops being accepted
    claims: dict[str, Any]
    id_token: str = ""  # needed as id_token_hint for the Keycloak logout URL

    @classmethod
    def from_response(cls, data: dict[str, Any], previous_refresh: str = "") -> Tokens:
        if "access_token" not in data:
            raise OIDCError(f"Token response without access_token: {sorted(data)}")
        claims = decode_jwt(data["access_token"])
        exp = claims.get("exp")
        expires_at = float(exp) if exp else time.time() + float(data.get("expires_in", 300))
        return cls(
            access_token=data["access_token"],
            # Keycloak rotates the refresh token on use; keep the old one if not.
            refresh_token=data.get("refresh_token") or previous_refresh,
            expires_at=expires_at,
            claims=claims,
            id_token=data.get("id_token") or "",
        )

    @property
    def user_id(self) -> str:
        return str(self.claims.get("sub", ""))

    @property
    def username(self) -> str:
        c = self.claims
        return str(c.get("preferred_username") or c.get("email") or c.get("name") or "")

    def needs_refresh(self, margin: float = REFRESH_MARGIN_SECONDS) -> bool:
        return time.time() >= self.expires_at - margin

    @property
    def premium_tier(self) -> str | None:
        roles = (self.claims.get("realm_access") or {}).get("roles") or []
        if "premium-platinum" in roles:
            return "platinum"
        if "premium-gold" in roles:
            return "gold"
        return None

    @property
    def release_channels(self) -> list[str]:
        """Addon release channels this account may use, "release" always first."""
        roles = (self.claims.get("resource_access") or {}).get("app-addon-version", {}).get(
            "roles"
        ) or []
        extra = [r[8:] for r in roles if r.startswith("channel/") and r[8:] not in ("", "release")]
        return ["release", *extra]


async def _post_token(
    session: aiohttp.ClientSession, form: list[tuple[str, str]]
) -> dict[str, Any]:
    async with session.post(
        f"{AUTH_BASE}/token", data=_encode(form), headers=chromium_token_headers()
    ) as resp:
        try:
            data: dict[str, Any] = await resp.json(content_type=None)
        except (aiohttp.ContentTypeError, ValueError):
            resp.raise_for_status()
            raise
        if resp.status >= 500 or resp.status == 429:
            resp.raise_for_status()  # transient, let the caller retry
        if resp.status != 200 or "error" in data:
            raise OIDCError(data.get("error_description") or data.get("error") or str(resp.status))
        return data


async def browser_login(
    session: aiohttp.ClientSession,
    open_url: Callable[[str], object] = webbrowser.open,
    timeout: float = LOGIN_TIMEOUT_SECONDS,
    on_url: Callable[[str], None] | None = None,
) -> Tokens:
    """Run the full browser login and return the tokens.

    ``on_url`` receives the login URL so the UI can show it for copying, in case
    no browser opens.
    """
    verifier = _pkce_verifier()
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    state = str(uuid.uuid4())
    nonce = str(uuid.uuid4())
    loop = asyncio.get_running_loop()
    result: asyncio.Future[dict[str, str]] = loop.create_future()

    async def callback(request: web.Request) -> web.Response:
        q = dict(request.query)
        if q.get("state") != state:
            return web.Response(status=400, text="State mismatch")
        if not result.done():
            result.set_result(q)
        ok = "code" in q
        page = _DONE_PAGE.format(
            title="Signed in to TSM" if ok else "Sign-in failed",
            text="You can close this tab and return to the TSM Desktop App."
            if ok
            else q.get("error_description", q.get("error", "")),
        )
        return web.Response(text=page, content_type="text/html")

    app = web.Application()
    app.router.add_get(CALLBACK_PATH, callback)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", 0)
    await site.start()
    try:
        server = site._server
        sockets = getattr(server, "sockets", None) or []
        port = sockets[0].getsockname()[1]
        callback_uri = redirect_uri(port)
        url = build_authorize_url(callback_uri, state, nonce, challenge)
        if on_url is not None:
            on_url(url)
        logger.info("Opening the TSM login page in the browser (callback port %d)", port)
        await loop.run_in_executor(None, open_url, url)
        try:
            query = await asyncio.wait_for(result, timeout)
        except TimeoutError as e:
            raise LoginCancelled("Login timed out") from e
        # Let the browser receive the "you can close this tab" page.
        await asyncio.sleep(0.2)
    finally:
        await runner.cleanup()

    if "code" not in query:
        raise OIDCError(query.get("error_description") or query.get("error") or "Login failed")
    data = await _post_token(
        session,
        [
            ("code", query["code"]),
            ("grant_type", "authorization_code"),
            ("client_id", CLIENT_ID),
            ("redirect_uri", callback_uri),
            ("code_verifier", verifier),
        ],
    )
    tokens = Tokens.from_response(data)
    logger.info("Browser login complete")
    return tokens


async def refresh(session: aiohttp.ClientSession, refresh_token: str) -> Tokens:
    """Exchange a refresh token for fresh tokens. Raises OIDCError if it was revoked."""
    data = await _post_token(
        session,
        [
            ("grant_type", "refresh_token"),
            ("refresh_token", refresh_token),
            ("client_id", CLIENT_ID),
        ],
    )
    return Tokens.from_response(data, previous_refresh=refresh_token)


async def revoke(session: aiohttp.ClientSession, refresh_token: str) -> None:
    """Revoke the refresh token on logout. Best effort, like the official client."""
    try:
        async with session.post(
            f"{AUTH_BASE}/revoke",
            data=_encode(
                [
                    ("client_id", CLIENT_ID),
                    ("token", refresh_token),
                    ("token_type_hint", "refresh_token"),
                ]
            ),
            headers=undici_revoke_headers(),
            timeout=aiohttp.ClientTimeout(total=5),
        ):
            pass
    except Exception as e:
        logger.warning("Failed to revoke the refresh token: %s", e)
