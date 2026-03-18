"""APScheduler job functions wired to services."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


async def job_auction_refresh(*, services) -> None:
    """Fetch region+realm auction data, update SQLite cache, write Lua files.
    Also checks and installs any outdated TSM addon files."""
    logger.info("job_auction_refresh: starting")
    try:
        data = await services.auction.refresh_all_realms()
        addon_versions = getattr(data, "addon_versions", [])
        if addon_versions:
            updated = await services.updater.check_and_update(addon_versions)
            if updated and callable(getattr(services, "addon_notify_fn", None)):
                names = ", ".join(updated)
                services.addon_notify_fn(f"TSM addon(s) updated: {names}")
        if callable(getattr(services, "auction_data_fn", None)):
            services.auction_data_fn(data)
    except Exception:
        logger.exception("job_auction_refresh: failed")


async def job_auth_refresh(*, services) -> None:
    """Refresh auth token before expiry."""
    logger.info("job_auth_refresh: starting")
    try:
        await services.auth.refresh_token()
    except Exception:
        logger.exception("job_auth_refresh: failed")


async def job_wow_monitor(*, services) -> None:
    """Scan filesystem for WoW installs, detect game running state."""
    logger.info("job_wow_monitor: starting")
    try:
        installs = await services.wow_detector.scan()
        if installs and services.config_store:
            cfg = services.config_store.load()
            if not cfg.wow_installs:
                cfg.wow_installs = installs
                services.config_store.save(cfg)
    except Exception:
        logger.exception("job_wow_monitor: failed")


async def job_backup(*, services) -> None:
    """Back up TSM SavedVariables if period has elapsed."""
    logger.info("job_backup: starting")
    try:
        cfg = services.config_store.load()
        # Ensure wow installs are populated before the sync backup code runs
        await services.wow_detector.get_installs()
        loop = asyncio.get_event_loop()
        created = await loop.run_in_executor(
            None,
            lambda: services.backup.run(
                cfg.backup_period_minutes,
                cfg.backup_retain_days,
                extra_installs=cfg.wow_installs,
            ),
        )
        if created and callable(getattr(services, "backup_notify_fn", None)):
            n = len(created)
            msg = f"Backup created ({n} account{'s' if n != 1 else ''})."
            services.backup_notify_fn(msg)
    except Exception:
        logger.exception("job_backup: failed")
