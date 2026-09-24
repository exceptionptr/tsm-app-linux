"""Close rules for the main window, including the logout case from issue #21."""

from __future__ import annotations

from tsm.ui._window_close import CloseAction, close_action


def test_close_hides_to_tray_when_configured():
    action = close_action(
        session_ending=False, minimize_to_tray=True, confirm_on_exit=False
    )

    assert action is CloseAction.HIDE


def test_close_asks_first_when_confirmation_is_on():
    action = close_action(
        session_ending=False, minimize_to_tray=False, confirm_on_exit=True
    )

    assert action is CloseAction.CONFIRM


def test_close_quits_when_nothing_holds_the_window():
    action = close_action(
        session_ending=False, minimize_to_tray=False, confirm_on_exit=False
    )

    assert action is CloseAction.QUIT


def test_logout_beats_minimize_to_tray():
    """Hiding instead of closing is what cancelled the logout (issue #21)."""
    action = close_action(
        session_ending=True, minimize_to_tray=True, confirm_on_exit=False
    )

    assert action is CloseAction.QUIT


def test_logout_asks_no_questions():
    """A question box during logout blocks the session just as a hide does."""
    action = close_action(
        session_ending=True, minimize_to_tray=False, confirm_on_exit=True
    )

    assert action is CloseAction.QUIT


def test_logout_wins_over_every_other_setting():
    action = close_action(
        session_ending=True, minimize_to_tray=True, confirm_on_exit=True
    )

    assert action is CloseAction.QUIT
