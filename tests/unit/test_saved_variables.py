"""Tests for tsm.wow.saved_variables."""

from __future__ import annotations

from tsm.wow.saved_variables import _parse_tsm_db, read_saved_variables


def test_parse_simple_string_values():
    text = """
TradeSkillMasterDB = {
    ["r@Realm@internalData@csvSales"] = "time,item,price",
    ["r@Realm@internalData@csvBuys"] = "time,item,qty",
}
"""
    result = _parse_tsm_db(text)
    assert result["r@Realm@internalData@csvSales"] == "time,item,price"
    assert result["r@Realm@internalData@csvBuys"] == "time,item,qty"


def test_parse_numeric_values():
    text = '["someKey"] = 12345'
    result = _parse_tsm_db(text)
    assert result["someKey"] == "12345"


def test_parse_negative_numeric():
    text = '["negKey"] = -99'
    result = _parse_tsm_db(text)
    assert result["negKey"] == "-99"


def test_string_takes_priority_over_number():
    # If a key appears as both a string and a numeric match, string wins
    text = '["k"] = "hello"\n["k"] = 42'
    result = _parse_tsm_db(text)
    assert result["k"] == "hello"


def test_parse_long_string():
    text = '["longKey"] = [[multi\nline\nvalue]]'
    result = _parse_tsm_db(text)
    assert result["longKey"] == "multi\nline\nvalue"


def test_parse_escaped_quote_in_value():
    text = r'["k"] = "val\\\"ue"'
    result = _parse_tsm_db(text)
    assert "k" in result


def test_empty_text():
    result = _parse_tsm_db("")
    assert result == {}


def test_read_saved_variables_missing_file(tmp_path):
    result = read_saved_variables(tmp_path / "NoFile.lua")
    assert result == {}


def test_read_saved_variables_parses_file(tmp_path):
    lua = tmp_path / "SV.lua"
    lua.write_text('["key"] = "value"\n', encoding="utf-8")
    result = read_saved_variables(lua)
    assert result["key"] == "value"


def test_read_saved_variables_handles_encoding_error(tmp_path):
    lua = tmp_path / "SV.lua"
    lua.write_bytes(b'["k"] = "\xff\xfe"')
    result = read_saved_variables(lua)
    assert isinstance(result, dict)
