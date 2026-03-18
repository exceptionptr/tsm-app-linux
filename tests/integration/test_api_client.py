"""Integration tests for TSMApiClient using aioresponses."""

from __future__ import annotations

import re

import pytest
from aioresponses import aioresponses

from tsm.api.client import OIDC_URL, TSMApiClient

# Regex helpers — match base URL regardless of dynamic query params (time, token)
RE_AUTH = re.compile(r"http://app-server\.tradeskillmaster\.com/v2/auth.*")
RE_STATUS = re.compile(r"http://app-server\.tradeskillmaster\.com/v2/status.*")
RE_CDN = re.compile(r"https://cdn\.tradeskillmaster\.com/data/test\.txt.*")


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
            "isPremium": False,
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
    assert result["realms"][0]["name"] == "Blackhand"
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
async def test_retry_on_server_error():
    client = TSMApiClient()
    client.set_user_info(
        {
            "session": "s",
            "userId": 1,
            "isPremium": False,
            "endpointSubdomains": {"status": "app-server"},
        }
    )
    good_payload = {"realms": [], "regions": [], "addonMessage": {"id": 0, "msg": ""}}
    with aioresponses() as m:
        m.get(RE_STATUS, status=503)
        m.get(RE_STATUS, status=503)
        m.get(RE_STATUS, payload=good_payload)
        result = await client.status.get()
    assert result["realms"] == []
    await client.close()
