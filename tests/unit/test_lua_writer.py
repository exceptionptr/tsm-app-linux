"""Tests for LuaWriter: verifies the real AppData.lua LoadData() format."""

from __future__ import annotations

from tsm.core.models.auction import AppInfo, AuctionData
from tsm.wow.lua_writer import LuaWriter


def test_write_creates_appdata_lua(tmp_path):
    writer = LuaWriter()
    data = AuctionData(app_info=AppInfo(version=41402, last_sync=1710000000))
    result = writer.write_app_data(data, tmp_path)
    assert result.name == "AppData.lua"
    assert result.exists()


def test_output_contains_loaddata_calls(tmp_path):
    writer = LuaWriter()
    data = AuctionData(app_info=AppInfo(version=41402, last_sync=1710000000))
    data.add_entry(
        "AUCTIONDB_NON_COMMODITY_DATA",
        "Blackhand",
        "return {downloadTime=1710000000,fields={},data={}}",
        1710000000,
    )
    writer.write_app_data(data, tmp_path)
    content = (tmp_path / "AppData.lua").read_text()

    assert 'select(2, ...).LoadData("APP_INFO","Global"' in content
    assert 'select(2, ...).LoadData("AUCTIONDB_NON_COMMODITY_DATA","Blackhand"' in content


def test_app_info_line_format(tmp_path):
    writer = LuaWriter()
    data = AuctionData(app_info=AppInfo(version=41402, last_sync=1710000000))
    writer.write_app_data(data, tmp_path)
    content = (tmp_path / "AppData.lua").read_text()
    # Must use long-bracket syntax [[...]]
    assert "[[" in content
    assert "]]" in content
    assert "version=41402" in content
    assert "lastSync=1710000000" in content


def test_data_blob_written_verbatim(tmp_path):
    writer = LuaWriter()
    data = AuctionData(app_info=AppInfo(version=41402, last_sync=1710000000))
    blob = "return {downloadTime=1710000000,fields={},data={{25,1CMGBEK}}}"
    data.add_entry("AUCTIONDB_NON_COMMODITY_DATA", "Blackhand", blob, 1710000000)
    writer.write_app_data(data, tmp_path)
    content = (tmp_path / "AppData.lua").read_text()
    assert blob in content


def test_atomic_write_replaces_existing(tmp_path):
    writer = LuaWriter()
    data1 = AuctionData(app_info=AppInfo(version=41402, last_sync=1000))
    data2 = AuctionData(app_info=AppInfo(version=41402, last_sync=2000))
    writer.write_app_data(data1, tmp_path)
    writer.write_app_data(data2, tmp_path)
    content = (tmp_path / "AppData.lua").read_text()
    assert "lastSync=2000" in content
    assert "lastSync=1000" not in content


def test_multiple_realms(tmp_path):
    writer = LuaWriter()
    data = AuctionData(app_info=AppInfo(version=41402, last_sync=1710000000))
    for realm in ["Blackhand", "Blackmoore", "Magtheridon", "Tarren Mill"]:
        data.add_entry(
            "AUCTIONDB_NON_COMMODITY_DATA",
            realm,
            "return {downloadTime=1710000000}",
            1710000000,
        )
    writer.write_app_data(data, tmp_path)
    content = (tmp_path / "AppData.lua").read_text()
    for realm in ["Blackhand", "Blackmoore", "Magtheridon", "Tarren Mill"]:
        assert f'"{realm}"' in content
