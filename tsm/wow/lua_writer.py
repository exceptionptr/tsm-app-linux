"""Generate and atomically write TSM AppData.lua files.

Real format from AppData.pyc (decompiled):

    select(2, ...).LoadData("TYPE","Realm",[[return data]]) --<TYPE,Realm,timestamp>

- One line per entry.
- The trailing --<...> comment is parsed back by AppData.__init__ to read timestamps.
- APP_INFO uses store_raw=True (no [[return ...]]), it's a raw Lua call.
- All other types use [[return data]] wrapping.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path

from tsm.core.models.auction import AppInfo, AuctionData

logger = logging.getLogger(__name__)

APP_VERSION = 41402

# Tags that use store_raw=True (pass blob verbatim, no [[return ...]] wrapper).
# All observed tags use the [[return ...]] wrapping, so this set is empty.
# Kept as a hook: add tag names here if a future API change introduces raw-format entries.
RAW_TAGS: set[str] = set()


class AppDataEntry:
    """Represents one line in AppData.lua."""

    __slots__ = ("tag", "realm_or_region", "data_blob", "timestamp", "store_raw")

    def __init__(
        self,
        tag: str,
        realm_or_region: str,
        data_blob: str,
        timestamp: int,
        store_raw: bool = False,
    ) -> None:
        self.tag = tag
        self.realm_or_region = realm_or_region
        self.data_blob = data_blob
        self.timestamp = timestamp
        self.store_raw = store_raw

    def render(self) -> str:
        tag, realm = self.tag, self.realm_or_region
        if self.store_raw:
            data_part = f'select(2, ...).LoadData("{tag}","{realm}",{self.data_blob})'
        else:
            data_part = f'select(2, ...).LoadData("{tag}","{realm}",[[return {self.data_blob}]])'
        return f"{data_part} --<{tag},{realm},{self.timestamp}>"


class AppDataFile:
    """Read and write AppData.lua, preserving entries not touched by this session."""

    KNOWN_TYPES = {
        "AUCTIONDB_NON_COMMODITY_DATA",
        "AUCTIONDB_NON_COMMODITY_SCAN_STAT",
        "AUCTIONDB_NON_COMMODITY_HISTORICAL",
        "AUCTIONDB_COMMODITY_DATA",
        "AUCTIONDB_COMMODITY_SCAN_STAT",
        "AUCTIONDB_COMMODITY_HISTORICAL",
        "AUCTIONDB_REGION_STAT",
        "AUCTIONDB_REGION_HISTORICAL",
        "AUCTIONDB_REGION_SALE",
        "SHOPPING_SEARCHES",
        "APP_INFO",
    }

    def __init__(self, path: Path) -> None:
        self._path = path
        self._entries: list[AppDataEntry] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    # Trailing comment: --<TYPE,Realm,timestamp>
                    comment_idx = line.rfind("--")
                    if comment_idx == -1:
                        continue
                    data_part = line[: comment_idx - 1]
                    meta = line[comment_idx + 3 : -1]  # strip --< and >
                    try:
                        tag, realm, ts_str = meta.split(",", 2)
                        ts = int(ts_str)
                    except ValueError:
                        continue
                    if tag not in self.KNOWN_TYPES:
                        continue
                    store_raw = tag in RAW_TAGS
                    self._entries.append(AppDataEntry(tag, realm, "", ts, store_raw))
                    # Store the full data line for re-writing unchanged entries
                    self._entries[-1].data_blob = _extract_blob(data_part, tag, realm, store_raw)
        except Exception:
            logger.exception("Failed to read existing AppData.lua: %s", self._path)

    def last_update(self, tag: str, realm_or_region: str) -> int:
        """Return the stored timestamp for (tag, realm), or 0 if not present."""
        for e in self._entries:
            if e.tag == tag and e.realm_or_region == realm_or_region:
                return e.timestamp
        return 0

    def update(self, tag: str, realm_or_region: str, data_blob: str, timestamp: int) -> None:
        """Insert or replace an entry."""
        store_raw = tag in RAW_TAGS
        for e in self._entries:
            if e.tag == tag and e.realm_or_region == realm_or_region:
                e.data_blob = data_blob
                e.timestamp = timestamp
                e.store_raw = store_raw
                return
        self._entries.append(AppDataEntry(tag, realm_or_region, data_blob, timestamp, store_raw))

    def save(self) -> None:
        """Atomically write AppData.lua."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(e.render() for e in self._entries) + "\n"
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=self._path.parent,
                delete=False,
                suffix=".tmp",
                encoding="utf-8",
            ) as f:
                f.write(content)
                tmp = f.name
            os.replace(tmp, self._path)
            logger.info(
                "Written AppData.lua (%d entries, %d bytes)", len(self._entries), len(content)
            )
        except Exception:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)
            raise


def _extract_blob(data_part: str, tag: str, realm: str, store_raw: bool) -> str:
    """Extract the inner data blob from a LoadData() line."""
    # data_part ends with ) - the closing paren of LoadData(tag, realm, data)
    prefix = f'select(2, ...).LoadData("{tag}","{realm}",'
    if not data_part.startswith(prefix):
        return data_part  # can't parse, store as-is
    inner = data_part[len(prefix) :]
    # Strip the one closing ) that belongs to LoadData(...)
    if inner.endswith(")"):
        inner = inner[:-1]
    if store_raw:
        return inner
    if inner.startswith("[[return ") and inner.endswith("]]"):
        return inner[9:-2]
    return inner


class LuaWriter:
    """Convenience wrapper: update AppData.lua from AuctionData model."""

    def write_app_data(self, data: AuctionData, addon_dir: Path) -> Path:
        """Merge new entries into AppData.lua and save atomically."""
        target = addon_dir / "AppData.lua"
        app_data = AppDataFile(target)

        # Write APP_INFO
        now = int(time.time())
        app_info = data.app_info or AppInfo(version=APP_VERSION, last_sync=now)
        # APP_INFO blob, stored as the raw inner blob (without [[return ...]]),
        # AppDataEntry.render() wraps it correctly based on store_raw=False
        app_info_blob = (
            f"{{version={app_info.version},lastSync={app_info.last_sync},"
            f'message={{id={app_info.message_id},msg="{app_info.message_text}"}},news={{}}}}'
        )
        app_data.update("APP_INFO", "Global", app_info_blob, app_info.last_sync)

        # Write all data entries
        for entry in data.entries.values():
            app_data.update(entry.tag, entry.realm_or_region, entry.data_blob, entry.download_time)

        app_data.save()
        return target
