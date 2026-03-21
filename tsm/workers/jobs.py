"""APScheduler job functions wired to services."""

from __future__ import annotations

import asyncio
import logging
import time

from tsm.core.models.auction import AppInfo, AuctionData

logger = logging.getLogger(__name__)


async def job_auction_refresh(*, services) -> None:
    """Poll every 5 min; only fetch from TSM API when data is older than the
    configured interval (default 60 min).  Also checks for addon updates."""
    try:
        statuses, saved_at = await services.auction.get_snapshot()
        threshold = getattr(services, "auction_interval_minutes", 60)
        age_minutes = (time.time() - saved_at) / 60 if saved_at else float("inf")
        if age_minutes < threshold:
            logger.debug(
                "job_auction_refresh: data is %.0f min old (threshold %d min), skipping API",
                age_minutes,
                threshold,
            )
            # Keep AppData.lua lastSync fresh so the addon does not show stale warnings.
            await services.auction.write_app_info()
            # Update status bar with cached realm list and current check time.
            if statuses and callable(getattr(services, "auction_data_fn", None)):
                fresh = AuctionData(
                    app_info=AppInfo(version=41402, last_sync=int(time.time())),
                    realm_statuses=list(statuses),
                )
                services.auction_data_fn(fresh)
            return
        logger.info("job_auction_refresh: data is %.0f min old, fetching from API", age_minutes)
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


async def job_backup(*, services) -> None:
    """Back up TSM SavedVariables if period has elapsed."""
    logger.info("job_backup: starting")
    try:
        cfg = services.config_store.load()
        # Ensure wow installs are populated before the sync backup code runs
        await services.wow_detector.get_installs()
        loop = asyncio.get_running_loop()
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
