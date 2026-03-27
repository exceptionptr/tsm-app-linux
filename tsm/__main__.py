"""Entry point: python -m tsm"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import signal
import sys
from pathlib import Path

import structlog

_LOG_DIR = Path.home() / ".local" / "share" / "tsm-app" / "logs"
_LOG_FILE = _LOG_DIR / "tsm-app.log"


def _setup_logging() -> None:
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

    logging.basicConfig(level=logging.INFO, handlers=[file_handler, stderr_handler])

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


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
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
    known, qt_argv = parser.parse_known_args()

    _setup_logging()

    from tsm.app import create_app
    from tsm.workers.bridge import AsyncBridge

    qt_app, window, _, auth_svc = create_app(
        [sys.argv[0]] + qt_argv,
        skip_detection=known.skip_detection,
        skip_auto_sync=known.skip_auto_sync,
        skip_auto_backup=known.skip_auto_backup,
    )
    # Do NOT show main window yet: only show it after successful auth.

    # Make Ctrl+C work: Qt blocks Python's default SIGINT handler.
    # Install a handler that calls QApplication.quit(), and use a 200ms
    # timer so the Python interpreter gets a chance to check for signals.
    signal.signal(signal.SIGINT, lambda *_: qt_app.quit())
    from PySide6.QtCore import QTimer

    _sigint_timer = QTimer()
    _sigint_timer.setInterval(200)
    _sigint_timer.timeout.connect(lambda: None)  # wake event loop for Python
    _sigint_timer.start()

    bridge = AsyncBridge()  # no parent; lives until callback fires

    def _on_restore(success: bool) -> None:
        if success:
            session = auth_svc.current_session
            if session:
                window.on_authenticated(session)
        else:
            window.show_login()

    bridge.result_ready.connect(_on_restore)
    bridge.run(auth_svc.restore_session())

    sys.exit(qt_app.exec())


if __name__ == "__main__":
    main()
