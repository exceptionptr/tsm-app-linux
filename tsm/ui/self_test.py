"""Check that the GUI stack actually loads.

The Flatpak, AppImage and Nix packages carry their own copy of Qt, so what is
most likely to break in them is Qt not loading at all: a missing platform
plugin, a missing system library, a PySide6 that does not match the interpreter.
Printing the version catches none of that, because it returns before PySide6 is
ever imported.

A window alone is not enough either. 1.1.16 passed this test while the Flatpak
crashed on start for a library only QtNetwork needed (issue #26) and the
AppImage failed its first DNS lookup (issue #27). So the test also imports the
whole application, takes a lock in a temporary directory and resolves localhost
through the asyncio executor the HTTP client uses.

Run it with `tsm-app --self-test`. It opens no database, reads no keyring, makes
no network call outside the machine and leaves the real single instance lock
alone, so it is safe to run while the app is already running. Set
QT_QPA_PLATFORM=offscreen to run it without a display, which is how CI checks
each package.
"""

from __future__ import annotations

import asyncio
import ssl
import sys
import tempfile
import threading
from pathlib import Path


def run_self_test() -> int:
    """Build a Qt application and a window, report what loaded, and tear it down.

    Returns a process exit code. Note that Qt aborts the process itself when it
    cannot find a platform plugin, so a failure may surface as Qt's own message
    rather than a return from here. Either way the exit code is not zero.
    """
    try:
        import PySide6
        from PySide6.QtCore import qVersion
        from PySide6.QtWidgets import QApplication, QMainWindow
    except Exception as exc:  # noqa: BLE001 - any import failure is a failure
        print(f"self-test FAILED: PySide6 did not import: {exc}", file=sys.stderr)
        return 1

    print(f"python      {sys.version.split()[0]} ({sys.executable})")
    print(f"PySide6     {PySide6.__version__}")
    print(f"Qt          {qVersion()}")

    # Constructing the application is what loads the platform plugin, and
    # showing a window is what proves the plugin works rather than merely
    # loading. Both are the steps a bundle tends to fail at.
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication(sys.argv[:1])
    window = QMainWindow()
    window.setWindowTitle("TSM self-test")
    window.resize(320, 200)
    window.show()
    app.processEvents()
    visible = window.isVisible()
    window.close()

    platform = app.platformName()
    print(f"platform    {platform}")

    if not platform:
        print("self-test FAILED: no Qt platform plugin loaded", file=sys.stderr)
        return 1
    if not visible:
        print("self-test FAILED: the window did not become visible", file=sys.stderr)
        return 1

    for name, check in (
        ("app", _check_app_imports),
        ("lock", _check_instance_lock),
        ("resolve", _check_resolver),
        ("ssl", _check_ssl),
    ):
        try:
            detail = check()
        except Exception as exc:  # noqa: BLE001 - any failure here is a failure
            print(f"self-test FAILED: {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        print(f"{name:<11} {detail}")

    print("self-test OK")
    return 0


def _check_app_imports() -> str:
    """Import every module the running app loads, models included.

    Pydantic builds its schemas at import time, so a model it rejects fails
    here rather than when the first sync arrives.
    """
    import tsm.app  # noqa: F401

    return "imported"


def _check_instance_lock() -> str:
    from tsm.core.single_instance import acquire_instance_lock

    with tempfile.TemporaryDirectory() as tmp:
        lock = acquire_instance_lock(Path(tmp) / "instance.lock")
        if lock is None:
            raise RuntimeError("could not take a lock in an empty directory")
        lock.close()
    return "ok"


def _check_resolver() -> str:
    """Resolve localhost the way aiohttp does, on a loop in a worker thread.

    loop.getaddrinfo runs in the default executor, which imports
    concurrent.futures.thread on first use, and the app runs its loop on a
    thread of its own, so both are reproduced here.
    """
    result: list[object] = []

    def work() -> None:
        async def resolve() -> int:
            infos = await asyncio.get_running_loop().getaddrinfo("localhost", 443)
            return len(infos)

        try:
            result.append(asyncio.run(resolve()))
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread
            result.append(exc)

    thread = threading.Thread(target=work, name="self-test-resolver")
    thread.start()
    thread.join(timeout=30)
    if not result:
        raise TimeoutError("resolving localhost did not finish")
    outcome = result[0]
    if isinstance(outcome, BaseException):
        raise outcome
    return f"localhost ({outcome} addresses)"


def _check_ssl() -> str:
    """Build the default TLS context, which needs the CA store to load."""
    context = ssl.create_default_context()
    return f"{ssl.OPENSSL_VERSION}, {context.cert_store_stats()['x509_ca']} CAs"
