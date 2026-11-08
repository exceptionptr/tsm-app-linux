"""Single instance lock: one running app per data directory.

An advisory flock on a file in the data directory. It used to be a
QLocalServer, but QtNetwork links against libgssapi_krb5, which the Flatpak
runtime does not ship, so the Flatpak crashed on start (issue #26). The kernel
drops a flock when the process ends, crashes included, so there is no stale
state to clean up afterwards.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import IO


def acquire_instance_lock(path: Path) -> IO[bytes] | None:
    """Take the lock at `path`, or return None if another process holds it.

    The returned file holds the lock for as long as it stays open, so the
    caller keeps a reference for the lifetime of the process.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")  # noqa: SIM115 - must stay open to hold the lock
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None

    # The pid is only a hint for whoever looks at the file; the lock is the flock.
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()}\n".encode())
    handle.flush()
    return handle
