"""asyncio -> Qt signal bridge for running coroutines from Qt views."""

from __future__ import annotations

import logging
from collections.abc import Coroutine
from concurrent.futures import Future
from typing import Any

from PySide6.QtCore import QCoreApplication, QObject, Signal, Slot

from tsm.workers.async_runner import get_runner

logger = logging.getLogger(__name__)


class AsyncBridge(QObject):
    """Runs a coroutine on the async runner and emits signals with the result.

    Usage:
        bridge = AsyncBridge(parent=self)
        bridge.result_ready.connect(self._on_data)
        bridge.error_occurred.connect(self._on_error)
        bridge.run(some_service.fetch_data())
    """

    result_ready: Signal = Signal(object)
    error_occurred: Signal = Signal(str)
    finished: Signal = Signal()

    def __init__(self, parent: QObject | None = None):
        # A bridge without a parent would be owned by its Python wrapper, and the
        # last reference is dropped on the async thread: Qt then deletes a main
        # thread object from the wrong thread while the main thread may still
        # deliver its events (heap corruption). The application owns it instead,
        # and it is deleted on the main thread once its answer has been delivered.
        if parent is None:
            parent = QCoreApplication.instance()
        super().__init__(parent)
        self.finished.connect(self._release)

    def run(self, coro: Coroutine[Any, Any, Any]) -> Future[Any]:
        """Submit coroutine to async runner; emit result_ready or error_occurred when done.

        Returns the concurrent future, so a caller can cancel() a long wait.
        """
        runner = get_runner()
        future = runner.submit(coro)
        future.add_done_callback(self._on_done)
        return future

    def _on_done(self, future) -> None:
        """Called from the async thread; emit Qt signals (safe via Qt's queued connections)."""
        try:
            result = future.result()
            self.result_ready.emit(result)
        except Exception as exc:
            logger.exception("AsyncBridge caught exception")
            self.error_occurred.emit(str(exc))
        finally:
            self.finished.emit()  # last use of self on this thread

    @Slot()
    def _release(self) -> None:
        """Main thread, after result_ready/error_occurred were delivered."""
        self.deleteLater()
