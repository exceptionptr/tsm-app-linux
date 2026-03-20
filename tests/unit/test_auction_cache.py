"""Tests for AuctionCache."""

from __future__ import annotations

import pytest

from tsm.core.models.auction import RealmData, RealmStatus
from tsm.storage.auction_cache import AuctionCache
from tsm.storage.database import Database


@pytest.fixture
async def db(tmp_path):
    db = Database(tmp_path / "test.db")
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
def cache(db):
    return AuctionCache(db)


@pytest.mark.asyncio
async def test_store_and_retrieve(cache):
    realm = RealmData(
        realm_slug="Blackhand",
        region="EU",
        blobs={"AUCTIONDB_NON_COMMODITY_DATA": "return {downloadTime=1710000000}"},
        last_updated=1710000000,
    )
    await cache.store(realm)
    result = await cache.get("Blackhand", "EU")
    assert result is not None
    assert result.realm_slug == "Blackhand"
    assert "AUCTIONDB_NON_COMMODITY_DATA" in result.blobs


@pytest.mark.asyncio
async def test_get_missing_returns_none(cache):
    result = await cache.get("NonExistent", "EU")
    assert result is None


@pytest.mark.asyncio
async def test_store_updates_existing(cache):
    realm = RealmData(realm_slug="R", region="EU", blobs={"TAG": "old"}, last_updated=1000)
    await cache.store(realm)
    realm2 = RealmData(realm_slug="R", region="EU", blobs={"TAG": "new"}, last_updated=2000)
    await cache.store(realm2)
    result = await cache.get("R", "EU")
    assert result.blobs["TAG"] == "new"


@pytest.mark.asyncio
async def test_get_all(cache):
    for i in range(3):
        r = RealmData(realm_slug=f"Realm{i}", region="EU", blobs={}, last_updated=i)
        await cache.store(r)
    all_realms = await cache.get_all()
    assert len(all_realms) == 3


@pytest.mark.asyncio
async def test_save_and_load_snapshot(cache):
    statuses = [
        RealmStatus(
            display_name="EU-Tarren Mill",
            is_region=False,
            auctiondb_status="Up to date",
            last_updated=1710000000,
            region="EU",
            name="Tarren Mill",
        )
    ]
    await cache.save_snapshot(statuses)
    loaded, saved_at = await cache.load_snapshot()
    assert len(loaded) == 1
    assert loaded[0].display_name == "EU-Tarren Mill"
    assert saved_at > 0


@pytest.mark.asyncio
async def test_load_snapshot_missing_returns_empty(cache):
    statuses, saved_at = await cache.load_snapshot()
    assert statuses == []
    assert saved_at == 0
