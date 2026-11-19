"""AppWindow starts at most one login at a time and supersedes the startup chain."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

import tsm.ui.app_window as mod  # noqa: E402


class _Bridge:
    created: list[_Bridge] = []

    def __init__(self, parent=None) -> None:
        self.result_ready = MagicMock()
        self.error_occurred = MagicMock()
        self.run = MagicMock()
        _Bridge.created.append(self)


def _fake_window() -> SimpleNamespace:
    auth = MagicMock()
    auth.migrated_from_password = False
    return SimpleNamespace(
        _auth_service=auth,
        _login_pending=False,
        _startup_superseded=False,
        _migration_info_shown=False,
        _tray=MagicMock(),
        _app_vm=SimpleNamespace(authenticated=False),
        _on_login_result=MagicMock(),
        _on_login_error=MagicMock(),
    )


@pytest.fixture(autouse=True)
def _bridge(monkeypatch):
    _Bridge.created.clear()
    monkeypatch.setattr(mod, "AsyncBridge", _Bridge)
    monkeypatch.setattr(mod.QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)


def test_a_second_start_while_a_login_is_pending_is_a_no_op():
    w = _fake_window()
    mod.AppWindow._start_login(w)
    mod.AppWindow._start_login(w)
    assert len(_Bridge.created) == 1
    assert w._startup_superseded is True


def test_a_new_login_may_start_once_the_answer_arrived():
    w = _fake_window()
    mod.AppWindow._start_login(w)
    mod.AppWindow._on_login_error(w, "The login window was closed")
    mod.AppWindow._start_login(w)
    assert len(_Bridge.created) == 2


def test_the_real_handlers_clear_the_pending_flag(monkeypatch):
    w = _fake_window()
    w._login_pending = True
    mod.AppWindow._on_login_error(w, "boom")
    assert w._login_pending is False
    w._login_pending = True
    w._on_login_success = MagicMock()
    w._app_vm = MagicMock()
    mod.AppWindow._on_login_result(w, SimpleNamespace(remember_failed=False))
    assert w._login_pending is False


def test_logout_cancels_the_restore_and_supersedes_the_startup():
    w = _fake_window()
    w._logging_out = False
    w._app_vm = MagicMock()
    w.hide = MagicMock()
    mod.AppWindow._on_logout_started(w)
    w._auth_service.cancel_restore.assert_called_once()
    assert w._startup_superseded is True
