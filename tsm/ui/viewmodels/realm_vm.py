"""Per-realm data state view model."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from tsm.workers.bridge import AsyncBridge

logger = logging.getLogger(__name__)

# Data older than this is shown as "Outdated", 1.5× the normal 60 min refresh interval.
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


class RealmViewModel(QObject):
    data_updated = Signal()
    loading_changed = Signal(bool)
    error_occurred = Signal(str)
    addons_updated = Signal(list)  # emits list[dict] from status API

    def __init__(self, auction_service=None, parent: QObject | None = None):
        super().__init__(parent)
        self._service = auction_service
        self._summaries: list[RealmSummary] = []
        self._last_sync: int = 0
        self._loading = False
        self._had_new_data: bool = False

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

    def load_snapshot(self) -> None:
        """Pre-populate the table from the last-known realm list (instant, no network)."""
        if self._service is None:
            return
        bridge = AsyncBridge(self)
        bridge.result_ready.connect(self._on_snapshot_received)
        bridge.run(self._service.get_snapshot())

    def refresh_all(self) -> None:
        if self._service is None:
            return
        self._set_loading(True)
        # Mark all displayed rows as "Updating..." while the fetch is in progress.
        for s in self._summaries:
            s.auctiondb_status = "Updating..."
        if self._summaries:
            self.data_updated.emit()
        bridge = AsyncBridge(self)
        bridge.result_ready.connect(self._on_data_received)
        bridge.error_occurred.connect(self._on_error)
        bridge.finished.connect(lambda: self._set_loading(False))
        bridge.run(self._service.refresh_all_realms())

    def remove_realm(self, game_version: str, region: str, name: str) -> None:
        """Call realms2/remove API and refresh."""
        if self._service is None:
            return
        bridge = AsyncBridge(self)
        bridge.result_ready.connect(lambda _: self.refresh_all())
        bridge.run(self._service.remove_realm(game_version, region, name))

    def _on_snapshot_received(self, result: object) -> None:
        """Called with (statuses, saved_at) from DB. Shows cached data immediately."""
        if not isinstance(result, tuple):
            return
        statuses, saved_at = result
        if not isinstance(statuses, list) or not statuses:
            return
        # Don't overwrite if refresh_all already completed (race: very fast network).
        if self._summaries:
            return
        # Staleness is based on when we last synced with the API, not on the
        # server-side lastModified timestamps (region blobs update less often than realms).
        now = int(time.time())
        is_outdated = saved_at and (now - saved_at) > _STALE_SECONDS
        adb_status = "Outdated" if is_outdated else "Up to date"
        self._summaries = [
            RealmSummary(
                display_name=s.display_name,
                is_region=s.is_region,
                auctiondb_status=adb_status,
                last_updated=s.last_updated,
                game_version=s.game_version,
                region=s.region,
                name=s.name,
            )
            for s in statuses
        ]
        self.data_updated.emit()

    def _on_data_received(self, data: object) -> None:
        # data is AuctionData
        statuses = getattr(data, "realm_statuses", [])
        if not statuses:
            # Service returned no realms, WoW install or AppHelper not detected yet.
            # Keep existing rows visible; reset any "Updating..." labels.
            for s in self._summaries:
                if s.auctiondb_status == "Updating...":
                    s.auctiondb_status = "Up to date"
            self.data_updated.emit()
            return
        self._summaries = [
            RealmSummary(
                display_name=s.display_name,
                is_region=s.is_region,
                auctiondb_status=s.auctiondb_status,
                last_updated=s.last_updated,
                game_version=s.game_version,
                region=s.region,
                name=s.name,
            )
            for s in statuses
        ]
        self._last_sync = getattr(data, "last_sync", 0)
        self._had_new_data = bool(getattr(data, "entries", {}))
        self.data_updated.emit()

        addon_versions = getattr(data, "addon_versions", [])
        if addon_versions:
            self.addons_updated.emit(addon_versions)

    def _on_error(self, error_msg: str) -> None:
        logger.error("Realm refresh error: %s", error_msg)
        self.error_occurred.emit(error_msg)
