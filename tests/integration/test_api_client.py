"""TSMApiClient against mocked TSM services (aioresponses)."""

from __future__ import annotations

import gzip
import re

import pytest
from aioresponses import aioresponses
from yarl import URL

from tsm.api.client import (
    ADDON_VERSION_API,
    DESKTOP_BACKEND,
    REALM_API,
    TSMApiClient,
    TSMApiError,
)


async def _client() -> TSMApiClient:
    c = TSMApiClient()

    async def token() -> str:
        return "tok"

    c.set_token_provider(token)
    return c


def _auth(m: aioresponses, method: str, url: str) -> str:
    calls = m.requests[(method, URL(url))]
    return calls[0].kwargs["headers"]["Authorization"]


@pytest.mark.asyncio
async def test_realms_use_bearer_auth():
    c = await _client()
    with aioresponses() as m:
        m.get(f"{REALM_API}/v2/realms", payload={"items": [{"realmId": 1}], "metadata": {}})
        assert await c.realms() == [{"realmId": 1}]
        assert _auth(m, "GET", f"{REALM_API}/v2/realms") == "Bearer tok"
    await c.close()


@pytest.mark.asyncio
async def test_game_versions_and_regions():
    c = await _client()
    gv = [{"gameType": "forever", "label": "Forever", "folder": "_forever_"}]
    with aioresponses() as m:
        m.get(f"{DESKTOP_BACKEND}/game-versions", payload=gv)
        m.get(f"{REALM_API}/v2/regions", payload={"items": [{"regionId": 2}]})
        assert await c.game_versions() == gv
        assert await c.regions() == [{"regionId": 2}]
    await c.close()


@pytest.mark.asyncio
async def test_user_realm_crud():
    c = await _client()
    with aioresponses() as m:
        m.get(
            re.compile(rf"{re.escape(DESKTOP_BACKEND)}/user-realms\?userIds=u1"),
            payload={"items": [{"id": "usr_rlm_1", "realmId": 300}]},
        )
        m.post(f"{DESKTOP_BACKEND}/user-realms", payload={})
        m.delete(f"{DESKTOP_BACKEND}/user-realms/usr_rlm_1", status=204)
        assert (await c.user_realms("u1"))[0]["id"] == "usr_rlm_1"
        await c.add_user_realm("u1", 706, "horde")
        await c.delete_user_realm("usr_rlm_1")
        post = next(v for k, v in m.requests.items() if k[0] == "POST")[0]
        assert post.kwargs["json"] == {"realmId": 706, "userId": "u1", "auctionHouseType": "HORDE"}
    await c.close()


@pytest.mark.asyncio
async def test_error_message_from_body_and_no_retry_on_4xx():
    c = await _client()
    with aioresponses() as m:
        m.post(f"{DESKTOP_BACKEND}/user-realms", status=400, payload={"message": "Limit reached"})
        with pytest.raises(TSMApiError, match="Limit reached") as ei:
            await c.add_user_realm("u", 1, "ALL")
    assert ei.value.status == 400
    await c.close()


@pytest.mark.asyncio
async def test_server_error_is_retried(monkeypatch):
    import tsm.api.client as mod

    monkeypatch.setattr(mod, "RETRY_DELAY", 0)
    c = await _client()
    with aioresponses() as m:
        m.get(f"{REALM_API}/v2/regions", status=502)
        m.get(f"{REALM_API}/v2/regions", payload={"items": []})
        assert await c.regions() == []
    await c.close()


@pytest.mark.asyncio
async def test_channels_forbidden_means_none():
    c = await _client()
    with aioresponses() as m:
        m.get(f"{ADDON_VERSION_API}/channels", status=403)
        assert await c.release_channel_labels() == []
    await c.close()


@pytest.mark.asyncio
async def test_download_gunzips_and_maps_404_to_none(monkeypatch):
    import tsm.api.client as mod

    sleeps: list[float] = []

    async def fake_sleep(d: float) -> None:
        sleeps.append(d)

    monkeypatch.setattr(mod.asyncio, "sleep", fake_sleep)
    c = TSMApiClient()
    with aioresponses() as m:
        m.get("https://blob/a", body=gzip.compress(b"{x=1}"))
        m.get("https://blob/b", status=404)
        m.get("https://blob/c", status=503)
        m.get("https://blob/c", body=b"{y=2}")
        assert await c.download("https://blob/a") == b"{x=1}"
        assert await c.download("https://blob/b") is None
        assert await c.download("https://blob/c") == b"{y=2}"
    assert sleeps == [1.0]
    await c.close()


@pytest.mark.asyncio
async def test_unauthenticated_request_fails_fast():
    c = TSMApiClient()
    with pytest.raises(RuntimeError, match="Not authenticated"):
        await c.realms()
    await c.close()
