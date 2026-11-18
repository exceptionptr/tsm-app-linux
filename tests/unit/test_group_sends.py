"""Group sends: AppData blob, tag-aware remove, import states, pending store, sync flow."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tsm.core.services import auction as auction_mod
from tsm.core.services.auction import AuctionDataService
from tsm.core.services.group_sends import GroupSendsService, notification_text
from tsm.core.services.sync import SyncController
from tsm.wow import game_versions as gvs
from tsm.wow.group_imports import parse_done_ids, read_done_ids
from tsm.wow.lua_writer import (
    AppDataFile,
    group_sent_at,
    render_app_info,
    render_group_imports,
)


def _send(
    sid: str,
    name: str = "Test Group",
    game_type: str = "retail",
    created="2025-01-02T03:04:05.678Z",
):
    return {
        "id": sid,
        "name": name,
        "author": "Max Mustermann",
        "createdAt": created,
        "importString": 'abc]]"\\',
        "gameType": game_type,
    }


# ---- lua_writer ---------------------------------------------------------


def test_group_imports_blob_quotes_and_converts_time():
    blob = render_group_imports([_send("g1")])
    assert blob == (
        '{{id="g1",name="Test Group",author="Max Mustermann",sentAt=1735787045,'
        'importString="abc\\093\\093\\034\\092"}}'
    )
    assert "]]" not in blob
    assert render_group_imports([]) == "{}"


def test_sent_at_is_zero_when_unparseable():
    assert group_sent_at({"createdAt": "garbage"}) == 0
    assert group_sent_at({}) == 0


def test_remove_with_tag_keeps_app_info(tmp_path):
    f = AppDataFile(tmp_path / "AppData.lua")
    f.update("APP_INFO", "Global", render_app_info("1.0.14", 5), 5)
    f.update("GROUP_IMPORTS", "Global", "{}", 9)
    assert f.remove(["Global"], tag="GROUP_IMPORTS") == ["Global"]
    assert [(e.tag, e.key) for e in f.entries] == [("APP_INFO", "Global")]


def test_replace_beats_an_older_timestamp(tmp_path):
    f = AppDataFile(tmp_path / "AppData.lua")
    f.update("GROUP_IMPORTS", "Global", "{new}", 100)
    f.replace("GROUP_IMPORTS", "Global", "{older}", 50)
    assert f.last_update("GROUP_IMPORTS", "Global") == 50
    assert f.entries[0].data == "{older}"


# ---- game types ---------------------------------------------------------


def test_game_types_follow_the_captured_order():
    assert gvs.game_types_for(["_retail_", "_forever_"]) == ["forever", "retail"]
    folders = ["_retail_", "_classic_era_", "_anniversary_", "_classic_", "_forever_"]
    assert gvs.game_types_for(folders) == ["classic", "classic-progression", "forever", "retail"]
    assert gvs.game_types_for([]) == []


# ---- import states ------------------------------------------------------

SAVED = """
TradeSkillMaster_AppHelperDB = {
\t["groupImports"] = {
\t\t["g1"] = "IMPORTED",
\t\t["g2"] = "PENDING",
\t\t["g3"] = "DISCARDED",
\t},
}
"""


def test_parse_done_ids():
    assert parse_done_ids(SAVED) == {"g1", "g3"}
    assert parse_done_ids("nothing here") == set()


def test_read_done_ids_case_insensitive_and_skips_savedvariables(tmp_path):
    acc = tmp_path / "_retail_" / "wtf" / "ACCOUNT" / "ACC1" / "savedvariables"
    acc.mkdir(parents=True)
    (acc / "tradeskillmaster_apphelper.lua").write_text(SAVED, encoding="utf-8")
    (tmp_path / "_retail_" / "wtf" / "ACCOUNT" / "SavedVariables").mkdir()
    assert read_done_ids(tmp_path, "_retail_") == {"g1", "g3"}
    assert read_done_ids(tmp_path, "_forever_") == set()


# ---- service ------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_debounce(monkeypatch):
    monkeypatch.setattr(auction_mod, "WRITE_DEBOUNCE_SECONDS", 0)


def _wow(tmp_path: Path, folders=("_retail_", "_forever_")) -> Path:
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


def _make(tmp_path, claimed=None, connected=True):
    base = _wow(tmp_path)
    detector = SimpleNamespace(installs=[SimpleNamespace(path=str(base))])
    auction = AuctionDataService(None, None, detector)
    client = MagicMock()
    client.claim_group_sends = AsyncMock(return_value=claimed or [])
    notes: list[str] = []
    store = tmp_path / "group_sends.json"
    svc = GroupSendsService(client, auction, store, notes.append, lambda: connected)
    return svc, auction, client, base, store, notes


@pytest.mark.asyncio
async def test_claim_persists_writes_and_notifies(tmp_path):
    svc, auction, client, base, store, notes = _make(tmp_path, [_send("g1"), _send("g2", "Other")])
    await auction.write_app_info()
    await svc.claim()
    await auction.flush_all()
    client.claim_group_sends.assert_awaited_once_with(["forever", "retail"])
    assert [s["id"] for s in json.loads(store.read_text(encoding="utf-8"))] == ["g1", "g2"]
    f = _appdata(base, "_retail_")
    assert f.last_update("GROUP_IMPORTS", "Global") == 1735787045
    assert f.last_update("APP_INFO", "Global") is not None
    assert _appdata(base, "_forever_").last_update("GROUP_IMPORTS", "Global") is None
    assert notes == [
        "2 groups sent to WoW Retail: Test Group and Other. Type /reload in Retail to import them."
    ]


@pytest.mark.asyncio
async def test_known_ids_are_not_added_twice_or_announced(tmp_path):
    svc, auction, _client, _base, store, notes = _make(tmp_path, [_send("g1")])
    await svc.claim()
    await svc.claim()
    assert [s["id"] for s in svc.pending] == ["g1"]
    assert len(notes) == 1


@pytest.mark.asyncio
async def test_pending_survives_a_restart_and_failed_claim(tmp_path):
    svc, auction, client, base, store, _ = _make(tmp_path, [_send("g1")])
    await svc.claim()
    await auction.flush_all()
    client.claim_group_sends.side_effect = RuntimeError("down")
    await svc.claim()
    assert [s["id"] for s in svc.pending] == ["g1"]
    again = GroupSendsService(client, auction, store)
    assert [s["id"] for s in again.pending] == ["g1"]


@pytest.mark.asyncio
async def test_handled_sends_leave_and_the_entry_is_removed_keeping_app_info(tmp_path):
    svc, auction, _client, base, _store, _ = _make(tmp_path, [_send("g1")])
    await auction.write_app_info()
    await svc.claim()
    await auction.flush_all()
    acc = base / "_retail_" / "WTF" / "Account" / "ACC1" / "SavedVariables"
    acc.mkdir(parents=True)
    (acc / "TradeSkillMaster_AppHelper.lua").write_text(SAVED.replace("g1", "g1"), encoding="utf-8")
    await svc.refresh()
    await auction.flush_all()
    assert svc.pending == []
    f = _appdata(base, "_retail_")
    assert f.last_update("GROUP_IMPORTS", "Global") is None
    assert f.last_update("APP_INFO", "Global") is not None


@pytest.mark.asyncio
async def test_no_claim_while_disconnected_or_on_refresh(tmp_path):
    svc, _a, client, *_ = _make(tmp_path, [_send("g1")], connected=False)
    await svc.claim()
    await svc.refresh()
    client.claim_group_sends.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_waiting_sync_ors_in_the_claim_flag(tmp_path):
    import asyncio

    svc, _a, client, *_ = _make(tmp_path, [_send("g1")])
    await asyncio.gather(svc.refresh(), svc.refresh(), svc.claim())
    assert client.claim_group_sends.await_count == 1


@pytest.mark.asyncio
async def test_failed_persist_is_retried_on_the_next_sync(tmp_path):
    svc, _auction, _client, _base, store, _ = _make(tmp_path, [_send("g1")])
    real = svc._persist
    calls: list[int] = []

    def flaky() -> None:
        calls.append(1)
        if len(calls) == 1:
            raise OSError("disk full")
        real()

    svc._persist = flaky  # type: ignore[method-assign]
    await svc.claim()
    assert not store.exists()
    # Nothing new and nothing handled: only the dirty flag makes this sync write.
    await svc.refresh()
    assert len(calls) == 2
    assert [x["id"] for x in json.loads(store.read_text(encoding="utf-8"))] == ["g1"]
    await svc.refresh()
    assert len(calls) == 2  # clean again, no more writes


def test_notification_text_single():
    text = notification_text([_send("a")], ["Retail", "Forever"])
    assert text == (
        "Group sent to WoW Retail and Forever: Test Group. "
        "Type /reload in Retail and Forever to import it."
    )


# ---- triggers -----------------------------------------------------------


class _FakeGroups:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def claim(self) -> None:
        self.calls.append("claim")

    async def refresh(self) -> None:
        self.calls.append("refresh")


def _sync(groups) -> SyncController:
    auction: Any = MagicMock()
    auction.handle_event = AsyncMock()
    auction.load_user_realms = AsyncMock()
    auction.stop = AsyncMock()
    auth = MagicMock()
    return SyncController(auth, auction, group_sends=groups)


async def _settle() -> None:
    import asyncio

    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_connect_and_group_send_event_claim():
    groups = _FakeGroups()
    sync = _sync(groups)
    await sync._on_state(True)
    await sync._on_event("group_send", {})
    await sync._on_event("app_info", {})
    await _settle()
    assert groups.calls == ["claim", "claim"]
    await sync.stop()
