"""Read which group sends the addon has imported or discarded.

The AppHelper addon records every send it handled in its SavedVariables file:

    TradeSkillMaster_AppHelperDB = {
        ["groupImports"] = { ["<send id>"] = "IMPORTED", ["<other id>"] = "DISCARDED" },
    }

The official client reads this file for every account folder of every installed
game version and drops the ids marked IMPORTED or DISCARDED from its pending list.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)

DONE_STATES = ("IMPORTED", "DISCARDED")
SAVED_VARIABLES_FILE = "TradeSkillMaster_AppHelper.lua"

_BLOCK = re.compile(r'\[\s*"groupImports"\s*\]\s*=\s*\{([^{}]*)\}')
_ENTRY = re.compile(r'\[\s*"((?:[^"\\]|\\.)*)"\s*\]\s*=\s*"([^"]*)"')


def _ci_child(parent: Path, name: str) -> Path | None:
    direct = parent / name
    if direct.exists():
        return direct
    try:
        lower = name.lower()
        for child in parent.iterdir():
            if child.name.lower() == lower:
                return child
    except OSError:
        pass
    return None


def parse_done_ids(text: str) -> set[str]:
    """Ids of the first groupImports table that are IMPORTED or DISCARDED."""
    m = _BLOCK.search(text)
    if m is None:
        return set()
    return {sid for sid, state in _ENTRY.findall(m.group(1)) if state in DONE_STATES}


def read_done_ids(base: Path, folder: str) -> set[str]:
    """Done ids across every account of one game version. Read errors give an empty set."""
    done: set[str] = set()
    account_root = base / folder
    for seg in ("WTF", "Account"):
        child = _ci_child(account_root, seg)
        if child is None:
            return done
        account_root = child
    try:
        accounts = [p for p in account_root.iterdir() if p.is_dir()]
    except OSError:
        return done
    for account in accounts:
        if account.name.lower() == "savedvariables" or account.name == ".DS_Store":
            continue
        sv = _ci_child(account, "SavedVariables")
        path = _ci_child(sv, SAVED_VARIABLES_FILE) if sv is not None else None
        if path is None:
            continue
        try:
            done |= parse_done_ids(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            logger.warning("Could not read %s", path)
    return done


def read_all_done_ids(bases: Iterable[Path], folders: Iterable[str]) -> set[str]:
    folders = list(folders)
    done: set[str] = set()
    for base in bases:
        for folder in folders:
            done |= read_done_ids(base, folder)
    return done
