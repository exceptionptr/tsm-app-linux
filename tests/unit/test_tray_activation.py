"""A tray click never shows the (empty) main window while logged out."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QSystemTrayIcon  # noqa: E402

import tsm.ui.app_window as mod  # noqa: E402


def _window(
    *,
    authenticated: bool = False,
    logging_out: bool = False,
    login_pending: bool = True,
    startup_superseded: bool = True,
    focus_login: MagicMock | None = None,
) -> SimpleNamespace:
    w = SimpleNamespace(
        _app_vm=SimpleNamespace(authenticated=authenticated),
        _logging_out=logging_out,
        _login_pending=login_pending,
        _startup_superseded=startup_superseded,
        _focus_login=focus_login if focus_login is not None else MagicMock(return_value=True),
        _start_login=MagicMock(),
        show=MagicMock(),
        raise_=MagicMock(),
        activateWindow=MagicMock(),
    )
    w._show_from_tray = lambda: mod.AppWindow._show_from_tray(w)
    return w


def _activate(w: SimpleNamespace, reason=QSystemTrayIcon.ActivationReason.DoubleClick) -> None:
    mod.AppWindow._on_tray_activated(w, reason)


def test_double_click_while_logged_out_does_not_show_the_main_window():
    w = _window()
    _activate(w)
    w.show.assert_not_called()


def test_logged_out_with_login_window_open_focuses_it():
    w = _window()
    _activate(w)
    w._focus_login.assert_called_once_with()
    w._start_login.assert_not_called()


def test_logged_out_without_focus_callback_does_nothing():
    w = _window()
    w._focus_login = None
    _activate(w)
    w.show.assert_not_called()
    w._start_login.assert_not_called()


def test_double_click_after_the_login_window_was_closed_starts_a_login():
    w = _window(login_pending=False)
    _activate(w)
    w._start_login.assert_called_once_with()
    w.show.assert_not_called()


def test_login_running_but_focus_returns_false_does_nothing_else():
    w = _window(focus_login=MagicMock(return_value=False))
    _activate(w)
    w._focus_login.assert_called_once_with()
    w._start_login.assert_not_called()
    w.show.assert_not_called()


@pytest.mark.parametrize(
    "reason",
    [QSystemTrayIcon.ActivationReason.DoubleClick, QSystemTrayIcon.ActivationReason.Trigger],
)
def test_logged_in_shows_and_raises_the_main_window(reason):
    w = _window(authenticated=True, login_pending=False)
    _activate(w, reason)
    w.show.assert_called_once_with()
    w.raise_.assert_called_once_with()
    w.activateWindow.assert_called_once_with()
    w._focus_login.assert_not_called()


def test_logout_in_progress_does_nothing():
    w = _window(logging_out=True, login_pending=False)
    _activate(w)
    w.show.assert_not_called()
    w._focus_login.assert_not_called()
    w._start_login.assert_not_called()


def test_startup_restore_in_progress_does_nothing():
    w = _window(login_pending=False, startup_superseded=False)
    _activate(w)
    w.show.assert_not_called()
    w._start_login.assert_not_called()


def test_other_activation_reasons_are_ignored():
    w = _window(authenticated=True)
    _activate(w, QSystemTrayIcon.ActivationReason.Context)
    w.show.assert_not_called()
