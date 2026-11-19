"""Closing the login window leaves the app in the tray: no page, no window, no quit."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

import tsm.ui.app_window as mod  # noqa: E402
from tsm.ui.views.login import login_was_closed  # noqa: E402


def _window(authenticated: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        _login_pending=True,
        _auth_service=MagicMock(),
        _app_vm=SimpleNamespace(authenticated=authenticated),
        _tray=MagicMock(),
        _start_login=MagicMock(),
        show=MagicMock(),
    )


@pytest.fixture
def app(monkeypatch):
    app = MagicMock()
    monkeypatch.setattr(mod.QApplication, "instance", MagicMock(return_value=app))
    monkeypatch.setattr(mod.QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    return app


@pytest.mark.parametrize(
    "raw", ["The login window was closed", "The application is shutting down"]
)
def test_closing_the_login_window_opens_nothing_and_does_not_quit(app, raw):
    w = _window()

    mod.AppWindow._on_login_error(w, raw)

    app.quit.assert_not_called()
    w.show.assert_not_called()
    w._tray.showMessage.assert_not_called()
    assert w._login_pending is False


def test_closing_without_a_system_tray_quits_like_before(app, monkeypatch):
    monkeypatch.setattr(mod.QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    w = _window()

    mod.AppWindow._on_login_error(w, "The login window was closed")

    app.quit.assert_called_once_with()


def test_other_errors_show_a_tray_message_and_no_window(app):
    w = _window()

    mod.AppWindow._on_login_error(w, "503 Service Unavailable")

    w._tray.showMessage.assert_called_once()
    assert "TSM server error (503)" in w._tray.showMessage.call_args.args[1]
    app.quit.assert_not_called()
    w.show.assert_not_called()
    assert w._login_pending is False


def test_error_without_a_system_tray_quits_when_signed_out(app, monkeypatch):
    monkeypatch.setattr(mod.QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    w = _window()

    mod.AppWindow._on_login_error(w, "503 Service Unavailable")

    w._tray.showMessage.assert_called_once()
    app.quit.assert_called_once_with()


def test_error_without_a_system_tray_keeps_a_signed_in_app(app, monkeypatch):
    monkeypatch.setattr(mod.QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    w = _window(authenticated=True)

    mod.AppWindow._on_login_error(w, "503 Service Unavailable")

    app.quit.assert_not_called()


def test_missing_auth_service_without_a_system_tray_quits(app, monkeypatch):
    monkeypatch.setattr(mod.QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    w = _window()
    w._auth_service = None

    mod.AppWindow._start_login(w)

    app.quit.assert_called_once_with()


def test_missing_auth_service_is_a_tray_message(app):
    w = _window()
    w._auth_service = None
    w._startup_superseded = False

    mod.AppWindow._start_login(w)

    w._tray.showMessage.assert_called_once()
    assert w._startup_superseded is True


def test_migration_info_is_shown_once(monkeypatch):
    monkeypatch.setattr(mod, "AsyncBridge", lambda parent=None: MagicMock())
    w = _window()
    w._login_pending = False
    w._migration_info_shown = False
    w._on_login_result = MagicMock()
    w._on_login_error = MagicMock()
    w._auth_service.migrated_from_password = True

    mod.AppWindow._start_login(w)
    w._login_pending = False
    mod.AppWindow._start_login(w)

    w._tray.showMessage.assert_called_once()


def test_login_was_closed_detects_close_and_shutdown_but_not_errors():
    assert login_was_closed("The login window was closed")
    assert login_was_closed("The application is shutting down")
    assert not login_was_closed("503 Service Unavailable")
    assert not login_was_closed("Login timed out")
