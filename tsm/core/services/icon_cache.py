"""Persistent on-disk cache for WoW item icons from the Wowhead CDN.

Mirrors ItemCache: a lock, a background thread and an on_done callback the
caller marshals back to the Qt main thread. ItemCache already stores the icon
slug for every item it resolves; this fetches the image for that slug.
"""

from __future__ import annotations

import logging
import threading
import urllib.request
from collections.abc import Callable
from pathlib import Path

from tsm.storage.config_store import DATA_DIR

logger = logging.getLogger(__name__)

_ICON_DIR = DATA_DIR / "icons"
# "medium" is 36px and about 1 KB, which suits a table row. "large" is 56px.
_ICON_URL = "https://wow.zamimg.com/images/wow/icons/medium/{}.jpg"
_UA = "Mozilla/5.0"
_TIMEOUT = 5


class IconCache:
    """Thread-safe icon downloader backed by files under DATA_DIR/icons."""

    def __init__(self, icon_dir: Path | None = None) -> None:
        self._dir = icon_dir or _ICON_DIR
        self._lock = threading.Lock()
        self._missing: set[str] = set()  # slugs the CDN refused, do not retry

    def path_for(self, slug: str) -> Path | None:
        """Local file for *slug*, or None when it has not been fetched yet."""
        if not slug:
            return None
        path = self._dir / f"{slug}.jpg"
        return path if path.is_file() else None

    def ensure_fetched(self, slugs: list[str], on_done: Callable[[list[str]], None]) -> None:
        """Download any slugs not on disk, then call on_done with what arrived.

        on_done runs on a worker thread, so callers must hop back to the Qt
        thread themselves, the same contract ItemCache uses.
        """
        with self._lock:
            wanted = [
                s
                for s in dict.fromkeys(slugs)
                if s and s not in self._missing and self.path_for(s) is None
            ]
        if not wanted:
            return
        threading.Thread(target=self._worker, args=(wanted, on_done), daemon=True).start()

    def _worker(self, slugs: list[str], on_done: Callable[[list[str]], None]) -> None:
        fetched: list[str] = []
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("Could not create icon cache dir %s", self._dir)
            on_done(fetched)
            return

        for slug in slugs:
            try:
                req = urllib.request.Request(_ICON_URL.format(slug), headers={"User-Agent": _UA})
                with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                    data = resp.read()
                if not data:
                    raise ValueError("empty response")
                # Write via a temp file so a torn download is never read as an icon.
                tmp = self._dir / f".{slug}.part"
                tmp.write_bytes(data)
                tmp.replace(self._dir / f"{slug}.jpg")
                fetched.append(slug)
            except Exception:
                logger.debug("Icon fetch failed for %s", slug)
                with self._lock:
                    self._missing.add(slug)
        on_done(fetched)
