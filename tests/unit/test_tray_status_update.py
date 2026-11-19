"""AppWindow._update_tray swaps the icon only on a status change."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

import tsm.ui.app_window as mod  # noqa: E402
from tsm.ui._tray_status import TrayStatus, tray_tooltip  # noqa: E402


@pytest.fixture
def built(monkeypatch):
    calls: list[TrayStatus] = []

    def fake_icon(status, bases):
        calls.append(status)
        return f"icon-{status.value}"

    monkeypatch.setattr(mod, "tray_icon", fake_icon)
    monkeypatch.setattr(mod, "_app_icon_images", lambda: [])
    return calls


def _window(authenticated: bool, connected: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        _app_vm=SimpleNamespace(authenticated=authenticated),
        _realm_vm=SimpleNamespace(summaries=[]),
        _connected=connected,
        _tray=MagicMock(),
        _tray_status=None,
        _tray_icons={},
    )


def test_same_status_sets_icon_once_and_tooltip_every_time(built):
    w = _window(authenticated=False)
    mod.AppWindow._update_tray(w)
    mod.AppWindow._update_tray(w)
    assert w._tray.setIcon.call_count == 1
    assert w._tray.setToolTip.call_count == 2
    w._tray.setToolTip.assert_called_with(tray_tooltip(TrayStatus.LOGGED_OUT))


def test_status_change_sets_icon_again_and_reuses_cache(built):
    w = _window(authenticated=False)
    mod.AppWindow._update_tray(w)
    w._app_vm.authenticated = True  # no realm data yet: not up to date
    mod.AppWindow._update_tray(w)
    assert w._tray.setIcon.call_count == 2
    w._tray.setToolTip.assert_called_with(tray_tooltip(TrayStatus.OUT_OF_DATE))
    w._app_vm.authenticated = False
    mod.AppWindow._update_tray(w)
    assert w._tray.setIcon.call_count == 3
    assert built == [TrayStatus.LOGGED_OUT, TrayStatus.OUT_OF_DATE]
