"""APScheduler job functions wired to services."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tsm.core.scheduler import ServiceContainer

logger = logging.getLogger(__name__)


async def job_auction_refresh(*, services: ServiceContainer) -> None:
    """Poll TSM API every 5 min for new auction data.

    refresh_all_realms() is differential: it calls the status endpoint,
    compares lastModified timestamps per realm/tag, and only downloads
    blobs that have changed since the last fetch.
    """
    try:
        logger.info("job_auction_refresh: checking TSM API for new data")
        data = await services.auction.refresh_all_realms()
        addon_versions = getattr(data, "addon_versions", [])
        if addon_versions:
            updated = await services.updater.check_and_update(addon_versions)
            if updated and services.addon_notify_fn is not None:
                names = ", ".join(updated)
                services.addon_notify_fn(f"TSM addon(s) updated: {names}")
        if services.auction_data_fn is not None:
            services.auction_data_fn(data)
    except Exception:
        logger.exception("job_auction_refresh: failed")


async def job_auth_refresh(*, services: ServiceContainer) -> None:
    """Refresh auth token before expiry."""
    logger.info("job_auth_refresh: starting")
    try:
        await services.auth.refresh_token()
    except Exception:
        logger.exception("job_auth_refresh: failed")


async def job_check_update(*, services: ServiceContainer) -> None:
    """One-shot at startup: check GitHub for a newer release tag."""
    try:
        from tsm import __version__
        from tsm.update_check import fetch_latest_tag, is_newer

        tag = await fetch_latest_tag()
        if tag and is_newer(tag, __version__):
            logger.info("job_check_update: newer version %s (current %s)", tag, __version__)
            if services.update_notify_fn is not None:
                services.update_notify_fn(tag)
        else:
            logger.debug("job_check_update: no update (current=%s, latest=%s)", __version__, tag)
    except Exception:
        logger.exception("job_check_update: failed")


async def job_backup(*, services: ServiceContainer) -> None:
    """Back up TSM SavedVariables if period has elapsed."""
    logger.info("job_backup: starting")
    try:
        if services.config_store is None or services.backup is None:
            return
        cfg = services.config_store.load()
        backup = services.backup
        # Ensure wow installs are populated before the sync backup code runs
        await services.wow_detector.get_installs()
        loop = asyncio.get_running_loop()
        created = await loop.run_in_executor(
            None,
            lambda: backup.run(
                cfg.backup_period_minutes,
                cfg.backup_retain_days,
            ),
        )
        if created and services.backup_notify_fn is not None:
            n = len(created)
            msg = f"Backup created ({n} account{'s' if n != 1 else ''})."
            services.backup_notify_fn(msg)
    except Exception:
        logger.exception("job_backup: failed")
