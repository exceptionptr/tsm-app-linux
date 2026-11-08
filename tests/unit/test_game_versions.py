from __future__ import annotations

from tsm.wow import game_versions as gvs


def test_every_folder_has_a_unique_key_and_suffix():
    assert len(set(gvs.FOLDERS)) == len(gvs.GAME_VERSIONS)
    assert len({gv.key for gv in gvs.GAME_VERSIONS}) == len(gvs.GAME_VERSIONS)
    assert len(set(gvs.SUFFIX_BY_FOLDER.values())) == len(gvs.GAME_VERSIONS)
    assert "_forever_" in gvs.FOLDERS


def test_region_keys_match_the_official_client():
    assert gvs.region_key("Retail", "eu") == "EU"
    assert gvs.region_key("Wrath", "eu") == "BCC-EU"
    assert gvs.region_key("Classic Era", "us") == "Classic-US"
    assert gvs.region_key("Classic Era - Hardcore", "eu") == "HC-EU"
    assert gvs.region_key("Season of Discovery", "eu") == "SoD-EU"
    assert gvs.region_key("Classic Era - Fresh", "eu") == "Fresh-EU"
    assert gvs.region_key("Forever", "eu") == "Forever-EU"
    assert gvs.region_key("Season of Mastery", "eu") is None


def test_region_folders():
    assert gvs.folder_for_region("Forever") == "_forever_"
    assert gvs.folder_for_region("Classic Era - Fresh") == "_anniversary_"
    assert gvs.folder_for_region("Season of Discovery") == "_classic_era_"
    assert gvs.folder_for_region("Wrath") == "_classic_"


def test_realm_key():
    assert gvs.realm_key("Tarren Mill", "ALL") == "Tarren Mill"
    assert gvs.realm_key("Everlook", "HORDE") == "Everlook-Horde"
    assert gvs.realm_key("Everlook", "Alliance") == "Everlook-Alliance"
