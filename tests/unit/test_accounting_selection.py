"""Accounting selection: remembered across data updates and restarts (issue #25)."""

from __future__ import annotations

from tsm.ui.views._accounting_selection import (
    Selection,
    load_selection,
    pick_index,
    save_selection,
)


def test_pick_index_finds_the_wanted_entry():
    assert pick_index(["Aerie Peak", "Soulseeker"], "Soulseeker") == 1


def test_pick_index_falls_back_to_first_entry():
    assert pick_index(["Aerie Peak", "Soulseeker"], "Gone") == 0
    assert pick_index(["Aerie Peak"], "") == 0


def test_pick_index_of_empty_list():
    assert pick_index([], "Soulseeker") == -1


def test_round_trip(tmp_path):
    path = tmp_path / "accounting_selection.json"
    wanted = Selection(account="ACCOUNT1 (classic)", realm="Soulseeker", character="Max")
    save_selection(path, wanted)
    assert load_selection(path) == wanted


def test_missing_file_gives_empty_selection(tmp_path):
    assert load_selection(tmp_path / "missing.json") == Selection()


def test_unreadable_file_gives_empty_selection(tmp_path):
    path = tmp_path / "accounting_selection.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_selection(path) == Selection()


def test_wrong_types_are_ignored(tmp_path):
    path = tmp_path / "accounting_selection.json"
    path.write_text('{"account": 3, "realm": "Soulseeker", "character": null}', encoding="utf-8")
    assert load_selection(path) == Selection(realm="Soulseeker")


def test_save_creates_the_directory(tmp_path):
    path = tmp_path / "config" / "accounting_selection.json"
    save_selection(path, Selection(account="A"))
    assert load_selection(path).account == "A"
