"""Browser login (PKCE) and token handling."""

from __future__ import annotations

import base64
import hashlib
import json
import time
import urllib.request
from urllib.parse import parse_qs, urlparse

import aiohttp
import pytest
from aioresponses import aioresponses

from tsm.api import oidc


def _jwt(claims: dict) -> str:
    def enc(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    return f"{enc({'alg': 'none'})}.{enc(claims)}.sig"


CLAIMS = {
    "sub": "user-1",
    "preferred_username": "someone",
    "exp": int(time.time()) + 300,
    "realm_access": {"roles": ["premium-gold"]},
    "resource_access": {"app-addon-version": {"roles": ["channel/beta"]}},
}


def test_token_claims():
    t = oidc.Tokens.from_response({"access_token": _jwt(CLAIMS), "refresh_token": "r"})
    assert t.user_id == "user-1"
    assert t.username == "someone"
    assert t.premium_tier == "gold"
    assert t.release_channels == ["release", "beta"]
    assert not t.needs_refresh()
    assert t.needs_refresh(margin=301)


def test_refresh_keeps_the_old_refresh_token_when_none_comes_back():
    t = oidc.Tokens.from_response({"access_token": _jwt(CLAIMS)}, previous_refresh="old")
    assert t.refresh_token == "old"


@pytest.mark.asyncio
async def test_browser_login_round_trip():
    seen: dict[str, str] = {}

    def fake_browser(url: str) -> None:
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        seen.update(q)
        cb = f"{q['redirect_uri']}?state={q['state']}&code=abc"
        with urllib.request.urlopen(cb) as resp:  # noqa: S310 - local callback
            seen["page"] = resp.read().decode()

    async with aiohttp.ClientSession() as session:
        with aioresponses(passthrough=["http://localhost"]) as m:
            m.post(
                f"{oidc.AUTH_BASE}/token",
                payload={"access_token": _jwt(CLAIMS), "refresh_token": "r1"},
            )
            tokens = await oidc.browser_login(session, open_url=fake_browser, timeout=10)
            call = next(iter(m.requests.values()))[0]
    assert tokens.refresh_token == "r1"
    assert seen["client_id"] == "desktop-app"
    assert seen["code_challenge_method"] == "S256"
    assert seen["redirect_uri"].startswith("http://localhost:")
    assert seen["redirect_uri"].endswith("/auth/callback")
    assert "offline_access" in seen["scope"]
    form = call.kwargs["data"]
    assert form["grant_type"] == "authorization_code"
    assert form["code"] == "abc"
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(form["code_verifier"].encode()).digest()
    ).rstrip(b"=").decode()
    assert challenge == seen["code_challenge"]
    assert "Signed in" in seen["page"]


@pytest.mark.asyncio
async def test_wrong_state_is_rejected_and_login_times_out():
    def fake_browser(url: str) -> None:
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        try:
            urllib.request.urlopen(f"{q['redirect_uri']}?state=evil&code=x")  # noqa: S310
        except urllib.error.HTTPError as e:
            assert e.code == 400

    async with aiohttp.ClientSession() as session:
        with pytest.raises(oidc.LoginCancelled):
            await oidc.browser_login(session, open_url=fake_browser, timeout=0.5)


@pytest.mark.asyncio
async def test_rejected_refresh_raises_oidc_error():
    async with aiohttp.ClientSession() as session:
        with aioresponses() as m:
            m.post(
                f"{oidc.AUTH_BASE}/token",
                status=400,
                payload={"error": "invalid_grant", "error_description": "Token is not active"},
            )
            with pytest.raises(oidc.OIDCError, match="not active"):
                await oidc.refresh(session, "r")


@pytest.mark.asyncio
async def test_server_error_on_refresh_is_transient():
    from tsm.api.client import is_transient_error

    async with aiohttp.ClientSession() as session:
        with aioresponses() as m:
            m.post(f"{oidc.AUTH_BASE}/token", status=503, payload={"error": "x"})
            with pytest.raises(aiohttp.ClientResponseError) as ei:
                await oidc.refresh(session, "r")
    assert is_transient_error(ei.value)
