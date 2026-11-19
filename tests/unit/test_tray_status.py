"""Tray status rules: the worst dot wins, signed out beats everything."""

from __future__ import annotations

from tsm.ui._freshness import Freshness as F
from tsm.ui._tray_status import TrayStatus, tray_status, tray_tooltip


def _status(authenticated=True, connected=True, freshness=(F.GREEN,)) -> TrayStatus:
    return tray_status(authenticated=authenticated, connected=connected, freshness=freshness)


def test_logged_out_beats_everything():
    assert _status(authenticated=False, freshness=[F.RED]) is TrayStatus.LOGGED_OUT
    assert _status(authenticated=False, connected=False, freshness=[]) is TrayStatus.LOGGED_OUT


def test_red_is_outdated_even_without_connection():
    assert _status(connected=False, freshness=[F.GREEN, F.RED]) is TrayStatus.OUTDATED
    assert _status(freshness=[F.YELLOW, F.RED, F.GREEN]) is TrayStatus.OUTDATED


def test_disconnected_is_out_of_date():
    assert _status(connected=False) is TrayStatus.OUT_OF_DATE


def test_no_realm_data_is_out_of_date():
    assert _status(freshness=[]) is TrayStatus.OUT_OF_DATE


def test_yellow_is_out_of_date():
    assert _status(freshness=[F.GREEN, F.YELLOW]) is TrayStatus.OUT_OF_DATE


def test_all_green_connected_is_synced():
    assert _status(freshness=iter([F.GREEN, F.GREEN])) is TrayStatus.SYNCED


def test_every_status_has_a_tooltip_without_em_dash():
    for status in TrayStatus:
        text = tray_tooltip(status)
        assert text
        assert "\u2014" not in text
