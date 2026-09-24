"""What a close request on the main window should do.

Kept free of PySide6 so the rules can be tested without a display stack.
"""

from __future__ import annotations

from enum import Enum


class CloseAction(Enum):
    """Outcome of a close request on the main window."""

    QUIT = "quit"
    HIDE = "hide"
    CONFIRM = "confirm"


def close_action(
    *,
    session_ending: bool,
    minimize_to_tray: bool,
    confirm_on_exit: bool,
) -> CloseAction:
    """Decide what a close request means.

    A request that arrives while the desktop session is ending has to be
    obeyed. Hiding to the tray or putting a question box on screen counts as
    refusing it, and a client that refuses cancels the logout for the whole
    session, which is what issue #21 reported on KDE Plasma.
    """
    if session_ending:
        return CloseAction.QUIT
    if minimize_to_tray:
        return CloseAction.HIDE
    if confirm_on_exit:
        return CloseAction.CONFIRM
    return CloseAction.QUIT
