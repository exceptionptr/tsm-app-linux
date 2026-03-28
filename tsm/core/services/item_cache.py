"""Persistent cache for WoW item data fetched from the Wowhead tooltip API."""
from __future__ import annotations

import json
import logging
import threading
import urllib.request
from collections.abc import Callable

from tsm.storage.config_store import DATA_DIR

logger = logging.getLogger(__name__)

_CACHE_FILE = DATA_DIR / "item_cache.json"
_WOWHEAD_URL = "https://nether.wowhead.com/tooltip/item/{}"
_UA = "Mozilla/5.0"
_TIMEOUT = 5

ItemData = dict[str, object]


class ItemCache:
    """Thread-safe persistent cache for WoW item data (name, quality, tooltip HTML).

    Fetches missing items from the Wowhead tooltip API in a background thread.
    Cache is saved to disk so subsequent app launches are instant.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, ItemData] = {}
        self._load()

    def get(self, item_id: str) -> ItemData | None:
        """Return cached entry for item_id, or None if not yet fetched."""
        with self._lock:
            return self._data.get(item_id)

    def get_name(self, item_id: str) -> str | None:
        with self._lock:
            entry = self._data.get(item_id)
        if entry:
            name = entry.get("name")
            return str(name) if name else None
        return None

    def ensure_fetched(
        self,
        item_ids: list[str],
        on_done: Callable[[dict[str, ItemData], list[str]], None],
    ) -> None:
        """Fetch any item_ids not yet in cache in a background thread.

        on_done(fetched, attempted) is always called when the batch finishes:
        - fetched: successfully resolved items
        - attempted: all ids that were tried (so callers can fall back for failures)
        Callers must marshal on_done back to the Qt main thread (e.g. via a Signal).
        """
        with self._lock:
            missing = [iid for iid in item_ids if iid not in self._data]
        if not missing:
            return
        threading.Thread(
            target=self._worker,
            args=(missing, on_done),
            daemon=True,
        ).start()

    def _worker(
        self,
        ids: list[str],
        on_done: Callable[[dict[str, ItemData], list[str]], None],
    ) -> None:
        new_data: dict[str, ItemData] = {}
        for item_id in ids:
            try:
                url = _WOWHEAD_URL.format(item_id)
                req = urllib.request.Request(url, headers={"User-Agent": _UA})
                with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                    data: ItemData = json.loads(resp.read().decode("utf-8"))
                if "name" in data:
                    new_data[item_id] = data
                    with self._lock:
                        self._data[item_id] = data
            except Exception:
                logger.debug("Wowhead fetch failed for item %s", item_id)
        if new_data:
            self._save()
        on_done(new_data, ids)

    def _load(self) -> None:
        try:
            if _CACHE_FILE.exists():
                self._data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Could not load item cache from %s", _CACHE_FILE)

    def _save(self) -> None:
        try:
            _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                data_copy = dict(self._data)
            _CACHE_FILE.write_text(
                json.dumps(data_copy, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            logger.warning("Could not save item cache")
