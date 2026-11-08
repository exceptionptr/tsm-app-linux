"""AuctionDataService: socket events to AppData.lua, pruning, realm list."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tsm.core.services import auction as auction_mod
from tsm.core.services.auction import AuctionDataService, RealmLimitReached
from tsm.wow.lua_writer import AppDataFile

BLOB = b"{downloadTime=1,fields={},data={}}"


def _region(rid: int, gv: str, prefix: str = "eu") -> dict:
    return {"regionId": rid, "name": "Europe", "regionPrefix": prefix, "gameVersion": gv}


REGIONS = {
    2: _region(2, "Retail"),
    14: _region(14, "Wrath"),
    40: _region(40, "Forever"),
}
REALMS = [
    {
        "realmId": 300,
        "regionId": 2,
        "name": "Tarren Mill",
        "localizedName": "Tarren Mill",
        "auctionHouses": [{"auctionHouseId": 97, "type": "All", "lastModified": 50}],
        "region": REGIONS[2],
    },
    {
        "realmId": 301,
        "regionId": 2,
        "name": "Silvermoon",
        "localizedName": "Silvermoon",
        "auctionHouses": [{"auctionHouseId": 98, "type": "All", "lastModified": 50}],
        "region": REGIONS[2],
    },
    {
        "realmId": 706,
        "regionId": 14,
        "name": "Everlook",
        "localizedName": "Everlook",
        "auctionHouses": [
            {"auctionHouseId": 501, "type": "Horde", "lastModified": 60},
            {"auctionHouseId": 502, "type": "Alliance", "lastModified": 60},
        ],
        "region": REGIONS[14],
    },
    {
        "realmId": 900,
        "regionId": 40,
        "name": "Doomhowl",
        "localizedName": "Doomhowl",
        "auctionHouses": [{"auctionHouseId": 700, "type": "All", "lastModified": 70}],
        "region": REGIONS[40],
    },
]
USER_REALMS = [
    {"id": "usr_rlm_1", "userId": "u", "realmId": 300, "auctionHouseType": "ALL"},
    {"id": "usr_rlm_2", "userId": "u", "realmId": 706, "auctionHouseType": "HORDE"},
    {"id": "usr_rlm_3", "userId": "u", "realmId": 900, "auctionHouseType": "ALL"},
]


def _wow(tmp_path: Path, folders=("_retail_", "_classic_", "_forever_")) -> Path:
    base = tmp_path / "World of Warcraft"
    for f in folders:
        gv = base / f
        gv.mkdir(parents=True)
        (gv / "Wow.exe").write_bytes(b"")
        ah = gv / "Interface" / "AddOns" / "TradeSkillMaster_AppHelper"
        ah.mkdir(parents=True)
        (ah / "TradeSkillMaster_AppHelper.lua").write_text("")
    return base


def _appdata(base: Path, folder: str) -> AppDataFile:
    return AppDataFile(
        base / folder / "Interface" / "AddOns" / "TradeSkillMaster_AppHelper" / "AppData.lua"
    )


def _client(user_realms=None) -> MagicMock:
    c = MagicMock()
    c.realms = AsyncMock(return_value=REALMS)
    c.regions = AsyncMock(return_value=list(REGIONS.values()))
    c.game_versions = AsyncMock(
        return_value=[{"gameType": "forever", "label": "WoW Forever", "folder": "_forever_"}]
    )
    realms = USER_REALMS if user_realms is None else user_realms
    c.user_realms = AsyncMock(return_value=list(realms))
    c.download = AsyncMock(return_value=BLOB)
    c.add_user_realm = AsyncMock()
    c.delete_user_realm = AsyncMock()
    return c


@pytest.fixture(autouse=True)
def _no_debounce(monkeypatch):
    monkeypatch.setattr(auction_mod, "WRITE_DEBOUNCE_SECONDS", 0)


async def _service(tmp_path, client=None, folders=("_retail_", "_classic_", "_forever_")):
    base = _wow(tmp_path, folders)
    detector = SimpleNamespace(installs=[SimpleNamespace(path=str(base))])
    svc = AuctionDataService(client or _client(), None, detector)
    await svc.start("u")
    await svc.flush_all()
    return svc, base


def _realm_event(realm_id=300, ah="ALL", tag="AUCTIONDB_NON_COMMODITY_DATA", lm=100):
    return {
        "realmId": realm_id,
        "auctionHouseType": ah,
        "stringType": tag,
        "lastModified": str(lm),  # the server sends strings and ints
        "url": "https://blob/x",
    }


@pytest.mark.asyncio
async def test_realm_string_is_written_with_its_auction_house(tmp_path):
    svc, base = await _service(tmp_path)
    await svc.handle_event("realm_auctiondb", _realm_event())
    await svc.flush_all()
    f = _appdata(base, "_retail_")
    assert f.last_update("AUCTIONDB_NON_COMMODITY_DATA", "Tarren Mill") == 100
    assert f.entries[0].auction_house_id == 97
    assert f.entries[0].data == BLOB.decode()


@pytest.mark.asyncio
async def test_known_data_is_not_downloaded_again(tmp_path):
    client = _client()
    svc, _ = await _service(tmp_path, client)
    await svc.handle_event("realm_auctiondb", _realm_event())
    await svc.flush_all()
    await svc.handle_event("realm_auctiondb", _realm_event())
    await svc.flush_all()
    assert client.download.await_count == 1


@pytest.mark.asyncio
async def test_faction_auction_house_and_progression_region(tmp_path):
    svc, base = await _service(tmp_path)
    await svc.handle_event("realm_auctiondb", _realm_event(706, "HORDE"))
    await svc.handle_event(
        "region_auctiondb",
        {"regionId": 14, "stringType": "AUCTIONDB_REGION_STAT", "lastModified": 7, "url": "u"},
    )
    await svc.flush_all()
    f = _appdata(base, "_classic_")
    assert f.last_update("AUCTIONDB_NON_COMMODITY_DATA", "Everlook-Horde") == 100
    assert f.last_update("AUCTIONDB_REGION_STAT", "BCC-EU") == 7
    assert _appdata(base, "_retail_").entries == []


@pytest.mark.asyncio
async def test_forever_data_goes_to_the_forever_client(tmp_path):
    svc, base = await _service(tmp_path)
    await svc.handle_event("realm_auctiondb", _realm_event(900))
    await svc.handle_event(
        "region_auctiondb",
        {"regionId": 40, "stringType": "AUCTIONDB_REGION_STAT", "lastModified": 8, "url": "u"},
    )
    await svc.flush_all()
    f = _appdata(base, "_forever_")
    assert f.last_update("AUCTIONDB_NON_COMMODITY_DATA", "Doomhowl") == 100
    assert f.last_update("AUCTIONDB_REGION_STAT", "Forever-EU") == 8


@pytest.mark.asyncio
async def test_unfollowed_realm_is_ignored(tmp_path):
    client = _client()
    svc, _ = await _service(tmp_path, client)
    await svc.handle_event("realm_auctiondb", _realm_event(301))
    await svc.handle_event("realm_auctiondb", _realm_event(706, "ALLIANCE"))
    await svc.flush_all()
    client.download.assert_not_awaited()


@pytest.mark.asyncio
async def test_nothing_is_downloaded_without_apphelper(tmp_path):
    client = _client()
    svc, _ = await _service(tmp_path, client, folders=("_classic_",))
    await svc.handle_event("realm_auctiondb", _realm_event())
    await svc.flush_all()
    client.download.assert_not_awaited()


@pytest.mark.asyncio
async def test_superseded_blob_is_skipped(tmp_path):
    client = _client()
    client.download = AsyncMock(return_value=None)
    svc, base = await _service(tmp_path, client)
    await svc.handle_event("realm_auctiondb", _realm_event())
    await svc.flush_all()
    assert _appdata(base, "_retail_").entries == []


@pytest.mark.asyncio
async def test_unfollowed_realm_data_is_pruned(tmp_path):
    base = _wow(tmp_path)
    f = _appdata(base, "_retail_")
    f.update("AUCTIONDB_NON_COMMODITY_DATA", "Silvermoon", "{}", 5, 98)
    f.update("AUCTIONDB_NON_COMMODITY_DATA", "Tarren Mill", "{}", 5, 97)
    f.update("AUCTIONDB_REGION_STAT", "EU", "{}", 5)
    f.update("AUCTIONDB_NON_COMMODITY_DATA", "Somewhere Unknown", "{}", 5)
    f.save()
    detector = SimpleNamespace(installs=[SimpleNamespace(path=str(base))])
    svc = AuctionDataService(_client(), None, detector)
    await svc.start("u")
    await svc.flush_all()
    keys = {e.key for e in _appdata(base, "_retail_").entries}
    assert keys == {"Tarren Mill", "EU", "Somewhere Unknown"}


@pytest.mark.asyncio
async def test_pruning_is_skipped_when_a_followed_realm_is_unknown(tmp_path):
    base = _wow(tmp_path)
    f = _appdata(base, "_retail_")
    f.update("AUCTIONDB_NON_COMMODITY_DATA", "Silvermoon", "{}", 5, 98)
    f.save()
    extra = [*USER_REALMS, {"id": "x", "userId": "u", "realmId": 12345, "auctionHouseType": "ALL"}]
    detector = SimpleNamespace(installs=[SimpleNamespace(path=str(base))])
    svc = AuctionDataService(_client(extra), None, detector)
    await svc.start("u")
    await svc.flush_all()
    assert {e.key for e in _appdata(base, "_retail_").entries} == {"Silvermoon"}


@pytest.mark.asyncio
async def test_statuses_list_realms_under_their_region(tmp_path):
    svc, _ = await _service(tmp_path)
    await svc.handle_event("realm_auctiondb", _realm_event())
    await svc.flush_all()
    statuses = {(s.game_version, s.region, s.name): s for s in await svc.statuses()}
    tm = statuses[("retail", "EU", "Tarren Mill")]
    assert tm.user_realm_id == "usr_rlm_1"
    assert tm.last_updated == 100
    assert tm.auctiondb_status == "Up to date"
    assert statuses[("bcc", "BCC-EU", "Everlook-Horde")].auctiondb_status == "Waiting"
    assert statuses[("forever", "Forever-EU", "Forever-EU")].is_region


@pytest.mark.asyncio
async def test_app_info_goes_to_every_game_version(tmp_path):
    svc, base = await _service(tmp_path)
    await svc.handle_event(
        "app_info", {"message": {"id": 1, "msg": "hello"}, "news": [{"title": "Forever"}]}
    )
    await svc.flush_all()
    for folder in ("_retail_", "_classic_", "_forever_"):
        entry = _appdata(base, folder).entries[0]
        assert (entry.tag, entry.key) == ("APP_INFO", "Global")
        assert 'msg="hello"' in entry.data
        assert 'version="1.0.9"' in entry.data


@pytest.mark.asyncio
async def test_addon_event_reaches_listeners(tmp_path):
    svc, _ = await _service(tmp_path)
    seen: list = []
    svc.add_addon_listener(seen.append)
    rel = {"addon": "TradeSkillMaster", "channel": "release", "version": "v4.15.4", "url": "z"}
    await svc.handle_event("addon", {"data": [rel], "isComplete": True})
    assert seen == [[rel]]
    assert svc.current().addon_versions == [{"name": "TradeSkillMaster", "version_str": "4.15.4"}]


@pytest.mark.asyncio
async def test_add_realm_respects_the_tier_limit(tmp_path):
    client = _client()
    svc, _ = await _service(tmp_path, client)
    with pytest.raises(RealmLimitReached):
        await svc.add_realm(301, "ALL", limit=3)
    await svc.add_realm(301, "all", limit=None)
    client.add_user_realm.assert_awaited_once_with("u", 301, "ALL")


@pytest.mark.asyncio
async def test_add_realm_reconnects_once_when_no_data_arrives(tmp_path, monkeypatch):
    monkeypatch.setattr(auction_mod, "NEW_REALM_RECONNECT_DELAY_SECONDS", 0)
    client = _client()
    svc, _ = await _service(tmp_path, client)
    client.user_realms.return_value = [
        {"id": "usr_rlm_9", "realmId": 301, "auctionHouseType": "ALL"}
    ]
    svc.reconnect = AsyncMock()
    await svc.add_realm(301, "all", limit=None)
    await svc.flush_all()
    svc.reconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_realm_skips_the_reconnect_when_data_already_came(tmp_path, monkeypatch):
    monkeypatch.setattr(auction_mod, "NEW_REALM_RECONNECT_DELAY_SECONDS", 0)
    client = _client()
    svc, _ = await _service(tmp_path, client)
    client.user_realms.return_value = [
        {"id": "usr_rlm_9", "realmId": 301, "auctionHouseType": "ALL"}
    ]
    svc.reconnect = AsyncMock()
    svc._server_lm[("realm", 301, "ALL")] = 5
    await svc.add_realm(301, "all", limit=None)
    await svc.flush_all()
    svc.reconnect.assert_not_awaited()


@pytest.mark.asyncio
async def test_remove_realm_uses_the_user_realm_id(tmp_path):
    client = _client()
    svc, _ = await _service(tmp_path, client)
    await svc.remove_realm("usr_rlm_2")
    client.delete_user_realm.assert_awaited_once_with("usr_rlm_2")


@pytest.mark.asyncio
async def test_legacy_local_realms_move_to_the_account(tmp_path):
    client = _client()
    cache = MagicMock()
    cache.get_json = AsyncMock(return_value=None)
    cache.put_json = AsyncMock()
    cache.save_snapshot = AsyncMock()
    cache.get_all_user_realms = AsyncMock(
        return_value=[("bcc", "BCC-EU", "Everlook-Alliance"), ("classic", "HC-EU", "Nowhere")]
    )
    cache.remove_user_realm = AsyncMock()
    base = _wow(tmp_path)
    detector = SimpleNamespace(installs=[SimpleNamespace(path=str(base))])
    svc = AuctionDataService(client, cache, detector)
    await svc.start("u")
    await svc.flush_all()
    client.add_user_realm.assert_awaited_once_with("u", 706, "ALLIANCE")
    assert cache.remove_user_realm.await_count == 2


@pytest.mark.asyncio
async def test_realm_tree_offers_each_auction_house(tmp_path):
    svc, _ = await _service(tmp_path)
    tree = svc.realm_tree()
    names = [r["name"] for r in tree["Progression"]["BCC-EU"]]
    assert names == ["Everlook (Alliance)", "Everlook (Horde)"]
    assert tree["WoW Forever"]["Forever-EU"][0]["realm_id"] == 900
