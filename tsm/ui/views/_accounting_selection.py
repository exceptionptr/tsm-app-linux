"""The account, realm and character picked on the Accounting tab.

Remembered in a small JSON file so that neither a realm data update, which
rescans the accounts, nor a restart throws the user back to the first account
in the list (issue #25). No Qt here, so it can be tested headless.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Selection:
    account: str = ""
    realm: str = ""
    character: str = ""


def pick_index(items: list[str], wanted: str) -> int:
    """Index of `wanted` in `items`, the first entry if it is absent, -1 if empty."""
    if not items:
        return -1
    try:
        return items.index(wanted)
    except ValueError:
        return 0


def load_selection(path: Path) -> Selection:
    """The saved selection, or an empty one if there is none or it is unreadable."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Selection()
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring unreadable accounting selection %s: %s", path, exc)
        return Selection()
    if not isinstance(raw, dict):
        return Selection()

    def text(key: str) -> str:
        value = raw.get(key)
        return value if isinstance(value, str) else ""

    return Selection(account=text("account"), realm=text("realm"), character=text("character"))


def save_selection(path: Path, selection: Selection) -> None:
    """Write the selection; a failure is logged, never raised, as it only costs comfort."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(selection)), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not save the accounting selection to %s: %s", path, exc)
