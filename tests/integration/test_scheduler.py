"""Integration tests for JobScheduler."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_scheduler_lifecycle():
    """Scheduler starts, schedules jobs, and stops cleanly."""
    from tsm.core.scheduler import JobScheduler, ServiceContainer

    config_store = MagicMock()
    config_store.load.return_value = MagicMock(
        wow_installs=[],
        backup_period_minutes=60,
    )

    services = ServiceContainer(
        auth=MagicMock(refresh_token=AsyncMock()),
        auction=MagicMock(
            refresh_all_realms=AsyncMock(return_value=MagicMock(addon_versions=[])),
            get_snapshot=AsyncMock(return_value=([], 0)),
        ),
        wow_detector=MagicMock(
            scan=AsyncMock(return_value=[]),
            set_installs=MagicMock(),
            installs=[],
        ),
        updater=MagicMock(check_and_update=AsyncMock(return_value=[])),
        config_store=config_store,
    )

    scheduler = JobScheduler(services)
    assert scheduler._started is False

    await scheduler.start()
    assert scheduler._started is True

    # Allow the background task to enter the scheduler context
    await asyncio.sleep(0.2)

    await scheduler.stop()
    assert scheduler._started is False


@pytest.mark.asyncio
async def test_scheduler_start_idempotent():
    """Calling start() twice does not create duplicate schedulers."""
    from tsm.core.scheduler import JobScheduler, ServiceContainer

    config_store = MagicMock()
    config_store.load.return_value = MagicMock(
        wow_installs=[],
        backup_period_minutes=60,
    )

    services = ServiceContainer(
        auth=MagicMock(refresh_token=AsyncMock()),
        auction=MagicMock(
            refresh_all_realms=AsyncMock(return_value=MagicMock(addon_versions=[])),
            get_snapshot=AsyncMock(return_value=([], 0)),
        ),
        wow_detector=MagicMock(
            scan=AsyncMock(return_value=[]),
            set_installs=MagicMock(),
            installs=[],
        ),
        updater=MagicMock(check_and_update=AsyncMock(return_value=[])),
        config_store=config_store,
    )

    scheduler = JobScheduler(services)
    await scheduler.start()
    runner_task = scheduler._runner_task

    await scheduler.start()  # should be no-op
    assert scheduler._runner_task is runner_task  # same task, not replaced

    await asyncio.sleep(0.1)
    await scheduler.stop()
