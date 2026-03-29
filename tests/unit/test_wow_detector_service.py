"""Tests for WoWDetectorService."""

from __future__ import annotations

from unittest.mock import patch

from tsm.core.models.config import WoWInstall
from tsm.core.services.wow_detector import WoWDetectorService

_FAKE_BASE = "/fake/wow"
_FAKE_INSTALLS = [WoWInstall(path=_FAKE_BASE)]


def test_installs_empty_initially():
    svc = WoWDetectorService()
    assert svc.installs == []


def test_set_installs():
    svc = WoWDetectorService()
    svc.set_installs(_FAKE_INSTALLS)
    assert svc.installs == _FAKE_INSTALLS


async def test_get_installs_returns_cached():
    svc = WoWDetectorService()
    svc.set_installs(_FAKE_INSTALLS)
    with patch("tsm.wow.detector.find_wow_base") as mock_find:
        result = await svc.get_installs()
    assert result == _FAKE_INSTALLS
    mock_find.assert_not_called()


async def test_get_installs_scans_if_empty():
    svc = WoWDetectorService()
    with patch("tsm.core.services.wow_detector.find_wow_base", return_value=_FAKE_BASE):
        result = await svc.get_installs()
    assert result == _FAKE_INSTALLS


async def test_scan_calls_find_wow_base():
    svc = WoWDetectorService()
    with patch(
        "tsm.core.services.wow_detector.find_wow_base", return_value=_FAKE_BASE
    ) as mock_find:
        result = await svc.scan()
    mock_find.assert_called_once()
    assert result == _FAKE_INSTALLS
    assert svc.installs == _FAKE_INSTALLS


async def test_scan_does_not_overwrite_config_installs():
    """scan() must not overwrite installs loaded from config via set_installs().

    Race condition: _resolve_wow_installs() may call set_installs() while a
    concurrent scan() is running in the thread-pool executor. When scan()
    finds nothing (e.g. WoW.exe absent from _retail_ on some Wine setups),
    the config-loaded paths must not be replaced with an empty list.
    """
    svc = WoWDetectorService()
    config_installs = [WoWInstall(path="/configured/wow")]

    svc.set_installs(config_installs)
    # Simulate scan that finds nothing (WoW.exe not found by auto-detection)
    with patch("tsm.core.services.wow_detector.find_wow_base", return_value=None):
        result = await svc.scan()

    assert result == []  # scan returns its own findings
    assert svc.installs == config_installs  # but _installs keeps config-loaded list


async def test_scan_updates_installs_when_no_config():
    """scan() updates _installs normally when set_installs() was never called."""
    svc = WoWDetectorService()
    with patch("tsm.core.services.wow_detector.find_wow_base", return_value=_FAKE_BASE):
        result = await svc.scan()
    assert result == _FAKE_INSTALLS
    assert svc.installs == _FAKE_INSTALLS
