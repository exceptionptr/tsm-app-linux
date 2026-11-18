"""Startup: a failed session restore must never leave the app invisible."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6.QtCore")

import tsm.workers.bridge as bridge_mod  # noqa: E402
from tsm.__main__ import run_startup  # noqa: E402


class _Signal:
    def __init__(self) -> None:
        self.slots: list = []

    def connect(self, fn) -> None:
        self.slots.append(fn)

    def fire(self, *args) -> None:
        for fn in self.slots:
            fn(*args)


class _FakeBridge:
    instances: list[_FakeBridge] = []

    def __init__(self, parent=None) -> None:
        self.result_ready = _Signal()
        self.error_occurred = _Signal()
        _FakeBridge.instances.append(self)

    def run(self, coro) -> None:
        pass


@pytest.fixture
def setup(monkeypatch):
    _FakeBridge.instances.clear()
    monkeypatch.setattr(bridge_mod, "AsyncBridge", _FakeBridge)
    scheduled: list = []
    window, auth = MagicMock(), MagicMock()
    run_startup(
        lambda: "coro",
        window,
        auth,
        tries=3,
        retry_ms=10,
        schedule=lambda ms, fn: scheduled.append(fn),
    )
    return window, auth, scheduled


def test_success_opens_the_main_window(setup):
    window, auth, _ = setup
    _FakeBridge.instances[0].result_ready.fire(True)
    window.on_authenticated.assert_called_once_with(auth.current_session)
    window.show_login.assert_not_called()


def test_no_saved_login_opens_the_login(setup):
    window, _, _ = setup
    _FakeBridge.instances[0].result_ready.fire(False)
    window.show_login.assert_called_once()


def test_errors_are_retried_then_the_login_opens(setup):
    window, _, scheduled = setup
    _FakeBridge.instances[0].error_occurred.fire("offline")
    assert len(scheduled) == 1
    window.show_login.assert_not_called()
    scheduled.pop()()  # second attempt
    _FakeBridge.instances[1].error_occurred.fire("offline")
    scheduled.pop()()  # third attempt
    window.show_login.assert_not_called()
    _FakeBridge.instances[2].error_occurred.fire("offline")
    assert not scheduled
    window.show_login.assert_called_once()


def _with_superseded(monkeypatch, flag: dict):
    _FakeBridge.instances.clear()
    monkeypatch.setattr(bridge_mod, "AsyncBridge", _FakeBridge)
    scheduled: list = []
    window = MagicMock()
    run_startup(
        lambda: "coro",
        window,
        MagicMock(),
        tries=3,
        retry_ms=10,
        schedule=lambda ms, fn: scheduled.append(fn),
        superseded=lambda: flag["on"],
    )
    return window, scheduled


def test_a_superseded_startup_opens_nothing_on_a_failed_restore(monkeypatch):
    flag = {"on": False}
    window, _ = _with_superseded(monkeypatch, flag)
    flag["on"] = True  # a logout has opened its own login meanwhile
    _FakeBridge.instances[0].result_ready.fire(False)
    window.show_login.assert_not_called()
    window.on_authenticated.assert_not_called()


def test_a_superseded_startup_ignores_errors_and_stops_retrying(monkeypatch):
    flag = {"on": False}
    window, scheduled = _with_superseded(monkeypatch, flag)
    _FakeBridge.instances[0].error_occurred.fire("offline")
    assert len(scheduled) == 1
    flag["on"] = True
    scheduled.pop()()  # the retry timer fires after the logout
    assert len(_FakeBridge.instances) == 1
    window.show_login.assert_not_called()
    _FakeBridge.instances[0].error_occurred.fire("offline")
    assert not scheduled
    window.show_login.assert_not_called()
