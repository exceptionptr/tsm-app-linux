"""Entry point: python -m tsm"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import signal
import sys
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import structlog

_LOG_DIR = Path.home() / ".local" / "share" / "tsm-app" / "logs"
_LOG_FILE = _LOG_DIR / "tsm-app.log"


def _setup_logging(debug: bool = False) -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler: 5 backups, 1 MB each
    file_handler = logging.handlers.RotatingFileHandler(
        _LOG_FILE,
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(fmt)

    from tsm.core.log_buffer import get_log_buffer

    buf_handler = get_log_buffer()

    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(level=level, handlers=[file_handler, stderr_handler, buf_handler])

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )


STARTUP_TRIES = 3
STARTUP_RETRY_MS = 5000


def run_startup(
    startup: Callable[[], Coroutine[Any, Any, bool]],
    window: Any,
    auth_svc: Any,
    *,
    tries: int = STARTUP_TRIES,
    retry_ms: int = STARTUP_RETRY_MS,
    schedule: Callable[[int, Callable[[], None]], None] | None = None,
    superseded: Callable[[], bool] | None = None,
) -> None:
    """Restore the session and open the matching window.

    The result decides which window comes next, so a failure must not leave the app
    invisible: a transient error is retried a few times, then the login opens. The
    stored credentials stay in the keyring either way. ``superseded`` tells that a
    login or a logout has taken over meanwhile: the chain then opens nothing.
    """
    from PySide6.QtCore import QTimer

    from tsm.workers.bridge import AsyncBridge

    if schedule is None:
        schedule = QTimer.singleShot

    def _attempt(left: int) -> None:
        bridge = AsyncBridge()  # no parent; lives until callback fires

        def _on_restore(success: bool) -> None:
            if superseded is not None and superseded():
                return
            if success:
                session = auth_svc.current_session
                if session:
                    window.on_authenticated(session)
            else:
                window.show_login()

        def _on_error(message: str) -> None:
            if superseded is not None and superseded():
                return
            if left > 1:
                logging.getLogger(__name__).warning(
                    "Startup failed (%s), trying again in %.0fs", message, retry_ms / 1000
                )
                schedule(
                    retry_ms,
                    lambda: None
                    if superseded is not None and superseded()
                    else _attempt(left - 1),
                )
            else:
                logging.getLogger(__name__).warning(
                    "Startup failed (%s), opening the login", message
                )
                window.show_login()

        bridge.result_ready.connect(_on_restore)
        bridge.error_occurred.connect(_on_error)
        bridge.run(startup())

    _attempt(tries)


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print version and exit",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Check that the GUI stack loads, then exit",
    )
    parser.add_argument(
        "--skip-detection",
        action="store_true",
        help="Skip WoW install auto-detection at startup",
    )
    parser.add_argument(
        "--skip-auto-sync",
        action="store_true",
        help="Do not schedule the periodic auction data sync job",
    )
    parser.add_argument(
        "--skip-auto-backup",
        action="store_true",
        help="Do not schedule the periodic backup job",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Log at DEBUG level",
    )
    known, qt_argv = parser.parse_known_args()

    if known.version:
        from tsm import __version__

        print(__version__)
        return

    if known.self_test:
        # Deliberately ahead of everything else: it must not open the database,
        # read the keyring or take the single instance lock.
        from tsm.ui.self_test import run_self_test

        sys.exit(run_self_test())

    _setup_logging(debug=known.debug)

    from tsm.app import create_app
    qt_app, window, _, auth_svc, startup = create_app(
        [sys.argv[0]] + qt_argv,
        skip_detection=known.skip_detection,
        skip_auto_sync=known.skip_auto_sync,
        skip_auto_backup=known.skip_auto_backup,
    )
    # Do NOT show main window yet: only show it after successful auth.

    # Make Ctrl+C work: Qt blocks Python's default SIGINT handler.
    # Install a handler that calls QApplication.quit(), and use a 200ms
    # timer so the Python interpreter gets a chance to check for signals.
    # SIGTERM is how a session manager ends the app on logout, so it takes the
    # same route and gets the scheduler and database closed on the way out.
    signal.signal(signal.SIGINT, lambda *_: qt_app.quit())
    signal.signal(signal.SIGTERM, lambda *_: qt_app.quit())
    from PySide6.QtCore import QTimer

    _signal_timer = QTimer()
    _signal_timer.setInterval(200)
    _signal_timer.timeout.connect(lambda: None)  # wake event loop for Python
    _signal_timer.start()

    run_startup(startup, window, auth_svc, superseded=lambda: window.startup_superseded)

    sys.exit(qt_app.exec())


if __name__ == "__main__":
    main()
