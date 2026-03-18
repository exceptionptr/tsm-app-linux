"""Entry point: python -m tsm"""

from __future__ import annotations

import logging
import signal
import sys

import structlog


def _setup_logging() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--debug",
        type=int,
        metavar="MINUTES",
        default=None,
        help="Run auction and backup jobs every MINUTES instead of normal intervals",
    )
    known, qt_argv = parser.parse_known_args()
    debug_minutes: int | None = known.debug

    _setup_logging()
    if debug_minutes is not None:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("tsm").setLevel(logging.DEBUG)
        logging.warning(
            "DEBUG mode: auction + backup interval = %d min (fires immediately)", debug_minutes
        )

    from tsm.app import create_app
    from tsm.workers.bridge import AsyncBridge

    qt_app, window, _async_runner, auth_svc = create_app(
        [sys.argv[0]] + qt_argv, debug_interval_minutes=debug_minutes
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
                window._app_vm.on_login_success(session)
                window._app_vm.set_status("Connected, loading data...")
                if not window._settings_vm.config.start_minimized:
                    window.show()
                window._realm_vm.load_snapshot()
                window._realm_vm.refresh_all()
        else:
            window.show_login()

    bridge.result_ready.connect(_on_restore)
    bridge.run(auth_svc.restore_session())

    sys.exit(qt_app.exec())


if __name__ == "__main__":
    main()
