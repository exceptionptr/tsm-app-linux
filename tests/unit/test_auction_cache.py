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


@pytest.mark.asyncio
async def test_migration_drops_bcc_rows_and_keeps_the_rest(tmp_path):
    """v4 repairs installs affected by issue #19 without wiping working rows."""
    import sqlite3

    path = tmp_path / "legacy.db"
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
        INSERT INTO schema_version (version) VALUES (3);
        CREATE TABLE user_added_realms (
            game_version TEXT NOT NULL,
            region TEXT NOT NULL,
            name TEXT NOT NULL,
            PRIMARY KEY (game_version, region, name)
        );
        INSERT INTO user_added_realms VALUES ('bcc', 'EU', 'Everlook-Horde');
        INSERT INTO user_added_realms VALUES ('classic', 'HC-EU', 'Soulseeker-Alliance');
        INSERT INTO user_added_realms VALUES ('anniversary', 'Fresh-EU', 'Thunderstrike-Alliance');
        """
    )
    con.commit()
    con.close()

    db = Database(path)
    await db.connect()
    try:
        cache = AuctionCache(db)
        assert await cache.get_user_realms("bcc") == set()
        assert await cache.get_user_realms("classic") == {("HC-EU", "Soulseeker-Alliance")}
        assert await cache.get_user_realms("anniversary") == {
            ("Fresh-EU", "Thunderstrike-Alliance")
        }
        async with db.connection.execute("SELECT version FROM schema_version") as cur:
            row = await cur.fetchone()
        assert row["version"] == 5
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_migration_collapses_a_multi_row_version_table(tmp_path):
    """version is the PRIMARY KEY, so old code appended rows instead of replacing.

    A database left with several rows must still report the highest version and
    come back with exactly one row, otherwise every later migration re-runs on
    each startup.
    """
    import sqlite3

    path = tmp_path / "multirow.db"
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
        INSERT INTO schema_version (version) VALUES (1);
        INSERT INTO schema_version (version) VALUES (3);
        CREATE TABLE user_added_realms (
            game_version TEXT NOT NULL,
            region TEXT NOT NULL,
            name TEXT NOT NULL,
            PRIMARY KEY (game_version, region, name)
        );
        INSERT INTO user_added_realms VALUES ('classic', 'HC-EU', 'Soulseeker-Alliance');
        """
    )
    con.commit()
    con.close()

    db = Database(path)
    await db.connect()
    try:
        async with db.connection.execute("SELECT version FROM schema_version") as cur:
            rows = await cur.fetchall()
        assert [r["version"] for r in rows] == [5]
        # read as v3, so the v3 wipe must not have re-run over a working row
        cache = AuctionCache(db)
        assert await cache.get_user_realms("classic") == {("HC-EU", "Soulseeker-Alliance")}
    finally:
        await db.close()
