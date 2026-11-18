"""QApplication setup and dependency injection wiring."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import IO, Any

from PySide6.QtWidgets import QApplication

from tsm.api.app_version import AppVersion
from tsm.api.client import TSMApiClient
from tsm.core.scheduler import JobScheduler, ServiceContainer
from tsm.core.services.auction import AuctionDataService
from tsm.core.services.auth import AuthService
from tsm.core.services.backup import BackupService
from tsm.core.services.group_sends import GroupSendsService
from tsm.core.services.sync import SyncController
from tsm.core.services.updater import UpdateService
from tsm.core.services.wow_detector import WoWDetectorService
from tsm.core.single_instance import acquire_instance_lock
from tsm.storage.auction_cache import AuctionCache
from tsm.storage.config_store import ConfigStore
from tsm.storage.database import Database
from tsm.ui.app_window import AppWindow, _make_window_icon
from tsm.ui.login_window import ChromiumLogin, log_engine_versions
from tsm.ui.styles.theme import load_theme
from tsm.ui.viewmodels.app_vm import AppViewModel
from tsm.ui.viewmodels.realm_vm import RealmViewModel
from tsm.ui.viewmodels.settings_vm import SettingsViewModel
from tsm.workers.async_runner import AsyncRunner

logger = logging.getLogger(__name__)

DATA_DIR = Path.home() / ".local" / "share" / "tsm-app"


# Held open for the lifetime of the process; closing it releases the lock.
_instance_lock: IO[bytes] | None = None


def _ensure_single_instance() -> None:
    """Exit with a message if another instance is already running."""
    global _instance_lock
    from PySide6.QtWidgets import QMessageBox

    _instance_lock = acquire_instance_lock(DATA_DIR / "instance.lock")
    if _instance_lock is not None:
        return  # We are the first instance

    QMessageBox.information(
        None,
        "TSM Already Running",
        "TSM Desktop App is already running.\nCheck the system tray.",
    )
    sys.exit(0)


DB_PATH = DATA_DIR / "data.db"


def create_app(
    argv: list[str] | None = None,
    skip_detection: bool = False,
    skip_auto_sync: bool = False,
    skip_auto_backup: bool = False,
) -> tuple[
    QApplication, AppWindow, AsyncRunner, AuthService, Callable[[], Coroutine[Any, Any, bool]]
]:
    """Wire up all dependencies and return the configured application."""
    qt_app = QApplication(argv or sys.argv)
    qt_app.setApplicationName("TSM Desktop App")
    from tsm import __version__

    qt_app.setApplicationVersion(__version__)
    qt_app.setOrganizationName("tsm-app")
    # The app lives in the tray and the login window is the only window while
    # signing in: closing it must not end the program (it did, and took the
    # token request in flight with it). Quitting is explicit (AppWindow, login page).
    qt_app.setQuitOnLastWindowClosed(False)
    # Names the app to the desktop: without it Qt falls back to the interpreter,
    # so the window carries no usable identity and KDE had nothing to put in
    # "Logout cancelled by ''" (issue #21). Matches packaging/tsm-app.desktop.
    qt_app.setDesktopFileName("tsm-app")

    load_theme(qt_app, "tsm_dark")
    qt_app.setWindowIcon(_make_window_icon())

    _ensure_single_instance()

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
    app_version = AppVersion(DATA_DIR / ".updaterId")
    log_engine_versions()
    chromium_login = ChromiumLogin(DATA_DIR, app_version.chromium_user_agent)
    auth_svc = AuthService(
        api_client,
        login_flow=chromium_login.run,
        user_agent=app_version.chromium_user_agent,
        logout_flow=chromium_login.logout,
    )
    wow_detector = WoWDetectorService(skip_scan=skip_detection)
    # APP_INFO.version is the desktop app version the addon shows; report the
    # official client's, which is the protocol this app speaks.
    auction_svc = AuctionDataService(
        api_client, cache, wow_detector, app_version=lambda: app_version.version
    )
    updater_svc = UpdateService(api_client, wow_detector)
    backup_svc = BackupService(wow_detector)

    # ViewModels (created before scheduler so callback can reference app_vm)
    app_vm = AppViewModel(auth_svc)
    realm_vm = RealmViewModel(auction_svc, auth_svc)
    settings_vm = SettingsViewModel(config_store)

    def _backup_notify(message: str) -> None:
        app_vm.backup_notification.emit(message)

    def _addon_notify(message: str) -> None:
        app_vm.addon_notification.emit(message)

    def _wow_warn(message: str) -> None:
        app_vm.set_status(message)

    auction_svc.add_listener(app_vm.realm_data_received.emit)
    group_sends = GroupSendsService(
        api_client,
        auction_svc,
        DATA_DIR / "group_sends.json",
        notify_fn=app_vm.group_send_notification.emit,
        is_connected=lambda: sync.connected,
    )
    auction_svc.on_app_info_tick = group_sends.refresh
    auth_svc.add_session_lost_listener(app_vm.session_lost.emit)
    sync = SyncController(
        auth_svc,
        auction_svc,
        updater=updater_svc,
        api_client=api_client,
        addon_notify_fn=_addon_notify,
        connection_fn=app_vm.connection_changed.emit,
        app_version=app_version,
        group_sends=group_sends,
    )

    # Scheduler (started after successful auth)
    svc_container = ServiceContainer(
        auth=auth_svc,
        auction=auction_svc,
        wow_detector=wow_detector,
        updater=updater_svc,
        backup=backup_svc,
        sync=sync,
        config_store=config_store,
        backup_notify_fn=_backup_notify,
        addon_notify_fn=_addon_notify,
        wow_warn_fn=_wow_warn,
        update_notify_fn=app_vm.update_available.emit,
    )
    scheduler = JobScheduler(
        svc_container,
        skip_detection=skip_detection,
        skip_auto_sync=skip_auto_sync,
        skip_auto_backup=skip_auto_backup,
    )

    # Main window
    window = AppWindow(
        app_vm,
        realm_vm,
        settings_vm,
        auth_service=auth_svc,
        addon_service=wow_detector,
        api_client=api_client,
        backup_service=backup_svc,
        updater_service=updater_svc,
        auction_service=auction_svc,
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
        else:
            # Logout or a rejected refresh token: drop the socket and timers.
            async_runner.submit(scheduler.stop())

    app_vm.authenticated_changed.connect(_on_authenticated)

    # Shutdown: stop scheduler + DB + async loop
    async def _shutdown() -> None:
        await scheduler.stop()
        await api_client.close()
        await db.close()

    qt_app.aboutToQuit.connect(lambda: async_runner.submit(_shutdown()).result(timeout=5))
    qt_app.aboutToQuit.connect(chromium_login.shutdown)
    qt_app.aboutToQuit.connect(async_runner.stop)

    # Logging out is announced as commitDataRequest. Take it as notice to stop
    # guarding the window, but do not quit here: the session manager decides
    # when clients die, and quitting early loses the rest of its handshake.
    # saveStateRequest is deliberately left alone. It also fires on an ordinary
    # session save, which is not a logout.
    qt_app.commitDataRequest.connect(lambda _manager: window.begin_session_end())

    async def _startup() -> bool:
        """Ask the version feed (bounded by its own timeout), then restore the session."""
        try:
            await app_version.check(await api_client.session())
        except Exception:
            logger.exception("Startup version check failed")
        logger.info(
            "App version %s (%s)",
            app_version.version,
            "update feed" if app_version.from_feed else "built-in fallback",
        )
        return await auth_svc.restore_session()

    return qt_app, window, async_runner, auth_svc, _startup
