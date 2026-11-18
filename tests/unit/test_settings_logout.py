"""Logout from the settings dialog: the login starts only after the logout has finished."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6.QtWidgets")

import tsm.workers.bridge as bridge_mod  # noqa: E402
from tsm.ui.views.settings import SettingsDialog  # noqa: E402


class _Signal:
    def __init__(self) -> None:
        self.slots: list = []

    def connect(self, fn) -> None:
        self.slots.append(fn)

    def fire(self) -> None:
        for fn in self.slots:
            fn()


class _FakeBridge:
    instances: list[_FakeBridge] = []

    def __init__(self, parent=None) -> None:
        self.finished = _Signal()
        self.coro = None
        _FakeBridge.instances.append(self)

    def run(self, coro) -> None:
        self.coro = coro


def _dialog(auth) -> SimpleNamespace:
    return SimpleNamespace(
        _vm=MagicMock(),
        _auth_service=auth,
        reject=MagicMock(),
        logged_out=MagicMock(),
        logout_started=MagicMock(),
    )


def test_logged_out_is_emitted_only_after_the_logout_finished(monkeypatch):
    _FakeBridge.instances.clear()
    monkeypatch.setattr(bridge_mod, "AsyncBridge", _FakeBridge)
    auth = MagicMock()
    auth.logout = MagicMock(return_value="logout-coro")
    dlg = _dialog(auth)

    SettingsDialog._logout_reset(dlg)  # type: ignore[arg-type]

    dlg._vm.reset_to_defaults.assert_called_once()
    dlg.reject.assert_called_once()
    dlg.logout_started.emit.assert_called_once()  # hidden before the logout runs
    (bridge,) = _FakeBridge.instances
    assert bridge.coro == "logout-coro"
    dlg.logged_out.assert_not_called()  # the login must not open yet
    dlg.logged_out.emit.assert_not_called()
    bridge.finished.fire()  # the signal is chained to logged_out
    dlg.logged_out.assert_called_once()


def test_logged_out_is_emitted_at_once_without_an_auth_service():
    dlg = _dialog(None)
    SettingsDialog._logout_reset(dlg)  # type: ignore[arg-type]
    dlg.reject.assert_called_once()
    dlg.logout_started.emit.assert_called_once()
    dlg.logged_out.emit.assert_called_once()


def test_main_window_hides_at_once_and_a_second_logout_is_ignored():
    from tsm.ui.app_window import AppWindow

    win = SimpleNamespace(
        _logging_out=False,
        _auth_service=MagicMock(),
        _startup_superseded=False,
        _app_vm=MagicMock(),
        hide=MagicMock(),
        show_login=MagicMock(),
    )
    AppWindow._on_logout_started(win)  # type: ignore[arg-type]
    AppWindow._on_logout_started(win)  # type: ignore[arg-type]
    win._app_vm.on_logout.assert_called_once()
    win.hide.assert_called_once()
    win.show_login.assert_not_called()
    AppWindow._on_logged_out(win)  # type: ignore[arg-type]
    AppWindow._on_logged_out(win)  # type: ignore[arg-type]
    win.show_login.assert_called_once()
