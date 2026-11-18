"""GroupSendsService: claim group sends and hand them to the addon, like the official client.

One sync does what the official client's does:

1. list the installed game versions and read which sends the addon has handled
2. on a socket connect or a group_send event, claim new sends (POST /group-sends/claim)
3. pending = pending minus handled (IMPORTED or DISCARDED) plus newly claimed
4. persist pending (DATA_DIR/group_sends.json) before anything is written to a game folder
5. write GROUP_IMPORTS/Global into AppData.lua of every installed game version
6. announce the newly claimed sends

A claimed send stays pending until the addon marks it handled, so a missing AppHelper,
a write error or a crash loses nothing: the next sync writes it again. Syncs are
serialised: one runs, one waits, and a waiting claim flag is OR-ed in.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tsm.wow import game_versions as gvs
from tsm.wow.group_imports import read_all_done_ids

logger = logging.getLogger(__name__)


def _join(items: list[str]) -> str:
    """The official list format: "a, b and c"."""
    if len(items) > 1:
        return ", ".join(items[:-1]) + " and " + items[-1]
    return "".join(items)


def notification_text(sends: list[dict[str, Any]], labels: list[str]) -> str:
    """Title and body of the official desktop notification, joined into one line."""
    where = _join(labels)
    title = (
        f"Group sent to WoW {where}"
        if len(sends) == 1
        else f"{len(sends)} groups sent to WoW {where}"
    )
    them = "it" if len(sends) == 1 else "them"
    names = _join([str(s.get("name", "")) for s in sends])
    body = f"{names}. Type /reload in {where} to import {them}."
    return f"{title}: {body}"


def _valid(send: object) -> bool:
    return isinstance(send, dict) and isinstance(send.get("id"), str) and bool(send["id"])


class GroupSendsService:
    def __init__(
        self,
        client: Any,
        auction: Any,
        store_path: Path,
        notify_fn: Callable[[str], None] | None = None,
        is_connected: Callable[[], bool] = lambda: True,
    ) -> None:
        self._client = client
        self._auction = auction
        self._path = store_path
        self._notify_fn = notify_fn
        self._is_connected = is_connected
        self._lock = asyncio.Lock()
        self._queued: list[bool] | None = None
        self._dirty = False  # pending differs from the file: write it on every sync
        self._pending = self._load()

    @property
    def pending(self) -> list[dict[str, Any]]:
        return list(self._pending)

    def _load(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError):
            logger.exception("Could not read %s, starting without pending group sends", self._path)
            return []
        return [s for s in data if _valid(s)] if isinstance(data, list) else []

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._pending, f)
            os.replace(tmp, self._path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    # ------------------------------------------------------------------ #

    async def claim(self) -> None:
        """Socket connect or group_send event: claim, then write."""
        await self.sync(True)

    async def refresh(self) -> None:
        """App start, APP_INFO tick: only re-read the import states and write."""
        await self.sync(False)

    async def sync(self, claim: bool) -> None:
        if self._queued is not None:
            self._queued[0] = self._queued[0] or claim
            async with self._lock:  # FIFO: returns after the queued run
                return
        queued = self._queued = [claim]
        async with self._lock:
            self._queued = None
            try:
                await self._run(queued[0])
            except Exception:
                logger.exception("Group send sync failed")

    async def _run(self, claim: bool) -> None:
        bases = self._auction.bases()
        folders = self._auction.installed_folders()
        if not bases or not folders:
            return
        done = await asyncio.to_thread(read_all_done_ids, bases, folders)
        new: list[dict[str, Any]] = []
        if claim:
            new = await self._claim(folders)
        kept = [s for s in self._pending if s["id"] not in done]
        if new or len(kept) != len(self._pending):
            self._pending = kept + new
            self._dirty = True
        if self._dirty:  # also retries a write that failed in an earlier sync
            try:
                await asyncio.to_thread(self._persist)
                self._dirty = False
            except OSError:
                logger.exception("Could not persist the pending group sends")
        for folder in folders:
            game_type = gvs.GAME_TYPE_BY_FOLDER.get(folder)
            sends = [s for s in self._pending if s.get("gameType") == game_type]
            self._auction.set_group_imports(folder, sends)
        self._announce(new, folders)

    async def _claim(self, folders: list[str]) -> list[dict[str, Any]]:
        game_types = gvs.game_types_for(folders)
        if not self._is_connected() or not game_types:
            return []
        try:
            claimed = await self._client.claim_group_sends(game_types)
        except Exception:
            logger.exception("Claiming group sends failed")
            return []
        known = {s["id"] for s in self._pending}
        new: list[dict[str, Any]] = []
        for send in claimed:
            if _valid(send) and send["id"] not in known:
                known.add(send["id"])
                new.append(send)
        if new:
            logger.info("Claimed %d group send(s)", len(new))
        return new

    def _announce(self, new: list[dict[str, Any]], folders: list[str]) -> None:
        if not new or self._notify_fn is None:
            return
        shown: list[dict[str, Any]] = []
        used: set[str] = set()
        for send in new:
            game_type = send.get("gameType")
            matching = [f for f in folders if gvs.GAME_TYPE_BY_FOLDER.get(f) == game_type]
            if matching:
                shown.append(send)
                used.update(matching)
        if not shown:
            return
        labels: list[str] = []
        for gv in gvs.GAME_VERSIONS:
            if gv.folder in used:
                label = self._auction.gv_label(gv.key)
                if label not in labels:
                    labels.append(label)
        try:
            self._notify_fn(notification_text(shown, labels))
        except Exception:
            logger.exception("Group send notification failed")
