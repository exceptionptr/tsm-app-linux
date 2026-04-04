"""Tests for tsm.wow.utils path helpers."""

from __future__ import annotations

from pathlib import Path

from tsm.wow.utils import (
    addon_dir,
    appdata_lua_path,
    apphelper_dir,
    installed_versions,
    normalize_wow_base,
    wtf_accounts_dir,
)


def test_normalize_wow_base_already_base():
    p = Path("/home/user/Games/wow")
    assert normalize_wow_base(p) == p


def test_normalize_wow_base_retail():
    p = Path("/home/user/Games/wow/_retail_")
    assert normalize_wow_base(p) == Path("/home/user/Games/wow")


def test_normalize_wow_base_classic():
    p = Path("/home/user/Games/wow/_classic_")
    assert normalize_wow_base(p) == Path("/home/user/Games/wow")


def test_normalize_wow_base_classic_era():
    p = Path("/home/user/Games/wow/_classic_era_")
    assert normalize_wow_base(p) == Path("/home/user/Games/wow")


def test_normalize_wow_base_anniversary():
    p = Path("/home/user/Games/wow/_anniversary_")
    assert normalize_wow_base(p) == Path("/home/user/Games/wow")


def test_addon_dir():
    base = Path("/home/user/Games/wow")
    assert addon_dir(base, "_retail_") == Path(
        "/home/user/Games/wow/_retail_/Interface/AddOns"
    )


def test_apphelper_dir_retail():
    base = Path("/home/user/Games/wow")
    assert apphelper_dir(base, "_retail_") == Path(
        "/home/user/Games/wow/_retail_/Interface/AddOns/TradeSkillMaster_AppHelper"
    )


def test_apphelper_dir_classic_era():
    base = Path("/home/user/Games/wow")
    assert apphelper_dir(base, "_classic_era_") == Path(
        "/home/user/Games/wow/_classic_era_/Interface/AddOns/TradeSkillMaster_AppHelper"
    )


def test_apphelper_dir_classic_progression():
    base = Path("/home/user/Games/wow")
    assert apphelper_dir(base, "_classic_") == Path(
        "/home/user/Games/wow/_classic_/Interface/AddOns/TradeSkillMaster_AppHelper"
    )


def test_apphelper_dir_anniversary():
    base = Path("/home/user/Games/wow")
    assert apphelper_dir(base, "_anniversary_") == Path(
        "/home/user/Games/wow/_anniversary_/Interface/AddOns/TradeSkillMaster_AppHelper"
    )


def test_appdata_lua_path_retail():
    base = Path("/home/user/Games/wow")
    expected = Path(
        "/home/user/Games/wow/_retail_/Interface/AddOns/TradeSkillMaster_AppHelper/AppData.lua"
    )
    assert appdata_lua_path(base, "_retail_") == expected


def test_appdata_lua_path_classic_era():
    base = Path("/home/user/Games/wow")
    expected = Path(
        "/home/user/Games/wow/_classic_era_/Interface/AddOns"
        "/TradeSkillMaster_AppHelper/AppData.lua"
    )
    assert appdata_lua_path(base, "_classic_era_") == expected


def test_wtf_accounts_dir():
    base = Path("/home/user/Games/wow")
    assert wtf_accounts_dir(base, "_retail_") == Path(
        "/home/user/Games/wow/_retail_/WTF/Account"
    )


def test_installed_versions_returns_existing(tmp_path):
    (tmp_path / "_retail_").mkdir()
    (tmp_path / "_classic_era_").mkdir()
    result = installed_versions(tmp_path)
    assert "_retail_" in result
    assert "_classic_era_" in result
    assert "_classic_" not in result


def test_installed_versions_empty_when_none(tmp_path):
    assert installed_versions(tmp_path) == []
