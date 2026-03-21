"""APScheduler 4.x setup on the asyncio event loop."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from apscheduler import AsyncScheduler
from apscheduler.triggers.interval import IntervalTrigger

from tsm.workers.jobs import job_auction_refresh, job_auth_refresh, job_backup

logger = logging.getLogger(__name__)


class AuctionServiceProtocol(Protocol):
    async def get_snapshot(self) -> tuple[Any, float]: ...
    async def refresh_all_realms(self) -> Any: ...
    async def write_app_info(self) -> None: ...


class AuthServiceProtocol(Protocol):
    async def refresh_token(self) -> None: ...


class UpdateServiceProtocol(Protocol):
    async def check_and_update(self, addon_versions: list[Any]) -> list[str]: ...


class ConfigStoreProtocol(Protocol):
    def load(self) -> Any: ...
    def save(self, config: Any) -> None: ...


class WoWDetectorProtocol(Protocol):
    async def scan(self) -> list[Any]: ...
    async def get_installs(self) -> list[Any]: ...
    def set_installs(self, installs: list[Any]) -> None: ...


class BackupServiceProtocol(Protocol):
    def run(
        self, period_minutes: int, retain_days: int, extra_installs: Any = None
    ) -> list[Any]: ...


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
    auction_data_fn: Callable[[Any], None] | None = None
    wow_warn_fn: Callable[[str], None] | None = None
    auction_interval_minutes: int = 60  # staleness threshold for the 5-min auction poller


class JobScheduler:
    def __init__(self, services: ServiceContainer, debug_interval_minutes: int | None = None):
        self._svc = services
        self._debug = debug_interval_minutes
        self._scheduler: AsyncScheduler | None = None
        self._runner_task: asyncio.Task[None] | None = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            return

        svc = self._svc
        debug = self._debug
        self._scheduler = AsyncScheduler()

        # Keep __aenter__ and __aexit__ in the same task (anyio cancel scope requirement).
        # All scheduler work runs inside _scheduler_task; stop() signals it via scheduler.stop().
        scheduler = self._scheduler

        async def _scheduler_task() -> None:
            assert scheduler is not None
            now = datetime.now(UTC)

            # Startup: resolve WoW installs from config, or auto-detect once.
            # No periodic rescanning needed; user can add paths via Settings.
            await _resolve_wow_installs(svc)

            async with scheduler:
                if debug is not None:
                    # Debug mode: bypass staleness gate and fire immediately.
                    svc.auction_interval_minutes = debug
                    await scheduler.add_schedule(
                        job_auction_refresh,
                        IntervalTrigger(minutes=debug),
                        id="auction_refresh",
                        kwargs={"services": svc},
                    )
                    await scheduler.add_schedule(
                        job_backup,
                        IntervalTrigger(minutes=debug),
                        id="backup",
                        kwargs={"services": svc},
                    )
                else:
                    # Auction poller: check every 5 minutes but only hit the API
                    # when data is older than auction_interval_minutes (default 60).
                    # First poll after 5 min; startup refresh already ran at login.
                    await scheduler.add_schedule(
                        job_auction_refresh,
                        IntervalTrigger(minutes=5, start_time=now + timedelta(minutes=5)),
                        id="auction_refresh",
                        kwargs={"services": svc},
                    )
                    # Backup: schedule at the user-configured period, not a fixed 15 min.
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
                logger.info("JobScheduler started (debug_interval=%s)", debug)
                await scheduler.run_until_stopped()

        self._runner_task = asyncio.ensure_future(_scheduler_task())
        self._started = True

    async def stop(self) -> None:
        if self._started and self._scheduler is not None:
            await self._scheduler.stop()
            if self._runner_task is not None:
                await self._runner_task
            self._started = False
            self._scheduler = None
            self._runner_task = None


async def _resolve_wow_installs(svc: ServiceContainer) -> None:
    """Check config for valid WoW paths; auto-detect if missing or invalid."""
    if svc.config_store is None:
        return
    cfg = svc.config_store.load()
    valid = [i for i in cfg.wow_installs if Path(i.path).exists()]
    if valid:
        svc.wow_detector.set_installs(valid)
        logger.info("WoW: using %d configured install(s)", len(valid))
        return

    logger.info("WoW: no valid configured path, running auto-detection")
    found = await svc.wow_detector.scan()
    if found:
        cfg.wow_installs = found
        svc.config_store.save(cfg)
        logger.info("WoW: auto-detected %d install(s)", len(found))
    else:
        logger.warning("WoW: no installs found; user should configure a path in Settings")
        if svc.wow_warn_fn is not None:
            svc.wow_warn_fn("No WoW installation found. Add path in Settings.")
