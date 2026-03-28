"""APScheduler 4.x setup on the asyncio event loop."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from tsm.api.types import AddonVersionInfo
    from tsm.core.models.auction import AuctionData, RealmStatus
    from tsm.core.models.config import AppConfig, WoWInstall

from apscheduler import AsyncScheduler
from apscheduler.triggers.interval import IntervalTrigger

from tsm.workers.jobs import job_auction_refresh, job_auth_refresh, job_backup

logger = logging.getLogger(__name__)


class AuctionServiceProtocol(Protocol):
    async def get_snapshot(self) -> tuple[list[RealmStatus], int]: ...
    async def refresh_all_realms(self) -> AuctionData: ...
    async def add_realm(self, game_version: str, realm_id: int) -> None: ...


class AuthServiceProtocol(Protocol):
    async def refresh_token(self) -> None: ...


class UpdateServiceProtocol(Protocol):
    async def check_and_update(self, addon_versions: list[AddonVersionInfo]) -> list[str]: ...


class ConfigStoreProtocol(Protocol):
    def load(self) -> AppConfig: ...
    def save(self, config: AppConfig) -> None: ...


class WoWDetectorProtocol(Protocol):
    async def scan(self) -> list[WoWInstall]: ...
    async def get_installs(self) -> list[WoWInstall]: ...
    def set_installs(self, installs: list[WoWInstall]) -> None: ...


class BackupServiceProtocol(Protocol):
    def run(
        self,
        period_minutes: int,
        retain_days: int,
        extra_installs: list[WoWInstall] | None = None,
    ) -> list[Path]: ...


@dataclass
class ServiceContainer:
    """Holds references to all services needed by scheduled jobs."""

    auth: AuthServiceProtocol
    auction: AuctionServiceProtocol
    wow_detector: WoWDetectorProtocol
    updater: UpdateServiceProtocol
    backup: BackupServiceProtocol | None = None
    config_store: ConfigStoreProtocol | None = None
    backup_notify_fn: Callable[[str], None] | None = None
    addon_notify_fn: Callable[[str], None] | None = None
    auction_data_fn: Callable[[AuctionData], None] | None = None
    wow_warn_fn: Callable[[str], None] | None = None


class JobScheduler:
    def __init__(
        self,
        services: ServiceContainer,
        skip_detection: bool = False,
        skip_auto_sync: bool = False,
        skip_auto_backup: bool = False,
    ):
        self._svc = services
        self._skip_detection = skip_detection
        self._skip_auto_sync = skip_auto_sync
        self._skip_auto_backup = skip_auto_backup
        self._scheduler: AsyncScheduler | None = None
        self._runner_task: asyncio.Task[None] | None = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            return

        svc = self._svc
        skip_detection = self._skip_detection
        skip_auto_sync = self._skip_auto_sync
        skip_auto_backup = self._skip_auto_backup
        self._scheduler = AsyncScheduler()

        # Keep __aenter__ and __aexit__ in the same task (anyio cancel scope requirement).
        # All scheduler work runs inside _scheduler_task; stop() signals it via scheduler.stop().
        scheduler = self._scheduler

        async def _scheduler_task() -> None:
            assert scheduler is not None
            now = datetime.now(UTC)

            # Startup: resolve WoW installs from config, or auto-detect once.
            # No periodic rescanning needed; user can add paths via Settings.
            await _resolve_wow_installs(svc, skip_scan=skip_detection)

            async with scheduler:
                # Auction poller: check TSM API every 5 minutes for new data.
                # refresh_all_realms() is differential so only changed blobs are
                # downloaded. First poll after 5 min; startup refresh already ran at login.
                if not skip_auto_sync:
                    await scheduler.add_schedule(
                        job_auction_refresh,
                        IntervalTrigger(minutes=5, start_time=now + timedelta(minutes=5)),
                        id="auction_refresh",
                        kwargs={"services": svc},
                    )
                # Backup: schedule at the user-configured period.
                if not skip_auto_backup:
                    backup_minutes = (
                        svc.config_store.load().backup_period_minutes
                        if svc.config_store is not None
                        else 60
                    )
                    await scheduler.add_schedule(
                        job_backup,
                        IntervalTrigger(
                            minutes=backup_minutes,
                            start_time=now + timedelta(minutes=backup_minutes),
                        ),
                        id="backup",
                        kwargs={"services": svc},
                    )
                await scheduler.add_schedule(
                    job_auth_refresh,
                    IntervalTrigger(minutes=25, start_time=now + timedelta(minutes=25)),
                    id="auth_refresh",
                    kwargs={"services": svc},
                )
                logger.info(
                    "JobScheduler started (detection=%s sync=%s backup=%s)",
                    not skip_detection,
                    not skip_auto_sync,
                    not skip_auto_backup,
                )
                await scheduler.run_until_stopped()

        self._runner_task = asyncio.create_task(_scheduler_task())
        self._started = True

    async def stop(self) -> None:
        if self._started and self._scheduler is not None:
            await self._scheduler.stop()
            if self._runner_task is not None:
                await self._runner_task
            self._started = False
            self._scheduler = None
            self._runner_task = None


async def _resolve_wow_installs(svc: ServiceContainer, skip_scan: bool = False) -> None:
    """Load WoW paths from config into the detector; auto-detect if missing or invalid."""
    if svc.config_store is None:
        return
    cfg = svc.config_store.load()
    valid = [i for i in cfg.wow_installs if Path(i.path).exists()]
    if valid:
        svc.wow_detector.set_installs(valid)
        logger.info("WoW: using %d configured install(s)", len(valid))
        return

    if skip_scan:
        logger.info("WoW: no valid configured path; auto-scan skipped (--skip-detection)")
        if not cfg.wow_installs and svc.wow_warn_fn is not None:
            svc.wow_warn_fn("No WoW installation found. Add path in Settings.")
        return

    logger.info("WoW: no valid configured path, running auto-detection")
    found = await svc.wow_detector.scan()
    if found:
        # Only persist auto-detected paths when config has no user-configured paths at
        # all. If the user has paths in config that are temporarily invalid (e.g. an
        # unmounted drive), do not overwrite them.
        if not cfg.wow_installs:
            cfg.wow_installs = found
            svc.config_store.save(cfg)
            logger.info("WoW: auto-detected %d install(s), saved to config", len(found))
        else:
            logger.info("WoW: auto-detected %d install(s), keeping existing config", len(found))
    else:
        logger.warning("WoW: no installs found; user should configure a path in Settings")
        if svc.wow_warn_fn is not None:
            svc.wow_warn_fn("No WoW installation found. Add path in Settings.")
