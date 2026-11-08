"""AppData.lua reader/writer, in the official 1.0.9 format."""

from __future__ import annotations

from tsm.wow.lua_writer import AppDataFile, lua_string, render_app_info

BLOB = "{downloadTime=1,fields={},data={}}"


def test_round_trip_single_entry(tmp_path):
    path = tmp_path / "AppData.lua"
    f = AppDataFile(path)
    assert f.update("AUCTIONDB_NON_COMMODITY_DATA", "Tarren Mill", BLOB, 100, 97)
    assert f.save()
    text = path.read_text()
    assert text == (
        'select(2, ...).LoadData("AUCTIONDB_NON_COMMODITY_DATA","Tarren Mill",[[return '
        + BLOB
        + "]]) --<AUCTIONDB_NON_COMMODITY_DATA,Tarren Mill,100,97>\n"
    )
    again = AppDataFile(path)
    assert again.last_update("AUCTIONDB_NON_COMMODITY_DATA", "Tarren Mill") == 100
    assert again.entries[0].auction_house_id == 97


def test_connected_realms_share_one_line(tmp_path):
    path = tmp_path / "AppData.lua"
    f = AppDataFile(path)
    f.update("T", "A", BLOB, 5, 7)
    f.update("T", "B", BLOB, 5, 7)
    f.save()
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    assert lines[0].startswith('for _,r in ipairs({"B","A"}) do select(2, ...).LoadData("T",r,')
    assert lines[0].endswith("]]) end --<T,B|A,5,7>")
    again = AppDataFile(path)
    assert {e.key for e in again.entries} == {"A", "B"}
    assert again.last_update("T", "A") == 5


def test_legacy_three_field_lines_are_read(tmp_path):
    path = tmp_path / "AppData.lua"
    path.write_text(
        'select(2, ...).LoadData("AUCTIONDB_REGION_STAT","EU",[[return {x=1}]]) '
        "--<AUCTIONDB_REGION_STAT,EU,1700000000>\n"
    )
    f = AppDataFile(path)
    assert f.last_update("AUCTIONDB_REGION_STAT", "EU") == 1700000000
    assert f.entries[0].data == "{x=1}"


def test_older_data_is_ignored(tmp_path):
    f = AppDataFile(tmp_path / "AppData.lua")
    f.update("T", "K", "{new=1}", 200)
    assert not f.update("T", "K", "{old=1}", 100)
    assert f.entries[0].data == "{new=1}"


def test_unparseable_code_is_kept_verbatim(tmp_path):
    path = tmp_path / "AppData.lua"
    raw = "print('something else') --<X,Y,3>"
    path.write_text(raw + "\n")
    f = AppDataFile(path)
    f.update("T", "K", BLOB, 1)
    f.save()
    assert raw in path.read_text()


def test_line_without_meta_is_dropped(tmp_path):
    path = tmp_path / "AppData.lua"
    path.write_text("garbage\n")
    assert AppDataFile(path).entries == []


def test_remove_reports_what_was_there(tmp_path):
    f = AppDataFile(tmp_path / "AppData.lua")
    f.update("T", "A", BLOB, 1)
    f.update("U", "A", BLOB, 1)
    f.update("T", "B", BLOB, 1)
    assert f.remove(["A", "Z"]) == ["A"]
    assert [e.key for e in f.entries] == ["B"]


def test_save_skips_unchanged_file(tmp_path):
    path = tmp_path / "AppData.lua"
    f = AppDataFile(path)
    assert not f.save()
    assert not path.exists()


def test_lua_string_escapes_like_the_official_client():
    assert lua_string('a"b\\c]]d\n') == '"a\\034b\\092c\\093\\093d\\010"'
    assert lua_string(None) == '""'


def test_render_app_info():
    blob = render_app_info(
        "1.0.9",
        42,
        {"id": 3, "msg": "hi"},
        [{"title": "T", "content": "C", "timestamp": 9, "link": "L"}],
    )
    assert blob == (
        '{version="1.0.9",lastSync=42,message={id=3,msg="hi"},'
        'news={{title="T",content="C",timestamp=9,link="L"}}}'
    )
    assert "]]" not in render_app_info("1", 1, {"msg": "]]"}, [])
