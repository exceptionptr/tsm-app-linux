"""AuctionDataService: event driven AuctionDB sync, as in the official 1.0.9 client.

The backend no longer has a status endpoint to poll. Instead:

1. The realm and region catalogue comes from realm-api (cached in SQLite so the
   tab works offline), and the realms the account follows from user-realms.
2. The socket pushes one event per data string (realm_auctiondb,
   realm_shopping, region_auctiondb), each with lastModified and a presigned
   download URL, right after connecting and again whenever new data lands.
3. A string is downloaded only if some AppData.lua that should hold it is
   older, at most four at a time, and then written into every WoW install's
   AppData.lua for that game version. Writes are batched per file: the socket
   sends a dozen strings in a burst, and each file is rewritten once for them.
4. Realms the account no longer follows are pruned from AppData.lua.
5. APP_INFO (version, news, message) is written on every app_info event and
   every 15 minutes while connected.

Keys follow the official writer: a realm auction house is keyed by the realm's
localized name, with "-Horde"/"-Alliance" for a faction auction house, and a
region by its game version prefix plus the region code ("EU", "BCC-EU",
"HC-EU", "Forever-EU"). See tsm/wow/game_versions.py.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from tsm.api.client import TSMApiClient, TSMApiError
from tsm.api.types import AddonRelease, Realm, Region, UserRealm
from tsm.core.models.auction import AppInfo, AuctionData, RealmStatus
from tsm.storage.auction_cache import AuctionCache
from tsm.wow import game_versions as gvs
from tsm.wow.lua_writer import AppDataFile, render_app_info
from tsm.wow.utils import installed_versions, normalize_wow_base

logger = logging.getLogger(__name__)

APPHELPER = "TradeSkillMaster_AppHelper"
DOWNLOAD_CONCURRENCY = 4
WRITE_DEBOUNCE_SECONDS = 1.5
APP_INFO_INTERVAL_SECONDS = 15 * 60
# The server does not push a newly followed realm on its own, and a reconnect
# right after the follow is too early. One reconnect after this pause fetches it.
NEW_REALM_RECONNECT_DELAY_SECONDS = 5.0

_REALM_TAG = "AUCTIONDB_NON_COMMODITY_DATA"
_REGION_TAG = "AUCTIONDB_REGION_STAT"
_AH_TYPES = ("ALL", "ALLIANCE", "HORDE")

ChangeListener = Callable[[AuctionData], Awaitable[None] | None]


class RealmLimitReached(RuntimeError):
    pass


def _ci_child(parent: Path, name: str) -> Path | None:
    """parent/name, matching the last segment case-insensitively (Wine prefixes)."""
    direct = parent / name
    if direct.exists():
        return direct
    try:
        lower = name.lower()
        for child in parent.iterdir():
            if child.name.lower() == lower:
                return child
    except OSError:
        pass
    return None


def apphelper_folder(base: Path, folder: str) -> Path | None:
    p: Path | None = base / folder
    for seg in ("Interface", "AddOns", APPHELPER):
        if p is None:
            return None
        p = _ci_child(p, seg)
    return p if p is not None and p.is_dir() else None


def _int(v: object) -> int:
    try:
        return int(v)  # type: ignore[call-overload,no-any-return]
    except (TypeError, ValueError):
        return 0


def _ah_type_from_api(t: str) -> str:
    return (t or "").upper()


@dataclass
class _Write:
    tag: str
    key: str
    data: str
    time: int
    auction_house_id: int | None


@dataclass
class _FileState:
    """What one AppData.lua holds, and the writes waiting for it."""

    stored: dict[tuple[str, str], int] | None = None
    pending: list[_Write] = field(default_factory=list)
    removals: set[str] = field(default_factory=set)
    flush: asyncio.Task[None] | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class AuctionDataService:
    def __init__(
        self,
        api_client: TSMApiClient | None = None,
        cache: AuctionCache | None = None,
        wow_detector: Any = None,
        app_version: str = "1.0.9",
    ):
        self._client = api_client
        self._cache = cache
        self._detector = wow_detector
        self._app_version = app_version
        self._user_id = ""
        self._realms: dict[int, Realm] = {}
        self._regions: dict[int, Region] = {}
        self._gv_labels: dict[str, str] = {}  # folder -> label from the API
        self._user_realms: list[UserRealm] = []
        self._user_realms_loaded = False
        # Newest lastModified the server announced: ("realm", id, ahType) / ("region", id, "")
        self._server_lm: dict[tuple[str, int, str], int] = {}
        self._in_flight: dict[tuple[str, int, str], int] = {}
        self._files: dict[Path, _FileState] = {}
        self._sem: asyncio.Semaphore | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self._listeners: list[ChangeListener] = []
        self._app_info: dict[str, Any] = {}
        self._app_info_task: asyncio.Task[None] | None = None
        self._addons: list[AddonRelease] = []
        self._addon_listeners: list[Callable[[list[AddonRelease]], Awaitable[Any] | Any]] = []
        self._last_event = 0
        self._written = 0
        self.reconnect: Callable[[], Awaitable[None]] | None = None

    # ------------------------------------------------------------------ #
    # Wiring
    # ------------------------------------------------------------------ #

    def add_listener(self, fn: ChangeListener) -> None:
        """Called with a fresh AuctionData whenever the realm list or its state changes."""
        self._listeners.append(fn)

    def add_addon_listener(self, fn: Callable[[list[AddonRelease]], Any]) -> None:
        self._addon_listeners.append(fn)

    @property
    def addons(self) -> list[AddonRelease]:
        return list(self._addons)

    @property
    def user_realms(self) -> list[UserRealm]:
        return list(self._user_realms)

    def gv_label(self, key: str) -> str:
        gv = gvs.BY_KEY.get(key)
        if gv is None:
            return key
        return self._gv_labels.get(gv.folder) or gv.label

    def _spawn(self, coro: Awaitable[Any]) -> asyncio.Task[Any]:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _emit(self) -> None:
        data = await self.snapshot()
        for fn in self._listeners:
            try:
                r = fn(data)
                if asyncio.iscoroutine(r):
                    await r
            except Exception:
                logger.exception("Auction listener failed")

    # ------------------------------------------------------------------ #
    # Catalogue and user realms
    # ------------------------------------------------------------------ #

    async def load_catalog(self, refresh: bool = True) -> None:
        """Realm and region catalogue: the cached copy first, then the network."""
        if self._cache is not None and not self._realms:
            with contextlib.suppress(Exception):
                self._apply_catalog(
                    await self._cache.get_json("realms"),
                    await self._cache.get_json("regions"),
                    await self._cache.get_json("game_versions"),
                )
        if not refresh or self._client is None:
            return
        try:
            realms, regions = await asyncio.gather(self._client.realms(), self._client.regions())
        except Exception as e:
            if not self._realms:
                raise
            logger.warning("Realm catalogue refresh failed, using the cached copy: %s", e)
            return
        game_versions: list[Any] = []
        try:
            game_versions = list(await self._client.game_versions())
        except Exception as e:
            logger.warning("Game version list unavailable: %s", e)
        self._apply_catalog(realms, regions, game_versions)
        if self._cache is not None:
            await self._cache.put_json("realms", realms)
            await self._cache.put_json("regions", regions)
            if game_versions:
                await self._cache.put_json("game_versions", game_versions)
        logger.info("Realm catalogue: %d realms, %d regions", len(realms), len(regions))

    def _apply_catalog(self, realms: Any, regions: Any, game_versions: Any) -> None:
        if isinstance(realms, list):
            self._realms = {r["realmId"]: cast(Realm, r) for r in realms if isinstance(r, dict)}
        if isinstance(regions, list):
            self._regions = {r["regionId"]: cast(Region, r) for r in regions if isinstance(r, dict)}
        for r in self._realms.values():
            region = r.get("region")
            if isinstance(region, dict) and r.get("regionId") not in self._regions:
                self._regions[r["regionId"]] = region
        if isinstance(game_versions, list):
            self._gv_labels = {
                g["folder"]: g["label"]
                for g in game_versions
                if isinstance(g, dict) and g.get("folder") and g.get("label")
            }

    async def start(self, user_id: str) -> None:
        """Called after login: catalogue, followed realms, migration, pruning."""
        self._user_id = user_id
        if self._app_info_task is None or self._app_info_task.done():
            # Not in self._tasks: flush_all() waits for those, and this one never ends.
            self._app_info_task = asyncio.ensure_future(self._app_info_loop())
        await self.load_catalog()
        await self.load_user_realms()
        await self.migrate_local_realms()

    async def stop(self) -> None:
        if self._app_info_task is not None:
            self._app_info_task.cancel()
            with contextlib.suppress(BaseException):
                await self._app_info_task
            self._app_info_task = None
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            with contextlib.suppress(BaseException):
                await task
        self._tasks.clear()
        self._user_realms = []
        self._user_realms_loaded = False
        self._server_lm.clear()
        self._in_flight.clear()
        self._files.clear()

    async def load_user_realms(self) -> None:
        if self._client is None or not self._user_id:
            return
        self._user_realms = await self._client.user_realms(self._user_id)
        self._user_realms_loaded = True
        logger.info("Account follows %d realm auction houses", len(self._user_realms))
        await self._prune()
        await self._emit()

    def _followed(self, realm_id: int, ah_type: str) -> UserRealm | None:
        for ur in self._user_realms:
            if ur["realmId"] == realm_id and ur["auctionHouseType"].upper() == ah_type:
                return ur
        return None

    def _followed_regions(self) -> set[int]:
        out = set()
        for ur in self._user_realms:
            realm = self._realms.get(ur["realmId"])
            if realm is not None:
                out.add(realm["regionId"])
        return out

    async def add_realm(self, realm_id: int, auction_house_type: str, limit: int | None) -> None:
        """Follow a realm auction house. limit is the account's realm limit (None = no limit)."""
        if self._client is None or not self._user_id:
            raise RuntimeError("Not signed in")
        ah_type = auction_house_type.upper()
        if self._followed(realm_id, ah_type):
            return
        if limit is not None and len(self._user_realms) >= limit:
            raise RealmLimitReached(
                f"Your account can follow {limit} realms. Remove one first or upgrade "
                "your TSM premium tier."
            )
        await self._client.add_user_realm(self._user_id, realm_id, ah_type)
        await self.load_user_realms()
        if self.reconnect is not None:
            self._spawn(self._reconnect_for_realm(realm_id, ah_type))

    async def _reconnect_for_realm(self, realm_id: int, ah_type: str) -> None:
        """Reconnect once, shortly after a follow, unless the realm's data already came."""
        await asyncio.sleep(NEW_REALM_RECONNECT_DELAY_SECONDS)
        if self._server_lm.get(("realm", realm_id, ah_type)):
            return
        if self._followed(realm_id, ah_type) is None or self.reconnect is None:
            return
        logger.info("No data yet for realm %d/%s, reconnecting once", realm_id, ah_type)
        await self.reconnect()

    async def remove_realm(self, user_realm_id: str) -> None:
        if self._client is None:
            raise RuntimeError("Not signed in")
        await self._client.delete_user_realm(user_realm_id)
        await self.load_user_realms()

    async def migrate_local_realms(self) -> None:
        """Move the old local-only Classic Era / Anniversary realm list to the account.

        Before the new backend, realms of those game versions were not stored
        server side, so the app kept its own list. Each row becomes a user realm
        (when the catalogue knows it) and is then deleted.
        """
        if self._cache is None or self._client is None or not self._user_id:
            return
        try:
            rows = await self._cache.get_all_user_realms()
        except Exception:
            return
        if not rows:
            return
        changed = False
        for game_version, region, name in rows:
            match = self._match_legacy(game_version, region, name)
            if match is None:
                logger.warning(
                    "Legacy realm %s/%s/%s not in the catalogue", game_version, region, name
                )
            else:
                realm_id, ah_type = match
                if not self._followed(realm_id, ah_type):
                    try:
                        await self._client.add_user_realm(self._user_id, realm_id, ah_type)
                        changed = True
                        logger.info("Moved local realm %s (%s) to the account", name, region)
                    except TSMApiError as e:
                        logger.warning("Could not move local realm %s: %s", name, e)
                        continue
            await self._cache.remove_user_realm(game_version, region, name)
        if changed:
            await self.load_user_realms()

    def _match_legacy(self, game_version: str, region: str, name: str) -> tuple[int, str] | None:
        gv = gvs.BY_KEY.get(game_version)
        for realm in self._realms.values():
            r = realm["region"]
            if gv is not None and gvs.folder_for_region(r.get("gameVersion", "")) != gv.folder:
                continue
            key = gvs.region_key(r.get("gameVersion", ""), r.get("regionPrefix", ""))
            if key != region and r.get("regionPrefix", "").upper() != region.upper():
                continue
            for ah in realm.get("auctionHouses") or [{"type": "All"}]:  # type: ignore[typeddict-item]
                ah_type = _ah_type_from_api(ah.get("type", "All"))
                for n in (realm["localizedName"], realm["name"]):
                    if name in (n, gvs.realm_key(n, ah_type)):
                        return realm["realmId"], ah_type
        return None

    # ------------------------------------------------------------------ #
    # WoW targets
    # ------------------------------------------------------------------ #

    def _bases(self) -> list[Path]:
        installs = self._detector.installs if self._detector is not None else []
        seen: list[Path] = []
        for inst in installs:
            b = normalize_wow_base(Path(inst.path))
            if b not in seen:
                seen.append(b)
        return seen

    def _targets(self, folder: str) -> list[Path]:
        """AppData.lua paths for one game version, across all WoW installs.

        Like the official client, a game version is written only when its
        AppHelper folder has AppData.lua or TradeSkillMaster_AppHelper.lua.
        """
        out = []
        for base in self._bases():
            d = apphelper_folder(base, folder)
            if d is None:
                continue
            appdata = _ci_child(d, "AppData.lua")
            if appdata is None and _ci_child(d, "TradeSkillMaster_AppHelper.lua") is None:
                continue
            out.append(appdata or d / "AppData.lua")
        return out

    def apphelper_missing(self) -> list[str] | None:
        bases = self._bases()
        if not bases:
            return None
        checked = False
        missing = []
        for base in bases:
            for folder in installed_versions(base):
                checked = True
                if apphelper_folder(base, folder) is None and folder not in missing:
                    missing.append(folder)
        return missing if checked else None

    def _state(self, path: Path) -> _FileState:
        st = self._files.get(path)
        if st is None:
            st = self._files[path] = _FileState()
        return st

    async def _stored(self, path: Path) -> dict[tuple[str, str], int]:
        st = self._state(path)
        if st.stored is None:

            def load() -> dict[tuple[str, str], int]:
                f = AppDataFile(path)
                return {(e.tag, e.key): e.time for e in f.entries if not e.raw}

            st.stored = await asyncio.to_thread(load)
        return st.stored

    async def stored_time(self, folder: str, tag: str, key: str) -> int:
        """Oldest timestamp of (tag, key) across the installs of a game version."""
        times = []
        for path in self._targets(folder):
            times.append((await self._stored(path)).get((tag, key), 0))
        return min(times) if times else 0

    async def _newest_for_key(self, folder: str, key: str) -> int:
        best = 0
        for path in self._targets(folder):
            stored = await self._stored(path)
            for (_tag, k), t in stored.items():
                if k == key and t > best:
                    best = t
        return best

    # ------------------------------------------------------------------ #
    # Socket events
    # ------------------------------------------------------------------ #

    async def handle_event(self, name: str, payload: Any) -> None:
        self._last_event = int(time.time())
        if name in ("realm_auctiondb", "realm_shopping"):
            await self._on_realm_string(payload)
        elif name == "region_auctiondb":
            await self._on_region_string(payload)
        elif name == "app_info":
            if isinstance(payload, dict):
                self._app_info = payload
                await self.write_app_info()
        elif name == "addon":
            data = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(data, list):
                self._addons = [
                    cast(AddonRelease, a) for a in data if isinstance(a, dict) and a.get("addon")
                ]
                for fn in self._addon_listeners:
                    try:
                        r = fn(self.addons)
                        if asyncio.iscoroutine(r):
                            self._spawn(r)
                    except Exception:
                        logger.exception("Addon listener failed")
                await self._emit()
        else:
            logger.debug("Unhandled socket event %s", name)

    async def _on_realm_string(self, p: Any) -> None:
        if not isinstance(p, dict):
            return
        realm_id = _int(p.get("realmId"))
        ah_type = _ah_type_from_api(str(p.get("auctionHouseType", "")))
        realm = self._realms.get(realm_id)
        if realm is None:
            await self.load_catalog()
            realm = self._realms.get(realm_id)
            if realm is None:
                logger.warning("Data for unknown realm %d ignored", realm_id)
                return
        if self._user_realms_loaded and self._followed(realm_id, ah_type) is None:
            logger.info("Data for realm %d/%s not followed, ignored", realm_id, ah_type)
            return
        region = realm["region"]
        folder = gvs.folder_for_region(region.get("gameVersion", ""))
        if folder is None:
            return
        ah_id = None
        for ah in realm.get("auctionHouses") or []:
            if _ah_type_from_api(ah.get("type", "")) == ah_type:
                ah_id = ah.get("auctionHouseId")
        key = gvs.realm_key(realm["localizedName"], ah_type)
        await self._offer(("realm", realm_id, ah_type), folder, p, key, ah_id)

    async def _on_region_string(self, p: Any) -> None:
        if not isinstance(p, dict):
            return
        region_id = _int(p.get("regionId"))
        region = self._regions.get(region_id)
        if region is None:
            logger.warning("Data for unknown region %d ignored", region_id)
            return
        gv_name = region.get("gameVersion", "")
        folder = gvs.folder_for_region(gv_name)
        key = gvs.region_key(gv_name, region.get("regionPrefix", ""))
        if folder is None or key is None:
            return
        await self._offer(("region", region_id, ""), folder, p, key, None)

    async def _offer(
        self,
        status_key: tuple[str, int, str],
        folder: str,
        p: dict[str, Any],
        key: str,
        ah_id: int | None,
    ) -> None:
        tag = str(p.get("stringType") or "")
        lm = _int(p.get("lastModified"))
        url = p.get("url")
        if not tag or not lm or not isinstance(url, str):
            return
        if lm > self._server_lm.get(status_key, 0):
            self._server_lm[status_key] = lm
        targets = self._targets(folder)
        if not targets:
            logger.debug("No AppHelper for %s, %s/%s not downloaded", folder, tag, key)
            return
        stale = [t for t in targets if (await self._stored(t)).get((tag, key), 0) < lm]
        if not stale:
            return
        self._in_flight[status_key] = self._in_flight.get(status_key, 0) + 1
        await self._emit()
        self._spawn(self._download(status_key, stale, _Write(tag, key, "", lm, ah_id), url))

    async def _download(
        self, status_key: tuple[str, int, str], targets: list[Path], w: _Write, url: str
    ) -> None:
        if self._sem is None:
            self._sem = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)
        try:
            async with self._sem:
                assert self._client is not None
                logger.info("Downloading %s / %s (%d)", w.tag, w.key, w.time)
                try:
                    raw = await self._client.download(url)
                except Exception as e:
                    logger.warning("Download of %s / %s failed: %s", w.tag, w.key, e)
                    return
            if raw is None:
                logger.info("%s / %s superseded on the server (404)", w.tag, w.key)
                return
            text = raw.decode("utf-8", errors="replace").strip()
            if text.startswith("return "):
                text = text[7:]
            if not text.startswith("{") or "]]" in text:
                logger.error("Unexpected content for %s / %s, not written", w.tag, w.key)
                return
            w.data = text
            for path in targets:
                self._queue_write(path, w)
        finally:
            n = self._in_flight.get(status_key, 1) - 1
            if n <= 0:
                self._in_flight.pop(status_key, None)
            else:
                self._in_flight[status_key] = n

    def _queue_write(self, path: Path, w: _Write) -> None:
        st = self._state(path)
        st.pending.append(w)
        if st.flush is None or st.flush.done():
            st.flush = self._spawn(self._flush(path))

    def _queue_removal(self, path: Path, keys: Iterable[str]) -> None:
        st = self._state(path)
        st.removals.update(keys)
        if st.flush is None or st.flush.done():
            st.flush = self._spawn(self._flush(path))

    async def _flush(self, path: Path) -> None:
        await asyncio.sleep(WRITE_DEBOUNCE_SECONDS)
        st = self._state(path)
        async with st.lock:
            writes, st.pending = st.pending, []
            removals, st.removals = st.removals, set()
            if not writes and not removals:
                return

            def apply() -> tuple[dict[tuple[str, str], int], int, list[str]]:
                f = AppDataFile(path)
                removed = f.remove(removals) if removals else []
                n = 0
                for w in writes:
                    if f.update(w.tag, w.key, w.data, w.time, w.auction_house_id):
                        n += 1
                f.save()
                return {(e.tag, e.key): e.time for e in f.entries if not e.raw}, n, removed

            try:
                st.stored, n, removed = await asyncio.to_thread(apply)
            except Exception:
                logger.exception("Failed to write %s", path)
                st.stored = None
                return
        self._written += n
        if removed:
            logger.info("Removed %s from %s", ", ".join(removed), path)
        await self._emit()

    async def flush_all(self) -> None:
        """Wait for every queued download and write (tests and shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    # ------------------------------------------------------------------ #
    # Pruning
    # ------------------------------------------------------------------ #

    async def _prune(self) -> None:
        """Drop AppData keys of known realms the account no longer follows."""
        wanted: set[tuple[str, str]] = set()
        for ur in self._user_realms:
            realm = self._realms.get(ur["realmId"])
            if realm is None:
                logger.warning("Followed realm %d not in the catalogue, not pruning", ur["realmId"])
                return
            folder = gvs.folder_for_region(realm["region"].get("gameVersion", ""))
            if folder:
                wanted.add((folder, gvs.realm_key(realm["localizedName"], ur["auctionHouseType"])))
        by_folder: dict[str, set[str]] = {}
        for realm in self._realms.values():
            folder = gvs.folder_for_region(realm["region"].get("gameVersion", ""))
            if folder is None:
                continue
            keys = by_folder.setdefault(folder, set())
            for n in {realm["localizedName"], realm["name"]}:
                for t in _AH_TYPES:
                    k = gvs.realm_key(n, t)
                    if (folder, k) not in wanted:
                        keys.add(k)
        for folder, keys in by_folder.items():
            for path in self._targets(folder):
                stored = await self._stored(path)
                present = {k for (_t, k) in stored} & keys
                if present:
                    self._queue_removal(path, present)

    # ------------------------------------------------------------------ #
    # APP_INFO
    # ------------------------------------------------------------------ #

    async def _app_info_loop(self) -> None:
        while True:
            await asyncio.sleep(APP_INFO_INTERVAL_SECONDS)
            if self._user_realms_loaded:
                try:
                    await self.write_app_info()
                except Exception:
                    logger.exception("Writing APP_INFO failed")

    async def write_app_info(self) -> None:
        now = int(time.time())
        info = self._app_info
        blob = render_app_info(
            self._app_version, now, info.get("message") or {}, info.get("news") or []
        )
        for gv in gvs.GAME_VERSIONS:
            for path in self._targets(gv.folder):
                self._queue_write(path, _Write("APP_INFO", "Global", blob, now, None))

    # ------------------------------------------------------------------ #
    # UI state
    # ------------------------------------------------------------------ #

    def _status_text(self, key: tuple[str, int, str], local: int) -> str:
        if self._in_flight.get(key):
            return "Updating..."
        server = self._server_lm.get(key, 0)
        if not local:
            return "Waiting"
        if server and local < server:
            return "Outdated"
        return "Up to date"

    async def statuses(self) -> list[RealmStatus]:
        out: list[RealmStatus] = []
        regions_done: set[int] = set()
        for ur in self._user_realms:
            realm = self._realms.get(ur["realmId"])
            if realm is None:
                continue
            region = realm["region"]
            gv_name = region.get("gameVersion", "")
            folder = gvs.folder_for_region(gv_name)
            gv = gvs.BY_FOLDER.get(folder or "")
            region_key = gvs.region_key(gv_name, region.get("regionPrefix", "")) or region.get(
                "regionPrefix", ""
            ).upper()
            ah_type = ur["auctionHouseType"].upper()
            key = gvs.realm_key(realm["localizedName"], ah_type)
            sk = ("realm", realm["realmId"], ah_type)
            local = await self._newest_for_key(folder, key) if folder else 0
            server = self._server_lm.get(sk, 0)
            if not server:
                for ah in realm.get("auctionHouses") or []:
                    if _ah_type_from_api(ah.get("type", "")) == ah_type:
                        server = _int(ah.get("lastModified"))
            out.append(
                RealmStatus(
                    display_name=f"{region_key}-{key}",
                    is_region=False,
                    auctiondb_status=self._status_text(sk, local),
                    last_updated=local,
                    game_version=gv.key if gv else gv_name,
                    region=region_key,
                    name=key,
                    user_realm_id=ur["id"],
                    realm_id=realm["realmId"],
                    auction_house_type=ah_type,
                    server_last_modified=server,
                )
            )
            rid = realm["regionId"]
            if rid in regions_done:
                continue
            regions_done.add(rid)
            rsk = ("region", rid, "")
            rlocal = await self._newest_for_key(folder, region_key) if folder else 0
            out.append(
                RealmStatus(
                    display_name=region_key,
                    is_region=True,
                    auctiondb_status=self._status_text(rsk, rlocal),
                    last_updated=rlocal,
                    game_version=gv.key if gv else gv_name,
                    region=region_key,
                    name=region_key,
                    server_last_modified=self._server_lm.get(rsk, _int(region.get("lastModified"))),
                )
            )
        return out

    def current(self) -> AuctionData:
        """Sync snapshot for the UI. Statuses are filled by current_async."""
        return AuctionData(
            app_info=AppInfo(
                version=self._app_version,
                last_sync=self._last_event,
                message_id=_int((self._app_info.get("message") or {}).get("id")),
                message_text=str((self._app_info.get("message") or {}).get("msg") or ""),
                news=list(self._app_info.get("news") or []),
            ),
            addon_versions=[
                {"name": a.get("addon", ""), "version_str": str(a.get("version", "")).lstrip("v")}
                for a in self._addons
            ],
            written=self._written,
            apphelper_missing_gv=self.apphelper_missing(),
        )

    async def snapshot(self) -> AuctionData:
        data = self.current()
        data.realm_statuses = await self.statuses()
        if self._cache is not None and data.realm_statuses:
            with contextlib.suppress(Exception):
                await self._cache.save_snapshot(data.realm_statuses)
        return data

    async def refresh_all_realms(self) -> AuctionData:
        """Manual refresh: reload the followed realms and ask the server to push again."""
        with contextlib.suppress(Exception):
            await self.load_user_realms()
        if self.reconnect is not None:
            await self.reconnect()
        return await self.snapshot()

    async def get_snapshot(self) -> tuple[list[RealmStatus], int]:
        """Last known realm list from the DB, for display before the first sync."""
        if self._cache is None:
            return [], 0
        return await self._cache.load_snapshot()

    def realm_tree(self) -> dict[str, dict[str, list[dict[str, Any]]]]:
        """{gv label: {region key: [{realm_id, ah_type, name}]}} for the Add Realm dropdown."""
        tree: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for realm in self._realms.values():
            region = realm["region"]
            gv_name = region.get("gameVersion", "")
            folder = gvs.folder_for_region(gv_name)
            region_key = gvs.region_key(gv_name, region.get("regionPrefix", ""))
            gv = gvs.BY_FOLDER.get(folder or "")
            if gv is None or region_key is None:
                continue
            label = self.gv_label(gv.key)
            node = tree.setdefault(label, {}).setdefault(region_key, [])
            ahs = realm.get("auctionHouses") or []
            types = [_ah_type_from_api(a.get("type", "")) for a in ahs] or ["ALL"]
            for t in types:
                name = realm["localizedName"]
                node.append(
                    {
                        "realm_id": realm["realmId"],
                        "ah_type": t,
                        "name": name if t == "ALL" else f"{name} ({t.capitalize()})",
                        "game_version": gv.key,
                    }
                )
        for regions in tree.values():
            for lst in regions.values():
                lst.sort(key=lambda r: r["name"].lower())
        return tree
