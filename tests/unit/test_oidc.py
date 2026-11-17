"""Browser login (PKCE) and token handling."""

from __future__ import annotations

import base64
import hashlib
import json
import time
import urllib.request
import uuid
from urllib.parse import parse_qs, parse_qsl, urlparse

import aiohttp
import pytest
from aioresponses import aioresponses

from tsm.api import oidc
from tsm.api.official import UA_CHROMIUM


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
    assert [k for k, _ in parse_qsl(call.kwargs["data"])] == [
        "code",
        "grant_type",
        "client_id",
        "redirect_uri",
        "code_verifier",
    ]
    form = dict(parse_qsl(call.kwargs["data"]))
    assert form["grant_type"] == "authorization_code"
    assert form["code"] == "abc"
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest())
        .rstrip(b"=")
        .decode()
    )
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


def test_authorize_url_names_order_and_encoding():
    url = oidc.build_authorize_url("http://localhost:1234/auth/callback", "S", "N", "C")
    assert url.startswith(f"{oidc.AUTH_BASE}/auth?")
    query = urlparse(url).query
    assert [k for k, _ in parse_qsl(query)] == [
        "client_id",
        "redirect_uri",
        "state",
        "response_mode",
        "response_type",
        "scope",
        "nonce",
        "code_challenge",
        "code_challenge_method",
    ]
    q = dict(parse_qsl(query))
    assert q["response_mode"] == "query"
    assert q["response_type"] == "code"
    assert q["scope"] == "openid roles profile email tsm-profile offline_access"
    assert "scope=openid%20roles%20profile" in query
    assert "+" not in query


def test_redirect_uri_is_built_in_one_place():
    assert oidc.redirect_uri() == "http://localhost/auth/callback"
    assert oidc.redirect_uri(4321) == "http://localhost:4321/auth/callback"


def test_pkce_verifier_format():
    v = oidc._pkce_verifier()
    assert len(v) == 96
    assert v.isascii() and v.isalnum()


@pytest.mark.asyncio
async def test_login_url_has_uuid_state_and_separate_nonce():
    seen: dict[str, str] = {}

    def fake_browser(url: str) -> None:
        seen.update(dict(parse_qsl(urlparse(url).query)))

    async with aiohttp.ClientSession() as session:
        with pytest.raises(oidc.LoginCancelled):
            await oidc.browser_login(session, open_url=fake_browser, timeout=0.3)
    assert uuid.UUID(seen["state"]).version == 4
    assert uuid.UUID(seen["nonce"]).version == 4
    assert seen["state"] != seen["nonce"]
    assert len(base64.urlsafe_b64decode(seen["code_challenge"] + "=")) == 32


@pytest.mark.asyncio
async def test_token_request_headers_are_chromium_without_origin():
    async with aiohttp.ClientSession() as session:
        with aioresponses() as m:
            m.post(f"{oidc.AUTH_BASE}/token", payload={"access_token": _jwt(CLAIMS)})
            await oidc.refresh(session, "r-old")
            call = next(iter(m.requests.values()))[0]
    h = call.kwargs["headers"]
    assert h["User-Agent"] == UA_CHROMIUM
    assert "tsm-app-linux" not in h["User-Agent"]
    assert h["Accept"] == "application/json"
    assert h["Content-Type"] == "application/x-www-form-urlencoded;charset=UTF-8"
    assert h["Accept-Language"] == "en-US"
    assert (h["Sec-Fetch-Site"], h["Sec-Fetch-Mode"], h["Sec-Fetch-Dest"]) == (
        "cross-site",
        "cors",
        "empty",
    )
    assert not {"Origin", "Authorization", "Cookie"} & set(h)
    assert call.kwargs["data"] == (
        "grant_type=refresh_token&refresh_token=r-old&client_id=desktop-app"
    )


@pytest.mark.asyncio
async def test_revoke_request_is_undici_form_without_auth():
    async with aiohttp.ClientSession() as session:
        with aioresponses() as m:
            m.post(f"{oidc.AUTH_BASE}/revoke", status=200)
            await oidc.revoke(session, "r-old")
            call = next(iter(m.requests.values()))[0]
    h = call.kwargs["headers"]
    assert h["User-Agent"] == "node"
    assert h["Accept"] == "*/*"
    assert h["Accept-Language"] == "*"
    assert h["Sec-Fetch-Mode"] == "cors"
    assert h["Content-Type"] == "application/x-www-form-urlencoded;charset=UTF-8"
    assert "br" in h["Accept-Encoding"] or not oidc.HAS_BROTLI
    assert not {"Origin", "Authorization", "Cookie"} & set(h)
    assert call.kwargs["data"] == (
        "client_id=desktop-app&token=r-old&token_type_hint=refresh_token"
    )


def test_logout_url_parameters():
    url = oidc.build_logout_url("IDT")
    assert url.startswith(f"{oidc.AUTH_BASE}/logout?")
    pairs = parse_qsl(urlparse(url).query)
    assert pairs == [
        ("client_id", "desktop-app"),
        ("post_logout_redirect_uri", "http://localhost/auth/callback"),
        ("id_token_hint", "IDT"),
    ]


def test_id_token_is_kept_for_the_logout_hint():
    t = oidc.Tokens.from_response({"access_token": _jwt(CLAIMS), "id_token": "idt"})
    assert t.id_token == "idt"
