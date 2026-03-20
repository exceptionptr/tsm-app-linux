"""Tests for ConfigStore."""

from __future__ import annotations

from tsm.core.models.config import AppConfig
from tsm.storage.config_store import ConfigStore


def test_load_defaults_when_no_file(tmp_path):
    store = ConfigStore(tmp_path / "config.toml")
    cfg = store.load()
    assert cfg.minimize_to_tray is True
    assert cfg.wow_installs == []


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
