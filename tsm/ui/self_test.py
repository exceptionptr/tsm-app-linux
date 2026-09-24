"""Check that the GUI stack actually loads.

The Flatpak, AppImage and Nix packages carry their own copy of Qt, so what is
most likely to break in them is Qt not loading at all: a missing platform
plugin, a missing system library, a PySide6 that does not match the interpreter.
Printing the version catches none of that, because it returns before PySide6 is
ever imported.

Run it with `tsm-app --self-test`. It opens no database, reads no keyring, makes
no network call and takes no single instance lock, so it is safe to run while
the app is already running. Set QT_QPA_PLATFORM=offscreen to run it without a
display, which is how CI checks each package.
"""

from __future__ import annotations

import sys


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

    print("self-test OK")
    return 0
