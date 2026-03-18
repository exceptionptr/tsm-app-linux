"""Read WoW SavedVariables.lua files.

Parses the flat-key TSM database format used for accounting data:
    TradeSkillMasterDB = {
        ["r@RealmName@internalData@csvSales"] = "...",
        ...
    }
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def read_saved_variables(path: Path) -> dict[str, str]:
    """Parse a WoW SavedVariables.lua file into a Python dict.

    Returns the top-level variable as a flat dict of string keys to string values.
    Handles the TSM flat-key format used for accounting data.
    """
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        return _parse_tsm_db(text)
    except Exception:
        logger.exception("Failed to read SavedVariables: %s", path)
        return {}


def _parse_tsm_db(text: str) -> dict[str, str]:
    """Extract flat string key→value pairs from a TSM SavedVariables file.

    Handles both regular strings and long strings ([[...]] or [=[...]=]).
    """
    result: dict[str, str] = {}

    # Match: ["key"] = "value" (single-line string values)
    # The value may contain escaped quotes but not unescaped ones.
    str_pattern = re.compile(
        r'\["([^"]+)"\]\s*=\s*"((?:[^"\\]|\\.)*)\"',
        re.DOTALL,
    )
    for m in str_pattern.finditer(text):
        result[m.group(1)] = m.group(2)

    # Match: ["key"] = [[value]] (long strings, level 0)
    long_str_pattern = re.compile(
        r'\["([^"]+)"\]\s*=\s*\[\[(.*?)\]\]',
        re.DOTALL,
    )
    for m in long_str_pattern.finditer(text):
        result[m.group(1)] = m.group(2)

    # Match top-level: VarName["key"] = "value" or simple string fields
    # Also handle: ["key"] = number
    num_pattern = re.compile(r'\["([^"]+)"\]\s*=\s*(-?\d+(?:\.\d+)?)')
    for m in num_pattern.finditer(text):
        key = m.group(1)
        if key not in result:
            result[key] = m.group(2)

    return result
