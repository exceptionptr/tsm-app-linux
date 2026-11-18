"""TSM account login: OpenID Connect authorization code flow with PKCE.

Matches the official 1.0.14 client (keycloak-js inside Electron): same authorize
parameters in the same order, same PKCE, state and nonce formats, and the token,
refresh and revoke requests with the headers the official channels send. The
token calls go through aiohttp with the Chromium header set (no Origin, no
cookie; TLS differs), because a page fetch cannot read Keycloak's error answers
(no CORS headers on 4xx). The revoke call carries the undici set. The login page runs
in an embedded Chromium window (tsm/ui/login_window.py) and the redirect_uri is
the official one, http://localhost/auth/callback, which the window catches before
it reaches the network. No system browser and no listener are involved.

The desktop-app client refuses the password grant ("Client not allowed for
direct access grants"), so the login page is the only way in. In exchange the app
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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, quote_plus, urlencode

import aiohttp
from aiohttp.compression_utils import HAS_BROTLI
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from tsm.api.chromium import SEC_CH_UA
from tsm.api.http import AUTO, UNDICI_SSL
from tsm.api.official import UA_CHROMIUM, UA_UNDICI

logger = logging.getLogger(__name__)

LoginFlow = Callable[[str], Awaitable[dict[str, str]]]
UserAgentFn = Callable[[], str]

AUTH_BASE = "https://id.tradeskillmaster.com/realms/app/protocol/openid-connect"
CLIENT_ID = "desktop-app"
SCOPE = "openid roles profile email tsm-profile offline_access"
CALLBACK_PATH = "/auth/callback"
# The official client refreshes when fewer than 90 s of validity remain.
REFRESH_MARGIN_SECONDS = 90
LOGIN_TIMEOUT_SECONDS = 600
# Token requests are short: a stuck connect must end in an error, not in silence.
TOKEN_TIMEOUT = aiohttp.ClientTimeout(total=30, sock_connect=10)
PKCE_VERIFIER_LENGTH = 96
_PKCE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"

class OIDCError(RuntimeError):
    """The identity server refused a request (bad grant, revoked token, ...)."""


class LoginCancelled(RuntimeError):
    """The login was abandoned or timed out."""


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def redirect_uri() -> str:
    """The OAuth redirect URI, the one place it is built (official, no port)."""
    return "http://localhost" + CALLBACK_PATH


def _pkce_verifier() -> str:
    """96 characters from A-Za-z0-9 (random byte mod 62), like keycloak-js."""
    return "".join(_PKCE_ALPHABET[b % 62] for b in secrets.token_bytes(PKCE_VERIFIER_LENGTH))


def _encode(params: list[tuple[str, str]]) -> str:
    """Query or form encoding like encodeURIComponent (space is %20, not +)."""
    return urlencode(params, quote_via=quote)


def build_authorize_url(redirect: str, state: str, nonce: str, challenge: str) -> str:
    """Authorize URL with the parameters and order of keycloak-js 1.0.14 (space is +)."""
    return f"{AUTH_BASE}/auth?" + urlencode(
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
        ],
        quote_via=quote_plus,  # the official authorize URL has scope=openid+roles+...
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


def chromium_token_headers(user_agent: str = UA_CHROMIUM) -> dict[str, str]:
    """Headers of the renderer fetch that posts to the token endpoint.

    Order and casing as captured (HTTP/2, so lower case). No Origin and no cookie,
    like the capture; Host and Content-Length are placed by aiohttp.
    """
    return {
        "host": AUTO,
        "content-length": AUTO,
        "sec-ch-ua-platform": '"Linux"',
        "user-agent": user_agent,
        "accept": "application/json",
        "sec-ch-ua": SEC_CH_UA,
        "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
        "sec-ch-ua-mobile": "?0",
        "sec-fetch-site": "cross-site",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "sec-fetch-storage-access": "active",
        "accept-encoding": _accept_encoding("gzip, deflate, br, zstd"),
        "accept-language": "en-US",
        "priority": "u=1, i",
    }


def undici_revoke_headers() -> dict[str, str]:
    """Headers of the main-process undici fetch that posts to the revoke endpoint.

    Same order and casing as client.undici_headers() without Authorization.
    """
    return {
        "host": AUTO,
        "connection": AUTO,
        "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
        "accept": "*/*",
        "accept-language": "*",
        "sec-fetch-mode": "cors",
        "user-agent": UA_UNDICI,
        "accept-encoding": _accept_encoding("br, gzip, deflate"),
        "content-length": AUTO,
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


def _read_token_answer(status: int, text: str) -> dict[str, Any]:
    """Tokens (or the error) from a token endpoint answer."""
    try:
        data: dict[str, Any] = json.loads(text)
    except ValueError:
        if status >= 400:
            raise _status_error(status) from None
        raise
    if status >= 500 or status == 429:
        raise _status_error(status)  # transient, let the caller retry
    if status != 200 or "error" in data:
        raise OIDCError(data.get("error_description") or data.get("error") or str(status))
    return data


def _status_error(status: int) -> aiohttp.ClientResponseError:
    request_info = aiohttp.RequestInfo(
        url=URL(f"{AUTH_BASE}/token"),
        method="POST",
        headers=CIMultiDictProxy(CIMultiDict()),
        real_url=URL(f"{AUTH_BASE}/token"),
    )
    return aiohttp.ClientResponseError(request_info, (), status=status)


async def _post_token(
    session: aiohttp.ClientSession,
    form: list[tuple[str, str]],
    user_agent: UserAgentFn | None = None,
) -> dict[str, Any]:
    """POST the form to the token endpoint with the Chromium header set.

    A 4xx answer is readable here: invalid_grant raises OIDCError (the token is
    rejected), network errors and 5xx/429 raise aiohttp errors (transient).
    """
    headers = chromium_token_headers(user_agent() if user_agent is not None else UA_CHROMIUM)
    grant = dict(form).get("grant_type", "")
    try:
        async with session.post(
            f"{AUTH_BASE}/token",
            data=_encode(form),
            headers=headers,
            timeout=TOKEN_TIMEOUT,
        ) as resp:
            text = await resp.text()
            data = _read_token_answer(resp.status, text)
    except TimeoutError as e:
        logger.info("Token request failed (%s): timeout", grant)
        raise TimeoutError("Token request timeout: no answer from the TSM login server") from e
    except (aiohttp.ClientError, OIDCError, ValueError) as e:
        # The message carries no form data, so no code, verifier or token.
        logger.info("Token request failed (%s): %s: %s", grant, type(e).__name__, e)
        raise
    logger.info("Token request answered (%s)", grant)
    return data


def _check_nonce(id_token: object, nonce: str) -> None:
    """Like keycloak-js: an id_token whose nonce is not ours is not adopted.

    The signature is not checked (the token came over TLS from the token endpoint);
    this guards against a response that belongs to another login.
    """
    if not id_token:
        return
    if not isinstance(id_token, str):
        raise OIDCError("Invalid id_token")
    if decode_jwt(id_token).get("nonce") != nonce:
        raise OIDCError("Nonce mismatch")


async def window_login(
    session: aiohttp.ClientSession,
    open_window: LoginFlow,
    timeout: float = LOGIN_TIMEOUT_SECONDS,
    user_agent: UserAgentFn | None = None,
) -> Tokens:
    """Run the full login in the embedded window and return the tokens.

    ``open_window`` shows the authorize URL and resolves to the query of the
    callback (``code``/``state`` or ``error``). Cancelling or timing out the wait
    makes it close the window.
    """
    verifier = _pkce_verifier()
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    state = str(uuid.uuid4())
    nonce = str(uuid.uuid4())
    callback_uri = redirect_uri()
    url = build_authorize_url(callback_uri, state, nonce, challenge)
    logger.info("Opening the TSM login window")
    try:
        query = await asyncio.wait_for(open_window(url), timeout)
    except TimeoutError as e:
        raise LoginCancelled("Login timed out") from e
    if query.get("state") != state:
        raise OIDCError("State mismatch")
    if "code" not in query:
        raise OIDCError(query.get("error_description") or query.get("error") or "Login failed")
    logger.info("Exchanging the login code")
    data = await _post_token(
        session,
        [
            ("code", query["code"]),
            ("grant_type", "authorization_code"),
            ("client_id", CLIENT_ID),
            ("redirect_uri", callback_uri),
            ("code_verifier", verifier),
        ],
        user_agent,
    )
    _check_nonce(data.get("id_token"), nonce)
    tokens = Tokens.from_response(data)
    logger.info("Login complete")
    return tokens


async def refresh(
    session: aiohttp.ClientSession, refresh_token: str, user_agent: UserAgentFn | None = None
) -> Tokens:
    """Exchange a refresh token for fresh tokens. Raises OIDCError if it was revoked."""
    data = await _post_token(
        session,
        [
            ("grant_type", "refresh_token"),
            ("refresh_token", refresh_token),
            ("client_id", CLIENT_ID),
        ],
        user_agent,
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
            ssl=UNDICI_SSL,
            timeout=aiohttp.ClientTimeout(total=5),
        ):
            pass
    except Exception as e:
        logger.warning("Failed to revoke the refresh token: %s", e)
