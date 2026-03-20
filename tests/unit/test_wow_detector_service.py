"""Tests for WoWDetectorService."""

from __future__ import annotations

from unittest.mock import patch

from tsm.core.models.config import WoWInstall
from tsm.core.services.wow_detector import WoWDetectorService

_FAKE_INSTALLS = [WoWInstall(path="/fake/wow", version="_retail_")]


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
    with patch("tsm.wow.detector.find_wow_installs") as mock_find:
        result = await svc.get_installs()
    assert result == _FAKE_INSTALLS
    mock_find.assert_not_called()


async def test_get_installs_scans_if_empty():
    svc = WoWDetectorService()
    with patch("tsm.core.services.wow_detector.find_wow_installs", return_value=_FAKE_INSTALLS):
        result = await svc.get_installs()
    assert result == _FAKE_INSTALLS


async def test_scan_calls_find_wow_installs():
    svc = WoWDetectorService()
    with patch(
        "tsm.core.services.wow_detector.find_wow_installs", return_value=_FAKE_INSTALLS
    ) as mock_find:
        result = await svc.scan()
    mock_find.assert_called_once()
    assert result == _FAKE_INSTALLS
    assert svc.installs == _FAKE_INSTALLS
