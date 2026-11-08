"""Per-realm data state view model."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from tsm.workers.bridge import AsyncBridge

logger = logging.getLogger(__name__)

# Startup-only threshold: cached snapshot data older than this is shown as "Outdated"
# until the socket has pushed the current state.
_STALE_SECONDS = 90 * 60


@dataclass
class RealmSummary:
    display_name: str
    is_region: bool
    auctiondb_status: str = "Up to date"
    last_updated: int = 0  # unix timestamp
    game_version: str = "retail"
    region: str = ""
    name: str = ""
    user_realm_id: str = ""
    realm_id: int = 0
    auction_house_type: str = ""
    server_last_modified: int = 0


def _summary(s: object) -> RealmSummary:
    return RealmSummary(
        display_name=s.display_name,  # type: ignore[attr-defined]
        is_region=s.is_region,  # type: ignore[attr-defined]
        auctiondb_status=s.auctiondb_status,  # type: ignore[attr-defined]
        last_updated=s.last_updated,  # type: ignore[attr-defined]
        game_version=s.game_version,  # type: ignore[attr-defined]
        region=s.region,  # type: ignore[attr-defined]
        name=s.name,  # type: ignore[attr-defined]
        user_realm_id=getattr(s, "user_realm_id", ""),
        realm_id=getattr(s, "realm_id", 0),
        auction_house_type=getattr(s, "auction_house_type", ""),
        server_last_modified=getattr(s, "server_last_modified", 0),
    )


class RealmViewModel(QObject):
    data_updated = Signal()
    loading_changed = Signal(bool)
    error_occurred = Signal(str)
    addons_updated = Signal(list)  # [{name, version_str}] from the socket's addon event
    remove_failed = Signal(str)  # realm removal was refused, carries the message
    add_failed = Signal(str)  # adding a realm was refused, carries the message
    realm_tree_ready = Signal(dict)  # {gv label: {region: [realm option]}}

    def __init__(self, auction_service=None, auth_service=None, parent: QObject | None = None):
        super().__init__(parent)
        self._service = auction_service
        self._auth = auth_service
        self._summaries: list[RealmSummary] = []
        self._last_sync: int = 0
        self._loading = False
        self._had_new_data: bool = False
        self._written = 0
        self._apphelper_missing_gv: list[str] | None = None
        self._labels: dict[str, str] = {}
        self._tree_loaded = False
        self._tree_pending = False

    @property
    def loading(self) -> bool:
        return self._loading

    def _set_loading(self, value: bool) -> None:
        self._loading = value
        self.loading_changed.emit(value)

    @property
    def summaries(self) -> list[RealmSummary]:
        return self._summaries

    @property
    def last_sync(self) -> int:
        return self._last_sync

    @property
    def had_new_data(self) -> bool:
        return self._had_new_data

    @property
    def gv_labels(self) -> dict[str, str]:
        return self._labels

    @property
    def apphelper_missing_gv(self) -> list[str] | None:
        """Game-version dirs that are installed but missing the AppHelper addon folder.

        None  = not checked yet / no game-version dirs found yet.
        []    = AppHelper found for every installed game version.
        [gv]  = these game-version dirs exist but their AppHelper folder is absent.
        """
        return self._apphelper_missing_gv

    def load_snapshot(self) -> None:
        """Pre-populate the table from the last-known realm list (instant, no network)."""
        if self._service is None:
            return
        bridge = AsyncBridge(self)
        bridge.result_ready.connect(self._on_snapshot_received)
        bridge.run(self._service.get_snapshot())

    def load_realm_tree(self) -> None:
        """Fill the Add Realm dropdowns from the realm catalogue."""
        if self._service is None or self._tree_pending:
            return
        self._tree_pending = True
        service = self._service

        async def _load() -> tuple[dict, dict]:
            await service.load_catalog(refresh=not service.realm_tree())
            from tsm.wow.game_versions import GAME_VERSIONS

            labels = {gv.key: service.gv_label(gv.key) for gv in GAME_VERSIONS}
            return service.realm_tree(), labels

        bridge = AsyncBridge(self)
        bridge.result_ready.connect(self._on_tree)
        bridge.error_occurred.connect(lambda e: logger.warning("Realm catalogue: %s", e))
        bridge.finished.connect(lambda: setattr(self, "_tree_pending", False))
        bridge.run(_load())

    def _on_tree(self, result: object) -> None:
        if not isinstance(result, tuple):
            return
        tree, labels = result
        self._labels = labels
        if tree:
            self._tree_loaded = True
            self.realm_tree_ready.emit(tree)
        if self._summaries:
            self.data_updated.emit()

    def refresh_all(self) -> None:
        """Reload the followed realms and have the server push its data again."""
        if self._service is None:
            return
        self._set_loading(True)
        bridge = AsyncBridge(self)
        bridge.result_ready.connect(self.on_data_received)
        bridge.error_occurred.connect(self._on_error)
        bridge.finished.connect(lambda: self._set_loading(False))
        bridge.run(self._service.refresh_all_realms())

    def remove_local(self, summary: RealmSummary) -> None:
        """Drop one summary from the local list (optimistic UI update).

        Identity based rather than by index: the view groups rows across several
        tables, so a table row number no longer maps onto this list.
        """
        self._summaries = [s for s in self._summaries if s is not summary]

    def remove_realm(self, summary: RealmSummary) -> None:
        """Stop following a realm. Emits remove_failed if the server refuses."""
        if self._service is None:
            return
        if not summary.user_realm_id:
            self._on_remove_error("This realm is not linked to your account.")
            return
        bridge = AsyncBridge(self)
        bridge.error_occurred.connect(self._on_remove_error)
        bridge.run(self._service.remove_realm(summary.user_realm_id))

    def _on_remove_error(self, error_msg: str) -> None:
        logger.error("Realm removal failed: %s", error_msg)
        self.remove_failed.emit(error_msg)
        self.refresh_all()  # restore the optimistically hidden row

    def add_realm(self, realm_id: int, auction_house_type: str) -> None:
        """Follow a realm auction house on the account."""
        if self._service is None:
            return
        session = self._auth.current_session if self._auth is not None else None
        limit = session.realm_limit if session is not None else 10
        bridge = AsyncBridge(self)
        bridge.error_occurred.connect(self._on_add_error)
        bridge.run(self._service.add_realm(realm_id, auction_house_type, limit))

    def _on_add_error(self, error_msg: str) -> None:
        logger.error("Adding a realm failed: %s", error_msg)
        self.add_failed.emit(error_msg)

    def _on_snapshot_received(self, result: object) -> None:
        """Called with (statuses, saved_at) from DB. Shows cached data immediately."""
        if not isinstance(result, tuple):
            return
        statuses, saved_at = result
        if not isinstance(statuses, list) or not statuses:
            return
        # Don't overwrite if live data already arrived.
        if self._summaries:
            return
        now = int(time.time())
        is_outdated = saved_at and (now - saved_at) > _STALE_SECONDS
        self._summaries = [_summary(s) for s in statuses]
        for s in self._summaries:
            s.auctiondb_status = "Outdated" if is_outdated else "Up to date"
        self.data_updated.emit()

    def on_data_received(self, data: object) -> None:
        # data is AuctionData
        new_sync = getattr(data, "last_sync", 0)
        if new_sync:
            self._last_sync = new_sync

        addon_versions = getattr(data, "addon_versions", [])
        if addon_versions:
            self.addons_updated.emit(addon_versions)

        missing_gv = getattr(data, "apphelper_missing_gv", None)
        if missing_gv is not None:
            if missing_gv and missing_gv != self._apphelper_missing_gv:
                logger.info("AppHelper missing for %s", missing_gv)
            self._apphelper_missing_gv = missing_gv

        written = getattr(data, "written", 0)
        self._had_new_data = written > self._written
        self._written = written

        statuses = getattr(data, "realm_statuses", None)
        if statuses is not None:
            self._summaries = [_summary(s) for s in statuses]
        if not self._tree_loaded:
            self.load_realm_tree()
        self.data_updated.emit()

    def _on_error(self, error_msg: str) -> None:
        logger.error("Realm refresh error: %s", error_msg)
        self.error_occurred.emit(error_msg)
