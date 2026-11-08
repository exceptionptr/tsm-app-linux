"""aiosqlite setup and migrations."""

from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 5

CREATE_AUCTION_CACHE = """
CREATE TABLE IF NOT EXISTS auction_cache (
    realm_slug TEXT NOT NULL,
    region TEXT NOT NULL,
    scan_data BLOB NOT NULL,
    last_updated INTEGER NOT NULL,
    PRIMARY KEY (realm_slug, region)
);
"""

CREATE_SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);
"""

CREATE_REALM_SNAPSHOT = """
CREATE TABLE IF NOT EXISTS realm_snapshot (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    statuses_json TEXT NOT NULL,
    saved_at INTEGER NOT NULL
);
"""

CREATE_USER_ADDED_REALMS = """
CREATE TABLE IF NOT EXISTS user_added_realms (
    game_version TEXT NOT NULL,
    region TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (game_version, region, name)
);
"""

# JSON copies of API catalogues (realms, regions, game versions), so the realm
# list and the Add Realm dropdown work at startup before the network is up.
CREATE_API_CACHE = """
CREATE TABLE IF NOT EXISTS api_cache (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    saved_at INTEGER NOT NULL
);
"""


class Database:
    def __init__(self, db_path: Path):
        self._path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._run_migrations()
        logger.info("Database connected: %s", self._path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def _run_migrations(self) -> None:
        if self._db is None:
            raise RuntimeError("Database not connected")
        await self._db.execute(CREATE_SCHEMA_VERSION)
        await self._db.commit()

        # version is the PRIMARY KEY, so "INSERT OR REPLACE" appends a row rather
        # than replacing the old one. Read the highest value and collapse the
        # table back to a single row below, which also repairs databases that
        # already accumulated several rows.
        async with self._db.execute("SELECT MAX(version) AS version FROM schema_version") as cur:
            row = await cur.fetchone()
        current_version = (row["version"] if row else None) or 0

        if current_version < 1:
            await self._db.execute(CREATE_AUCTION_CACHE)
            await self._db.execute(CREATE_REALM_SNAPSHOT)
            await self._db.execute(CREATE_USER_ADDED_REALMS)

        if current_version < 3:
            # region column changed from a two-letter suffix ("EU") to the full API
            # region string ("HC-EU"). Old entries are incompatible with the new exact
            # matching filter, so wipe and require re-add via the UI.
            await self._db.execute("DELETE FROM user_added_realms")

        if current_version < 4:
            # bcc rows are no longer read: /v2/status returns the account's own
            # Progression realms, so they are not filtered against this table.
            # Existing rows also stored the bare region ("EU") instead of the
            # API's ("BCC-EU"), which skipped every Progression realm. Drop only
            # the bcc rows; classic and anniversary entries are correct and
            # re-adding them by hand is a nuisance. See issue #19.
            await self._db.execute("DELETE FROM user_added_realms WHERE game_version='bcc'")

        if current_version < 5:
            # The new backend registers realms of every game version server side.
            # user_added_realms is kept only until AuctionDataService has moved its
            # rows to the account (see migrate_local_realms).
            await self._db.execute(CREATE_API_CACHE)

        await self._db.execute("DELETE FROM schema_version")
        await self._db.execute(
            "INSERT INTO schema_version (version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
        await self._db.commit()

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database not connected")
        return self._db
