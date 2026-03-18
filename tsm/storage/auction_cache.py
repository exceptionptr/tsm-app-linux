"""Auction cache read/write using SQLite.

The `scan_data` column stores JSON-serialised blobs dict:
    {"AUCTIONDB_NON_COMMODITY_DATA": "<blob>", ...}
"""

from __future__ import annotations

import json
import logging
import time

from tsm.core.models.auction import RealmData, RealmStatus
from tsm.storage.database import Database

logger = logging.getLogger(__name__)


class AuctionCache:
    def __init__(self, db: Database):
        self._db = db

    async def store(self, realm: RealmData) -> None:
        db = self._db.connection
        await db.execute(
            """INSERT INTO auction_cache (realm_slug, region, scan_data, last_updated)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(realm_slug, region) DO UPDATE SET
                 scan_data=excluded.scan_data,
                 last_updated=excluded.last_updated""",
            (realm.realm_slug, realm.region, json.dumps(realm.blobs), realm.last_updated),
        )
        await db.commit()

    async def get(self, realm_slug: str, region: str) -> RealmData | None:
        db = self._db.connection
        async with db.execute(
            "SELECT * FROM auction_cache WHERE realm_slug=? AND region=?",
            (realm_slug, region),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return RealmData(
                realm_slug=row["realm_slug"],
                region=row["region"],
                blobs=json.loads(row["scan_data"]),
                last_updated=row["last_updated"],
            )

    async def get_all(self) -> list[RealmData]:
        db = self._db.connection
        async with db.execute("SELECT * FROM auction_cache ORDER BY last_updated DESC") as cursor:
            rows = await cursor.fetchall()
            return [
                RealmData(
                    realm_slug=r["realm_slug"],
                    region=r["region"],
                    blobs=json.loads(r["scan_data"]),
                    last_updated=r["last_updated"],
                )
                for r in rows
            ]

    async def save_snapshot(self, statuses: list[RealmStatus]) -> None:
        """Persist the last known realm status list so it can be shown at next startup."""
        db = self._db.connection
        blob = json.dumps([s.model_dump() for s in statuses])
        await db.execute(
            """INSERT INTO realm_snapshot (id, statuses_json, saved_at)
               VALUES (1, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 statuses_json=excluded.statuses_json,
                 saved_at=excluded.saved_at""",
            (blob, int(time.time())),
        )
        await db.commit()

    async def load_snapshot(self) -> tuple[list[RealmStatus], int]:
        """Return (statuses, saved_at) from the last persisted snapshot, or ([], 0)."""
        db = self._db.connection
        async with db.execute(
            "SELECT statuses_json, saved_at FROM realm_snapshot WHERE id=1"
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return [], 0
        try:
            statuses = [RealmStatus(**item) for item in json.loads(row["statuses_json"])]
            return statuses, int(row["saved_at"])
        except Exception:
            logger.warning("Failed to deserialise realm snapshot — ignoring")
            return [], 0

    async def delete_old(self, older_than_seconds: int = 86400 * 7) -> int:
        cutoff = int(time.time()) - older_than_seconds
        db = self._db.connection
        cursor = await db.execute("DELETE FROM auction_cache WHERE last_updated < ?", (cutoff,))
        await db.commit()
        return cursor.rowcount or 0
