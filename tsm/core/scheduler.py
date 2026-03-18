"""APScheduler 4.x setup on the asyncio event loop."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from apscheduler import AsyncScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


@dataclass
class ServiceContainer:
    """Holds references to all services needed by scheduled jobs."""

    auth: object
    auction: object
    wow_detector: object
    updater: object
    backup: object = None
    config_store: object = None
    backup_notify_fn: object = None  # callable(message: str) | None
    addon_notify_fn: object = None  # callable(message: str) | None
    auction_data_fn: object = None  # callable(AuctionData) | None


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
            async with scheduler:
                if debug is not None:
                    # Debug mode: auction + backup fire immediately and repeat every debug minutes.
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
                    # Delay first run by the full interval — realm_vm.refresh_all() handles
                    # the startup auction fetch; we just authenticated so no auth refresh needed.
                    await scheduler.add_schedule(
                        job_auction_refresh,
                        IntervalTrigger(minutes=60, start_time=now + timedelta(minutes=60)),
                        id="auction_refresh",
                        kwargs={"services": svc},
                    )
                    # Delay first backup check — BackupService has its own period guard but
                    # we don't want a backup attempt on every startup.
                    await scheduler.add_schedule(
                        job_backup,
                        IntervalTrigger(minutes=15, start_time=now + timedelta(minutes=15)),
                        id="backup",
                        kwargs={"services": svc},
                    )
                await scheduler.add_schedule(
                    job_auth_refresh,
                    IntervalTrigger(minutes=25, start_time=now + timedelta(minutes=25)),
                    id="auth_refresh",
                    kwargs={"services": svc},
                )
                # Fire immediately — we want WoW install detection and config persistence ASAP.
                await scheduler.add_schedule(
                    job_wow_monitor,
                    IntervalTrigger(minutes=5),
                    id="wow_monitor",
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


from tsm.workers.jobs import (  # noqa: E402
    job_auction_refresh,
    job_auth_refresh,
    job_backup,
    job_wow_monitor,
)
