"""Tray activation rules: the main window is never shown while signed out."""

from __future__ import annotations

from tsm.ui._tray_action import TrayAction, tray_action


def _action(**overrides: bool) -> TrayAction:
    state = {
        "authenticated": False,
        "logging_out": False,
        "login_pending": False,
        "startup_superseded": True,
    }
    state.update(overrides)
    return tray_action(**state)


def test_authenticated_shows_main():
    assert _action(authenticated=True) is TrayAction.SHOW_MAIN


def test_authenticated_shows_main_even_with_login_open():
    action = _action(authenticated=True, login_pending=True)

    assert action is TrayAction.SHOW_MAIN


def test_logout_beats_everything_but_authenticated():
    action = _action(logging_out=True, login_pending=True)

    assert action is TrayAction.NOTHING


def test_pending_login_focuses_login_window():
    assert _action(login_pending=True) is TrayAction.FOCUS_LOGIN


def test_pending_login_with_restore_done_focuses_login_window():
    action = _action(login_pending=True, startup_superseded=False)

    assert action is TrayAction.FOCUS_LOGIN


def test_session_restore_running_does_nothing():
    assert _action(startup_superseded=False) is TrayAction.NOTHING


def test_idle_signed_out_starts_login():
    assert _action() is TrayAction.START_LOGIN
