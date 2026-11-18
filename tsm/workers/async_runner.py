"""QThread that hosts the asyncio event loop."""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import Future

from PySide6.QtCore import QThread

logger = logging.getLogger(__name__)

_runner: AsyncRunner | None = None


def get_runner() -> AsyncRunner:
    global _runner
    if _runner is None:
        raise RuntimeError("AsyncRunner not initialized")
    return _runner


class AsyncRunner(QThread):
    """Hosts the asyncio event loop in a dedicated QThread.

    All async services run on this thread's event loop.
    Use submit() to schedule coroutines from the Qt main thread.

    Call wait_ready() after start() to block until the loop is running.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        global _runner
        _runner = self

    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        # Signal that the loop is ready before entering run_forever
        self._loop.call_soon(self._ready.set)
        logger.info("AsyncRunner event loop started")
        try:
            self._loop.run_forever()
        finally:
            self._drain_loop(self._loop)
            self._loop.close()
            logger.info("AsyncRunner event loop stopped")

    @staticmethod
    def _drain_loop(loop: asyncio.AbstractEventLoop) -> None:
        """Cancel what is still running and close async generators before the loop closes.

        Without it a coroutine in flight (a connect, a login) is destroyed pending and
        its cleanup runs against a closed loop ("Event loop is closed").
        """
        pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.run_until_complete(loop.shutdown_asyncgens())

    def wait_ready(self, timeout: float = 5.0) -> None:
        """Block until the event loop is running. Raises RuntimeError on timeout."""
        if not self._ready.wait(timeout):
            raise RuntimeError("AsyncRunner event loop did not start in time")

    def stop(self) -> None:
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self.wait()

    def submit(self, coro) -> Future[object]:
        """Schedule a coroutine on the async loop from any thread."""
        if self._loop is None or not self._loop.is_running():
            raise RuntimeError("AsyncRunner event loop is not running")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)
