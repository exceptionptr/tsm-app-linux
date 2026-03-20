"""Tests for BackupService."""

from __future__ import annotations

import zipfile
from datetime import datetime
from unittest.mock import patch

from tsm.core.services.backup import _SEPARATOR, _TIME_FORMAT, BackupService


def test_delete_success(tmp_path):
    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("dummy.txt", "data")
    svc = BackupService()
    result = svc.delete(zip_path)
    assert result is True
    assert not zip_path.exists()


def test_delete_missing_file(tmp_path):
    svc = BackupService()
    result = svc.delete(tmp_path / "nonexistent.zip")
    assert result is False


def test_restore_bad_filename(tmp_path):
    zip_path = tmp_path / "badname.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("dummy.txt", "data")
    svc = BackupService()
    result = svc.restore(zip_path)
    assert result is False


def test_list_backups_parses_filenames(tmp_path, monkeypatch):
    import tsm.core.services.backup as bmod

    monkeypatch.setattr(bmod, "_BACKUP_DIR", tmp_path)
    keep_dir = tmp_path / "keep"
    keep_dir.mkdir()
    monkeypatch.setattr(bmod, "_KEEP_DIR", keep_dir)

    ts_str = datetime.now().strftime(_TIME_FORMAT)
    name = f"abcd1234{_SEPARATOR}Account1{_SEPARATOR}{ts_str}.zip"
    zip_path = tmp_path / name
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("dummy.lua", "")

    svc = BackupService()
    backups = svc._list_backups()
    assert len(backups) == 1
    assert backups[0]["account"] == "Account1"
    assert backups[0]["keep"] is False
    assert backups[0]["path"] == zip_path


def test_find_sv_files(tmp_path):
    (tmp_path / "TradeSkillMaster.lua").write_text("")
    (tmp_path / "TradeSkillMaster_Accounting.lua").write_text("")
    (tmp_path / "OtherAddon.lua").write_text("")

    svc = BackupService()
    result = svc._find_sv_files(tmp_path)
    names = {p.name for p in result}
    assert "TradeSkillMaster.lua" in names
    assert "TradeSkillMaster_Accounting.lua" in names
    assert "OtherAddon.lua" not in names


def test_run_no_accounts_returns_empty():
    svc = BackupService()
    with patch.object(svc, "_find_accounts", return_value={}):
        result = svc.run(period_minutes=60, retain_days=30)
    assert result == []
