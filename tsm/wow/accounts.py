"""Enumerate WoW accounts and their realm configurations."""

from __future__ import annotations

import logging
from pathlib import Path

from tsm.core.models.config import WoWInstall

logger = logging.getLogger(__name__)


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
