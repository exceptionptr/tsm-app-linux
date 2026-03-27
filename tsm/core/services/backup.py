"""BackupService: matches original TSM backup logic from WoWHelper.pyc.

Original behaviour (from decompiled WoWHelper.py):
- Backs up ALL TradeSkillMaster*.lua SavedVariables per account
- Uses ZIP_LZMA compression
- Filename: {system_id}_{account}_{timestamp}.zip  (BACKUP_TIME_FORMAT = "%Y%m%d%H%M%S")
  Named:    {system_id}_{account}_{timestamp}_{safe_name}.zip
- Per account:
    1. Purge backups older than retain period
    2. Collect modified times of all TSM SV files
    3. Skip if no SV files exist
    4. Skip if max(sv_mtime) < last_backup_time (no change since last backup)
    5. Skip if now - last_backup < period (period not yet elapsed)
    6. Replace previous non-keep backup (delete it before creating new one)
    7. Create new zip
- Restore: extract all files to WTF/Account/{account}/SavedVariables/
"""

from __future__ import annotations

import hashlib
import logging
import re
import socket
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from tsm.wow.utils import iter_wow_gv_roots

logger = logging.getLogger(__name__)

_BACKUP_DIR = Path.home() / ".local" / "share" / "tsm-app" / "backups"
_KEEP_DIR = _BACKUP_DIR / "keep"
_TIME_FORMAT = "%Y%m%d%H%M%S"
_SEPARATOR = "_"
_TSM_ADDON_PREFIX = "TradeSkillMaster"
_SUFFIX_BY_GV = {
    "_retail_": "",
    "_classic_era_": "-Classic",
    "_classic_": "-Progression",
    "_anniversary_": "-Anniversary",
}


def _system_id() -> str:
    raw = socket.gethostname().encode()
    return hashlib.md5(raw).hexdigest()[:8]


class BackupService:
    def __init__(self, wow_detector=None):
        self._detector = wow_detector

    def run(
        self,
        period_minutes: int,
        retain_days: int,
        extra_installs=None,
        keep: bool = False,
        name: str = "",
    ) -> list[Path]:
        """Create backups per account. Returns list of newly created paths.

        keep=True saves to the keep/ subfolder and skips replacing the previous backup.
        """
        _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        _KEEP_DIR.mkdir(parents=True, exist_ok=True)
        created: list[Path] = []
        sys_id = _system_id()

        accounts = self._find_accounts(extra_installs=extra_installs)
        if not accounts:
            logger.info("BackupService: no TSM accounts found, nothing to back up")
            return created
        logger.info("BackupService: found %d account(s): %s", len(accounts), list(accounts.keys()))

        all_backups = self._list_backups()
        retain_td = timedelta(days=retain_days) if retain_days > 0 else None
        period_td = timedelta(minutes=period_minutes)

        for account_key, sv_dir in accounts.items():
            # 1. Purge old backups for this account
            acct_backups = [b for b in all_backups if b["account"] == account_key]
            surviving = []
            for b in acct_backups:
                age = datetime.now() - b["timestamp"]
                if retain_td and age > retain_td and not b["keep"]:
                    try:
                        b["path"].unlink()
                        logger.info("Purged old backup: %s", b["path"].name)
                    except Exception:
                        logger.warning("Failed to purge backup: %s", b["path"])
                else:
                    surviving.append(b)
            acct_backups = surviving

            # 2. Collect TSM SV file paths + their mtimes
            sv_files = self._find_sv_files(sv_dir)
            if not sv_files:
                logger.debug("No TSM SV files for account %s", account_key)
                continue

            modified_times = [p.stat().st_mtime for p in sv_files]

            # 3+4+5. Check whether a new backup is needed
            if keep:
                # Manual backup: ignore file-change state, rate-limit to once per minute
                manual_backups = [b for b in acct_backups if b["keep"]]
                if manual_backups:
                    last_manual = max(b["timestamp"] for b in manual_backups)
                    if datetime.now() - last_manual < timedelta(minutes=1):
                        logger.debug("Manual backup rate limit not elapsed for %s", account_key)
                        continue
            else:
                # Automatic backup: skip if no file changes or period not elapsed
                if acct_backups:
                    last_backup = max(b["timestamp"] for b in acct_backups)
                    last_ts = last_backup.timestamp()
                    if max(modified_times) < last_ts:
                        logger.debug("No change since last backup for %s", account_key)
                        continue
                    if datetime.now() - last_backup < period_td:
                        logger.debug("Backup period not elapsed for %s", account_key)
                        continue
                # 6. Keep only the 9 most recent automatic backups (10th is the one
                #    we're about to create).
                auto_backups = sorted(
                    [b for b in acct_backups if not b["keep"]],
                    key=lambda b: b["timestamp"],
                    reverse=True,
                )
                for old in auto_backups[9:]:
                    try:
                        old["path"].unlink()
                        logger.debug("Pruned old backup: %s", old["path"].name)
                    except Exception:
                        pass

            # 7. Create new zip
            try:
                path = self._create_backup(sys_id, account_key, sv_files, keep=keep, name=name)
                created.append(path)
                logger.info("Backup created: %s", path.name)
            except Exception:
                logger.exception("Failed to create backup for %s", account_key)

        return created

    def restore(self, backup_path: Path) -> bool:
        """Extract all SV files from backup zip to the correct SavedVariables dir."""
        accounts = self._find_accounts()
        # Match account from filename: {sys_id}_{account}_{timestamp}[_{name}].zip
        stem = backup_path.stem
        parts = stem.split(_SEPARATOR, 3)  # [sys_id, account, timestamp, name?]
        if len(parts) < 3:
            logger.error("Cannot parse backup filename: %s", backup_path.name)
            return False
        account_key = parts[1]
        sv_dir = accounts.get(account_key)
        if sv_dir is None:
            logger.error("No matching account found for key: %s", account_key)
            return False
        try:
            with zipfile.ZipFile(backup_path, "r") as zf:
                zf.extractall(sv_dir)
            logger.info("Restored backup %s → %s", backup_path.name, sv_dir)
            return True
        except Exception:
            logger.exception("Failed to restore backup %s", backup_path)
            return False

    def delete(self, zip_path: Path) -> bool:
        """Delete a backup file. Returns True on success."""
        try:
            zip_path.unlink()
            logger.info("Deleted backup: %s", zip_path.name)
            return True
        except Exception:
            logger.exception("Failed to delete backup: %s", zip_path)
            return False

    # ── Internals ──────────────────────────────────────────────────────

    def _find_accounts(self, extra_installs=None) -> dict[str, Path]:
        """Return {account_key: sv_directory} for accounts with TSM SV files."""
        from tsm.wow.detector import find_wow_installs

        result: dict[str, Path] = {}

        # Collect installs: detector cache + user-configured extras
        installs = list(self._detector.installs) if self._detector is not None else []
        if extra_installs:
            existing = {i.path for i in installs}
            for i in extra_installs:
                if i.path not in existing:
                    installs.append(i)
                    existing.add(i.path)

        # Last resort: run a fresh filesystem scan
        if not installs:
            logger.info("BackupService: no cached installs, running fresh scan")
            installs = find_wow_installs()

        logger.info("BackupService: scanning %d WoW install(s)", len(installs))
        for wow_root, gv in iter_wow_gv_roots(installs):
            suffix = _SUFFIX_BY_GV.get(gv, "")
            wtf_accounts = wow_root / gv / "WTF" / "Account"
            if not wtf_accounts.is_dir():
                logger.debug("BackupService: no WTF/Account at %s", wtf_accounts)
                continue
            logger.info("BackupService: checking accounts at %s", wtf_accounts)
            for acct_dir in wtf_accounts.iterdir():
                if not acct_dir.is_dir() or acct_dir.name == "SavedVariables":
                    continue
                sv_dir = acct_dir / "SavedVariables"
                if not sv_dir.is_dir():
                    continue
                if any(sv_dir.glob(f"{_TSM_ADDON_PREFIX}*.lua")):
                    account_key = acct_dir.name + suffix
                    result[account_key] = sv_dir
        return result

    def _find_sv_files(self, sv_dir: Path) -> list[Path]:
        """All TradeSkillMaster*.lua files in a SavedVariables directory."""
        return list(sv_dir.glob(f"{_TSM_ADDON_PREFIX}*.lua"))

    def _create_backup(
        self,
        sys_id: str,
        account_key: str,
        sv_files: list[Path],
        keep: bool = False,
        name: str = "",
    ) -> Path:
        ts = datetime.now().strftime(_TIME_FORMAT)
        safe_name = re.sub(r"[^\w\-]", "-", name).strip("-") if name.strip() else ""
        stem = f"{sys_id}{_SEPARATOR}{account_key}{_SEPARATOR}{ts}"
        if safe_name:
            stem = f"{stem}{_SEPARATOR}{safe_name}"
        zip_path = (_KEEP_DIR if keep else _BACKUP_DIR) / f"{stem}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_LZMA) as zf:
            for sv in sv_files:
                zf.write(sv, sv.name)
        return zip_path

    def _list_backups(self) -> list[dict]:
        """Return list of {account, timestamp, path, keep, name} dicts."""
        result = []
        for keep, directory in ((False, _BACKUP_DIR), (True, _KEEP_DIR)):
            if not directory.exists():
                continue
            for f in directory.glob("*.zip"):
                parts = f.stem.split(_SEPARATOR, 3)  # [sys_id, account, ts, name?]
                if len(parts) < 3:
                    continue
                try:
                    ts = datetime.strptime(parts[2], _TIME_FORMAT)
                except ValueError:
                    continue
                result.append(
                    {
                        "account": parts[1],
                        "timestamp": ts,
                        "path": f,
                        "keep": keep,
                        "name": parts[3] if len(parts) > 3 else "",
                    }
                )
        return result
