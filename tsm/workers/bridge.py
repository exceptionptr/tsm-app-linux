"""asyncio -> Qt signal bridge for running coroutines from Qt views."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

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
        super().__init__(parent)

    def run(self, coro) -> None:
        """Submit coroutine to async runner; emit result_ready or error_occurred when done."""
        # Keep a self-reference so Python doesn't GC this bridge before the callback fires.
        self._self_ref: AsyncBridge | None = self
        runner = get_runner()
        future = runner.submit(coro)
        future.add_done_callback(self._on_done)

    def _on_done(self, future) -> None:
        """Called from the async thread; emit Qt signals (safe via Qt's queued connections)."""
        try:
            result = future.result()
            self.result_ready.emit(result)
        except Exception as exc:
            logger.exception("AsyncBridge caught exception")
            self.error_occurred.emit(str(exc))
        finally:
            self.finished.emit()
            self._self_ref = None  # release self-reference
