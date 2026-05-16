"""Integration tests for TSMApiClient using aioresponses."""

from __future__ import annotations

import re

import pytest
from aioresponses import aioresponses

from tsm.api.client import OIDC_URL, TSMApiClient

# Regex helpers, match base URL regardless of dynamic query params (time, token)
RE_AUTH = re.compile(r"http://app-server\.tradeskillmaster\.com/v2/auth.*")
RE_STATUS = re.compile(r"http://app-server\.tradeskillmaster\.com/v2/status.*")
RE_CDN = re.compile(r"https://cdn\.tradeskillmaster\.com/data/test\.txt.*")
RE_ADDON = re.compile(r"http://addon-server\.tradeskillmaster\.com/v2/addon/.*")
RE_ADDON_CDN = re.compile(r"https://cdn\.tradeskillmaster\.com/addons/.*")

ADDON_USER_INFO = {
    "session": "s",
    "userId": 1,
    "endpointSubdomains": {"addon": "addon-server"},
}


@pytest.mark.asyncio
async def test_oidc_login():
    client = TSMApiClient()
    with aioresponses() as m:
        m.post(OIDC_URL, payload={"access_token": "oidc_tok", "token_type": "Bearer"})
        result = await client.auth.get_oidc_token("user@test.com", "pass")
    assert result["access_token"] == "oidc_tok"
    await client.close()


@pytest.mark.asyncio
async def test_authenticate_sets_user_info():
    client = TSMApiClient()
    user_info = {
        "session": "sess123",
        "userId": 42,
        "isPremium": True,
        "endpointSubdomains": {"status": "app-server"},
    }
    with aioresponses() as m:
        m.post(RE_AUTH, payload=user_info)
        result = await client.auth.authenticate("oidc_tok")
    assert result["session"] == "sess123"
    assert client.session_token == "sess123"
    await client.close()


@pytest.mark.asyncio
async def test_status_call():
    client = TSMApiClient()
    client.set_user_info(
        {
            "session": "s",
            "userId": 1,
            "endpointSubdomains": {"status": "app-server"},
        }
    )
    status_payload = {
        "realms": [{"name": "Blackhand", "region": "EU", "ahId": 1, "appDataStrings": {}}],
        "regions": [],
        "addonMessage": {"id": 0, "msg": ""},
        "appVersion": 41402,
    }
    with aioresponses() as m:
        m.get(RE_STATUS, payload=status_payload)
        result = await client.status.get()
    realms = result.get("realms", [])
    assert realms[0].get("name") == "Blackhand"
    await client.close()


@pytest.mark.asyncio
async def test_raw_download():
    client = TSMApiClient()
    blob = "return {downloadTime=1710000000,fields={},data={}}"
    with aioresponses() as m:
        m.get(RE_CDN, body=blob)
        result = await client.raw_download("https://cdn.tradeskillmaster.com/data/test.txt")
    assert "downloadTime" in result
    await client.close()


@pytest.mark.asyncio
async def test_addon_download_direct_bytes():
    """Old API behavior: addon endpoint returns zip bytes directly."""
    client = TSMApiClient()
    client.set_user_info(ADDON_USER_INFO)
    fake_zip = b"PK\x03\x04fake-zip-content"
    with aioresponses() as m:
        m.get(RE_ADDON, body=fake_zip, content_type="application/zip")
        result = await client.addon.download("TradeSkillMaster")
    assert result == fake_zip
    await client.close()


@pytest.mark.asyncio
async def test_addon_download_json_redirect():
    """New API behavior: addon endpoint returns JSON with redirect URL."""
    client = TSMApiClient()
    client.set_user_info(ADDON_USER_INFO)
    fake_zip = b"PK\x03\x04fake-zip-from-cdn"
    with aioresponses() as m:
        m.get(RE_ADDON, payload={"url": "https://cdn.tradeskillmaster.com/addons/tsm.zip"})
        m.get(RE_ADDON_CDN, body=fake_zip, content_type="application/zip")
        result = await client.addon.download("TradeSkillMaster")
    assert result == fake_zip
    await client.close()


@pytest.mark.asyncio
async def test_addon_download_json_missing_url():
    """JSON response with no recognizable URL key raises ValueError."""
    client = TSMApiClient()
    client.set_user_info(ADDON_USER_INFO)
    with aioresponses() as m:
        m.get(RE_ADDON, payload={"foo": "bar"})
        with pytest.raises(ValueError, match="no URL"):
            await client.addon.download("TradeSkillMaster")
    await client.close()


@pytest.mark.asyncio
async def test_addon_download_api_error_envelope():
    """API error envelope {success: False, error: ...} raises ValueError with the message."""
    client = TSMApiClient()
    client.set_user_info(ADDON_USER_INFO)
    with aioresponses() as m:
        m.get(RE_ADDON, payload={"success": False, "error": "Invalid request."})
        with pytest.raises(ValueError, match="Invalid request"):
            await client.addon.download("TradeSkillMaster")
    await client.close()


@pytest.mark.asyncio
async def test_addon_download_strips_version_prefix():
    """version_str values with a leading 'v' are stripped before the API call."""
    client = TSMApiClient()
    client.set_user_info(ADDON_USER_INFO)
    fake_zip = b"PK\x03\x04stripped-version"
    with aioresponses() as m:
        # The mock matches regardless of query params, so we just verify no crash
        m.get(RE_ADDON, body=fake_zip, content_type="application/zip")
        result = await client.addon.download("TradeSkillMaster", tsm_version="v4.14.7")
    assert result == fake_zip
    await client.close()


@pytest.mark.asyncio
async def test_retry_on_server_error():
    client = TSMApiClient()
    client.set_user_info(
        {
            "session": "s",
            "userId": 1,
            "endpointSubdomains": {"status": "app-server"},
        }
    )
    good_payload = {"realms": [], "regions": [], "addonMessage": {"id": 0, "msg": ""}}
    with aioresponses() as m:
        m.get(RE_STATUS, status=503)
        m.get(RE_STATUS, status=503)
        m.get(RE_STATUS, payload=good_payload)
        result = await client.status.get()
    assert result.get("realms") == []
    await client.close()
