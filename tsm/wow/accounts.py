"""Enumerate WoW accounts and their realm configurations."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from tsm.core.models.config import WoWInstall

logger = logging.getLogger(__name__)

_GAME_VERSIONS = ("_retail_", "_classic_era_", "_classic_", "_anniversary_")
_SUFFIXES = {
    "_retail_": "",
    "_classic_era_": "-Classic",
    "_classic_": "-Progression",
    "_anniversary_": "-Anniversary",
}
_TSM_ADDON_PREFIX = "TradeSkillMaster"


def get_account_dirs(install: WoWInstall) -> list[Path]:
    """Return all WoW account directories for an install."""
    wtf_accounts = Path(install.path) / "WTF" / "Account"
    if not wtf_accounts.is_dir():
        return []
    return [d for d in wtf_accounts.iterdir() if d.is_dir() and d.name != "SavedVariables"]


def get_realm_dirs(account_dir: Path) -> list[Path]:
    """Return all realm directories for a WoW account."""
    return [d for d in account_dir.iterdir() if d.is_dir()] if account_dir.is_dir() else []


def get_character_dirs(realm_dir: Path) -> list[Path]:
    """Return all character directories for a realm."""
    return [d for d in realm_dir.iterdir() if d.is_dir()] if realm_dir.is_dir() else []


def scan_tsm_accounts(detector) -> dict[str, list[str]]:
    """Return {account_display_name: [realm, ...]} from WTF directories.

    Scans all known game version directories under each detected WoW install.
    Only includes accounts that have a TradeSkillMaster.lua SavedVariables file.
    """
    result: dict[str, list[str]] = {}
    if detector is None:
        return result
    installs = detector.installs
    for install in installs:
        wow_root = Path(install.path).parent
        for gv in _GAME_VERSIONS:
            suffix = _SUFFIXES.get(gv, "")
            wtf_accounts = wow_root / gv / "WTF" / "Account"
            if not wtf_accounts.is_dir():
                continue
            for acct_dir in wtf_accounts.iterdir():
                if not acct_dir.is_dir():
                    continue
                if not re.match(r"^[A-Za-z0-9#]+$", acct_dir.name):
                    continue
                if acct_dir.name == "SavedVariables":
                    continue
                sv = acct_dir / "SavedVariables" / f"{_TSM_ADDON_PREFIX}.lua"
                if not sv.exists():
                    continue
                acct_key = acct_dir.name + suffix
                realms = scan_realm_names(acct_dir)
                if realms:
                    result.setdefault(acct_key, []).extend(realms)
    return result


def scan_realm_names(acct_dir: Path) -> list[str]:
    """Return sorted realm names from WTF Account/ACCOUNT/SERVER structure."""
    realms = [
        item.name for item in acct_dir.iterdir() if item.is_dir() and item.name != "SavedVariables"
    ]
    return sorted(realms)
