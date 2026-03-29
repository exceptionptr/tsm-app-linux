"""Tests for ConfigStore."""

from __future__ import annotations

from tsm.core.models.config import AppConfig
from tsm.storage.config_store import ConfigStore


def test_load_defaults_when_no_file(tmp_path):
    store = ConfigStore(tmp_path / "config.toml")
    cfg = store.load()
    assert cfg.minimize_to_tray is True
    assert cfg.wow_path == ""


def test_load_parses_toml(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_bytes(b"backup_period_minutes = 120\nminimize_to_tray = false\n")
    store = ConfigStore(config_file)
    cfg = store.load()
    assert cfg.backup_period_minutes == 120
    assert cfg.minimize_to_tray is False


def test_load_returns_defaults_on_corrupt_toml(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_bytes(b"not valid toml [[[")
    store = ConfigStore(config_file)
    cfg = store.load()
    assert cfg.backup_period_minutes == 60


def test_save_creates_file(tmp_path):
    config_file = tmp_path / "config.toml"
    store = ConfigStore(config_file)
    cfg = AppConfig(backup_period_minutes=90)
    store.save(cfg)
    assert config_file.exists()
    loaded = store.load()
    assert loaded.backup_period_minutes == 90


def test_save_creates_parent_dirs(tmp_path):
    config_file = tmp_path / "a" / "b" / "config.toml"
    store = ConfigStore(config_file)
    store.save(AppConfig())
    assert config_file.exists()


def test_migrate_normalizes_retail_path_to_base(tmp_path):
    """Old configs store _retail_ subdir; migration should normalize to base dir."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '[[wow_installs]]\npath = "/home/user/Games/wow/_retail_"\nversion = "_retail_"\n'
    )
    store = ConfigStore(config_file)
    cfg = store.load()
    assert cfg.wow_path == "/home/user/Games/wow"


def test_migrate_takes_first_entry(tmp_path):
    """Migration uses the first wow_installs entry for wow_path."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '[[wow_installs]]\npath = "/home/user/Games/wow/_retail_"\n'
        '[[wow_installs]]\npath = "/home/user/Games/wow/_classic_"\n'
    )
    store = ConfigStore(config_file)
    cfg = store.load()
    assert cfg.wow_path == "/home/user/Games/wow"


def test_migrate_keeps_base_path_unchanged(tmp_path):
    """Paths already at base dir are not modified by migration."""
    config_file = tmp_path / "config.toml"
    config_file.write_text('[[wow_installs]]\npath = "/home/user/Games/wow"\n')
    store = ConfigStore(config_file)
    cfg = store.load()
    assert cfg.wow_path == "/home/user/Games/wow"


def test_new_format_wow_path(tmp_path):
    """New format uses wow_path string directly."""
    config_file = tmp_path / "config.toml"
    config_file.write_text('wow_path = "/home/user/Games/wow"\n')
    store = ConfigStore(config_file)
    cfg = store.load()
    assert cfg.wow_path == "/home/user/Games/wow"
