"""Integration tests for JobScheduler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_scheduler_starts():
    from tsm.core.scheduler import JobScheduler

    mock_services = MagicMock()
    mock_services.auction.refresh_all_realms = AsyncMock()
    mock_services.auth.refresh_token = AsyncMock()
    mock_services.wow_detector.scan = AsyncMock()
    mock_services.updater.check_and_update = AsyncMock()

    scheduler = JobScheduler(mock_services)
    # Just test it doesn't raise during construction
    assert scheduler is not None
