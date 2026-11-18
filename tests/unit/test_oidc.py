"""Browser login (PKCE) and token handling."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
import uuid
from urllib.parse import parse_qsl, urlparse

import aiohttp
import pytest
from aioresponses import aioresponses

from tsm.api import chromium, oidc
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


def _flow(seen: dict[str, str], **extra: str):
    """A fake login window: records the authorize URL and answers with the callback."""

    async def open_window(url: str) -> dict[str, str]:
        q = dict(parse_qsl(urlparse(url).query))
        seen.update(q)
        return {"state": q["state"], "code": "abc", **extra}

    return open_window


@pytest.mark.asyncio
async def test_window_login_round_trip():
    seen: dict[str, str] = {}
    async with aiohttp.ClientSession() as session:
        with aioresponses() as m:
            m.post(
                f"{oidc.AUTH_BASE}/token",
                payload={"access_token": _jwt(CLAIMS), "refresh_token": "r1"},
            )
            tokens = await oidc.window_login(session, _flow(seen), timeout=10)
            call = next(iter(m.requests.values()))[0]
    assert tokens.refresh_token == "r1"
    assert seen["client_id"] == "desktop-app"
    assert seen["code_challenge_method"] == "S256"
    assert seen["redirect_uri"] == "http://localhost/auth/callback"
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
    assert form["redirect_uri"] == "http://localhost/auth/callback"
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert challenge == seen["code_challenge"]


@pytest.mark.asyncio
async def test_wrong_state_is_rejected():
    async def open_window(url: str) -> dict[str, str]:
        return {"state": "evil", "code": "x"}

    async with aiohttp.ClientSession() as session:
        with pytest.raises(oidc.OIDCError, match="State mismatch"):
            await oidc.window_login(session, open_window, timeout=5)


@pytest.mark.asyncio
async def test_login_error_from_the_callback_is_raised():
    async def open_window(url: str) -> dict[str, str]:
        state = dict(parse_qsl(urlparse(url).query))["state"]
        return {"state": state, "error": "access_denied", "error_description": "Nope"}

    async with aiohttp.ClientSession() as session:
        with pytest.raises(oidc.OIDCError, match="Nope"):
            await oidc.window_login(session, open_window, timeout=5)


@pytest.mark.asyncio
async def test_login_times_out_and_cancels_the_window():
    cancelled = asyncio.Event()

    async def open_window(url: str) -> dict[str, str]:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return {}

    async with aiohttp.ClientSession() as session:
        with pytest.raises(oidc.LoginCancelled):
            await oidc.window_login(session, open_window, timeout=0.2)
    assert cancelled.is_set()


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
    assert "scope=openid+roles+profile+email+tsm-profile+offline_access" in query
    assert "%20" not in query


def test_redirect_uri_is_built_in_one_place():
    assert oidc.redirect_uri() == "http://localhost/auth/callback"


def test_pkce_verifier_format():
    v = oidc._pkce_verifier()
    assert len(v) == 96
    assert v.isascii() and v.isalnum()


@pytest.mark.asyncio
async def test_login_url_has_uuid_state_and_separate_nonce():
    seen: dict[str, str] = {}

    async def open_window(url: str) -> dict[str, str]:
        seen.update(dict(parse_qsl(urlparse(url).query)))
        raise oidc.LoginCancelled("closed")

    async with aiohttp.ClientSession() as session:
        with pytest.raises(oidc.LoginCancelled):
            await oidc.window_login(session, open_window, timeout=5)
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
    assert h["user-agent"] == UA_CHROMIUM
    assert "tsm-app-linux" not in h["user-agent"]
    assert h["accept"] == "application/json"
    assert h["content-type"] == "application/x-www-form-urlencoded;charset=UTF-8"
    assert h["accept-language"] == "en-US"
    assert h["priority"] == "u=1, i"
    assert h["sec-ch-ua"] == chromium.SEC_CH_UA
    assert (h["sec-fetch-site"], h["sec-fetch-mode"], h["sec-fetch-dest"]) == (
        "cross-site",
        "cors",
        "empty",
    )
    assert h["sec-fetch-storage-access"] == "active"
    assert not {"origin", "authorization", "cookie"} & {k.lower() for k in h}
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
    assert h["user-agent"] == "node"
    assert h["accept"] == "*/*"
    assert h["accept-language"] == "*"
    assert h["sec-fetch-mode"] == "cors"
    assert h["content-type"] == "application/x-www-form-urlencoded;charset=UTF-8"
    assert "br" in h["accept-encoding"] or not oidc.HAS_BROTLI
    assert not {"origin", "authorization", "cookie", "sentry-trace", "baggage"} & {
        k.lower() for k in h
    }
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


@pytest.mark.asyncio
async def test_refresh_rotates_the_token():
    async with aiohttp.ClientSession() as session:
        with aioresponses() as m:
            m.post(
                f"{oidc.AUTH_BASE}/token",
                payload={"access_token": _jwt(CLAIMS), "refresh_token": "r-new"},
            )
            tokens = await oidc.refresh(session, "r-old")
    assert tokens.refresh_token == "r-new"


@pytest.mark.asyncio
async def test_network_error_on_refresh_is_transient():
    from tsm.api.client import is_transient_error

    async with aiohttp.ClientSession() as session:
        with aioresponses() as m:
            m.post(f"{oidc.AUTH_BASE}/token", exception=aiohttp.ClientConnectionError("down"))
            with pytest.raises(aiohttp.ClientError) as ei:
                await oidc.refresh(session, "r")
    assert is_transient_error(ei.value)


@pytest.mark.asyncio
async def test_token_request_uses_the_live_user_agent_and_captured_order(monkeypatch):
    from aiohttp import web

    from tsm.api.http import OrderedRequest

    seen: list[list[tuple[str, str]]] = []

    async def handler(request: web.Request) -> web.Response:
        seen.append([(k.decode(), v.decode()) for k, v in request.raw_headers])
        return web.json_response({"access_token": _jwt(CLAIMS)})

    app = web.Application()
    app.router.add_post("/token", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    port = runner.addresses[0][1]
    monkeypatch.setattr(oidc, "AUTH_BASE", f"http://127.0.0.1:{port}")
    try:
        async with aiohttp.ClientSession(request_class=OrderedRequest) as session:
            await oidc.refresh(session, "r", lambda: "UA-LIVE/9.9")
    finally:
        await runner.cleanup()
    names = [k for k, _ in seen[0]]
    assert names == list(oidc.chromium_token_headers())
    assert dict(seen[0])["user-agent"] == "UA-LIVE/9.9"
    assert not {"origin", "cookie", "authorization"} & {n.lower() for n in names}


def _answer(seen, nonce_of=lambda n: n, id_token=None):
    from aioresponses import CallbackResult

    def body(url, **kwargs) -> CallbackResult:
        token = id_token if id_token is not None else _jwt({"nonce": nonce_of(seen["nonce"])})
        return CallbackResult(
            status=200,
            payload={"access_token": _jwt(CLAIMS), "refresh_token": "r1", "id_token": token},
        )

    return body


async def _login_with(callback, seen) -> oidc.Tokens:
    async with aiohttp.ClientSession() as session:
        with aioresponses() as m:
            m.post(f"{oidc.AUTH_BASE}/token", callback=callback)
            return await oidc.window_login(session, _flow(seen), timeout=5)


@pytest.mark.asyncio
async def test_matching_nonce_is_accepted():
    seen: dict[str, str] = {}
    tokens = await _login_with(_answer(seen), seen)
    assert tokens.refresh_token == "r1"


@pytest.mark.asyncio
async def test_nonce_mismatch_is_not_adopted():
    seen: dict[str, str] = {}
    with pytest.raises(oidc.OIDCError, match="Nonce mismatch"):
        await _login_with(_answer(seen, lambda n: "other"), seen)


@pytest.mark.asyncio
async def test_id_token_without_nonce_or_malformed_is_not_adopted():
    seen: dict[str, str] = {}
    with pytest.raises(oidc.OIDCError):
        await _login_with(_answer(seen, id_token="not-a-jwt"), seen)
    with pytest.raises(oidc.OIDCError, match="Nonce mismatch"):
        await _login_with(_answer(seen, id_token=_jwt({})), seen)


def test_token_post_has_a_short_timeout_and_a_readable_error():
    async def run() -> None:
        async with aiohttp.ClientSession() as session:
            with aioresponses() as m:
                m.post(f"{oidc.AUTH_BASE}/token", exception=TimeoutError())
                with pytest.raises(TimeoutError, match="Token request timeout"):
                    await oidc._post_token(session, [("grant_type", "refresh_token")])
                (call,) = m.requests[("POST", oidc.URL(f"{oidc.AUTH_BASE}/token"))]
                timeout = call.kwargs["timeout"]
                assert timeout.total == 30
                assert timeout.sock_connect == 10

    asyncio.run(run())


def test_login_error_texts_for_a_token_timeout():
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    from tsm.ui.views.login import format_auth_error

    msg = format_auth_error("Token request timeout: no answer from the TSM login server")
    assert "reach TSM servers" in msg
