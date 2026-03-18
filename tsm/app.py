"""QApplication setup and dependency injection wiring."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from tsm.api.client import TSMApiClient
from tsm.core.scheduler import JobScheduler, ServiceContainer
from tsm.core.services.addon_writer import AddonWriterService
from tsm.core.services.auction import AuctionDataService
from tsm.core.services.auth import AuthService
from tsm.core.services.backup import BackupService
from tsm.core.services.updater import UpdateService
from tsm.core.services.wow_detector import WoWDetectorService
from tsm.storage.auction_cache import AuctionCache
from tsm.storage.config_store import ConfigStore
from tsm.storage.database import Database
from tsm.ui.app_window import AppWindow, _make_window_icon
from tsm.ui.styles.theme import load_theme
from tsm.ui.viewmodels.app_vm import AppViewModel
from tsm.ui.viewmodels.realm_vm import RealmViewModel
from tsm.ui.viewmodels.settings_vm import SettingsViewModel
from tsm.workers.async_runner import AsyncRunner

logger = logging.getLogger(__name__)

DATA_DIR = Path.home() / ".local" / "share" / "tsm-app"
DB_PATH = DATA_DIR / "data.db"


def create_app(
    argv: list[str] | None = None,
    debug_interval_minutes: int | None = None,
) -> tuple[QApplication, AppWindow, AsyncRunner, AuthService]:
    """Wire up all dependencies and return the configured application."""
    qt_app = QApplication(argv or sys.argv)
    qt_app.setApplicationName("TSM Desktop App")
    from tsm import __version__

    qt_app.setApplicationVersion(__version__)
    qt_app.setOrganizationName("tsm-app")

    load_theme(qt_app, "tsm_dark")
    qt_app.setWindowIcon(_make_window_icon())

    # AsyncRunner must start before any async work
    async_runner = AsyncRunner()
    async_runner.start()
    async_runner.wait_ready()  # block until the event loop is actually running

    # Connect DB on the async runner's loop; block until done
    db = Database(DB_PATH)
    async_runner.submit(db.connect()).result(timeout=10)

    # Storage
    cache = AuctionCache(db)
    config_store = ConfigStore()

    # API + Services
    api_client = TSMApiClient()
    auth_svc = AuthService(api_client)
    wow_detector = WoWDetectorService()
    addon_writer = AddonWriterService(wow_detector)
    auction_svc = AuctionDataService(api_client, cache, addon_writer)
    updater_svc = UpdateService(api_client, wow_detector)
    backup_svc = BackupService(wow_detector)

    # ViewModels (created before scheduler so callback can reference app_vm)
    app_vm = AppViewModel(auth_svc)
    realm_vm = RealmViewModel(auction_svc)
    settings_vm = SettingsViewModel(config_store)

    def _backup_notify(message: str) -> None:
        app_vm.backup_notification.emit(message)

    def _addon_notify(message: str) -> None:
        app_vm.addon_notification.emit(message)

    # Scheduler (started after successful auth)
    svc_container = ServiceContainer(
        auth=auth_svc,
        auction=auction_svc,
        wow_detector=wow_detector,
        updater=updater_svc,
        backup=backup_svc,
        config_store=config_store,
        backup_notify_fn=_backup_notify,
        addon_notify_fn=_addon_notify,
        auction_data_fn=app_vm.realm_data_received.emit,
    )
    scheduler = JobScheduler(svc_container, debug_interval_minutes=debug_interval_minutes)

    # Main window
    window = AppWindow(
        app_vm,
        realm_vm,
        settings_vm,
        auth_service=auth_svc,
        addon_service=wow_detector,
        api_client=api_client,
        backup_service=backup_svc,
    )

    # Start scheduler once the user is authenticated
    def _on_authenticated(is_authed: bool) -> None:
        if is_authed:
            fut = async_runner.submit(scheduler.start())
            fut.add_done_callback(
                lambda f: (
                    logger.error(
                        "Scheduler failed to start: %s", f.exception(), exc_info=f.exception()
                    )
                    if f.exception()
                    else None
                )
            )

    app_vm.authenticated_changed.connect(_on_authenticated)

    # Shutdown: stop scheduler + DB + async loop
    async def _shutdown() -> None:
        await scheduler.stop()
        await api_client.close()
        await db.close()

    qt_app.aboutToQuit.connect(lambda: async_runner.submit(_shutdown()).result(timeout=5))
    qt_app.aboutToQuit.connect(async_runner.stop)

    return qt_app, window, async_runner, auth_svc
