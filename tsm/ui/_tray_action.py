"""What a click on the tray icon (or its "Show" entry) should do.

Kept free of PySide6 so the rules can be tested without a display stack.
"""

from __future__ import annotations

from enum import Enum


class TrayAction(Enum):
    """Outcome of a tray activation."""

    SHOW_MAIN = "show_main"
    FOCUS_LOGIN = "focus_login"
    START_LOGIN = "start_login"
    NOTHING = "nothing"


def tray_action(
    *,
    authenticated: bool,
    logging_out: bool,
    login_pending: bool,
    startup_superseded: bool,
) -> TrayAction:
    """Decide what a tray activation means.

    The main window is empty while signed out, so it is only shown when the
    user is authenticated. Otherwise the tray brings the login back: it raises
    the login window, or opens it again after it was closed. While a logout or
    the session restore at startup is running, those flows open the right
    window themselves, so the tray must not start a second login.
    """
    if authenticated:
        return TrayAction.SHOW_MAIN
    if logging_out:
        return TrayAction.NOTHING
    if login_pending:
        return TrayAction.FOCUS_LOGIN
    if not startup_superseded:
        return TrayAction.NOTHING
    return TrayAction.START_LOGIN
