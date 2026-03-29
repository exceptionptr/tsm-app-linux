"""Tests for AddonWriterService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from tsm.core.models.auction import AuctionData
from tsm.core.services.addon_writer import AddonWriterService


async def test_write_data_no_detector():
    svc = AddonWriterService(wow_detector=None)
    data = AuctionData()
    result = await svc.write_data(data)
    assert result == []


async def test_write_data_addon_dir_missing(tmp_path):
    install = MagicMock()
    install.path = str(tmp_path)
    detector = MagicMock()
    detector.get_installs = AsyncMock(return_value=[install])
    svc = AddonWriterService(wow_detector=detector)
    data = AuctionData()
    result = await svc.write_data(data)
    assert result == []


async def test_write_data_calls_lua_writer(tmp_path):
    # New behavior: install.path is the WoW base dir; code iterates installed game versions
    addon_dir = tmp_path / "_retail_" / "Interface" / "AddOns" / "TradeSkillMaster_AppHelper"
    addon_dir.mkdir(parents=True)
    expected_path = addon_dir / "AppData.lua"

    install = MagicMock()
    install.path = str(tmp_path)
    detector = MagicMock()
    detector.get_installs = AsyncMock(return_value=[install])

    svc = AddonWriterService(wow_detector=detector)
    data = AuctionData()

    with patch.object(svc._lua_writer, "write_app_data", return_value=expected_path) as mock_write:
        result = await svc.write_data(data)

    mock_write.assert_called_once_with(data, addon_dir, gv_dir="_retail_")
    assert result == [expected_path]
