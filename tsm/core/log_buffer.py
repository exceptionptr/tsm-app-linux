"""In-memory log buffer for the current application session.

Installs as a standard logging.Handler so every log record emitted after
_setup_logging() is also stored in a bounded deque. The log viewer reads
from this buffer to display session logs without touching the log file.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime

_MAX_RECORDS = 2000


class LogBuffer(logging.Handler):
    """Thread-safe in-memory store of LogRecord objects."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self._records: deque[logging.LogRecord] = deque(maxlen=_MAX_RECORDS)
        self._lock = threading.Lock()
        self.start_time: datetime = datetime.now()

    def emit(self, record: logging.LogRecord) -> None:
        with self._lock:
            self._records.append(record)

    @property
    def records(self) -> list[logging.LogRecord]:
        """Snapshot of all stored records (oldest first)."""
        with self._lock:
            return list(self._records)


_buffer: LogBuffer | None = None


def get_log_buffer() -> LogBuffer:
    """Return the singleton LogBuffer, creating it if necessary."""
    global _buffer
    if _buffer is None:
        _buffer = LogBuffer()
    return _buffer
