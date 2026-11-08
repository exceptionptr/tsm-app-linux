"""Read and atomically write TradeSkillMaster_AppHelper/AppData.lua.

Format written by the official 1.0.9 client (exportAddonDataWorker), one line
per entry, each ending in a meta comment the next run parses back:

    select(2, ...).LoadData("TYPE","Key",[[return DATA]]) --<TYPE,Key,time>
    select(2, ...).LoadData("TYPE","Key",[[return DATA]]) --<TYPE,Key,time,ahId>
    for _,r in ipairs({"A","B"}) do select(2, ...).LoadData("TYPE",r,[[return DATA]]) end
        --<TYPE,A|B,time,ahId>    (same line in the file, wrapped here)

- Key is a realm ("Tarren Mill", "Everlook-Horde"), a region ("EU", "BCC-EU")
  or "Global" for APP_INFO.
- ahId is the auction house id. Connected realms share one auction house, so
  entries with the same type, ahId and time are written once for all of them
  with the ipairs form instead of duplicating a multi-megabyte blob.
- Lines this module cannot take apart are kept verbatim ("raw"), so an older or
  newer writer's entries survive a rewrite untouched.

The legacy Python client wrote only the 3-field form, which is read here too.
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

APPDATA_FILE = "AppData.lua"


def _wrap(tag: str, keys: list[str]) -> tuple[str, str]:
    if len(keys) == 1:
        return f'select(2, ...).LoadData("{tag}","{keys[0]}",[[return ', "]])"
    names = ",".join(f'"{k}"' for k in keys)
    return (
        f'for _,r in ipairs({{{names}}}) do select(2, ...).LoadData("{tag}",r,[[return ',
        "]]) end",
    )


def _unwrap(code: str, tag: str, keys: list[str]) -> str | None:
    prefix, suffix = _wrap(tag, keys)
    if code.startswith(prefix) and code.endswith(suffix):
        return code[len(prefix) : len(code) - len(suffix)]
    return None


@dataclass
class AppDataEntry:
    tag: str
    key: str
    data: str  # inner blob, or the whole code line when raw
    time: int
    auction_house_id: int | None = None
    raw: bool = False


class AppDataFile:
    """In-memory AppData.lua. Load, update or remove entries, then save()."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: list[AppDataEntry] = []
        self._modified = False
        if path.exists():
            self._load()

    def _load(self) -> None:
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            logger.exception("Failed to read %s", self.path)
            return
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            idx = line.rfind("--<")
            if idx == -1 or not line.endswith(">"):
                logger.warning("Dropping AppData.lua line without meta: %.80s", line)
                continue
            code = line[:idx].rstrip()
            fields = [f.strip() for f in line[idx + 3 : -1].split(",")]
            if len(fields) < 3 or not fields[0] or not fields[1]:
                logger.warning("Dropping AppData.lua line with bad meta: %.80s", line[idx:])
                continue
            tag, key_field, time_s = fields[0], fields[1], fields[2]
            try:
                ts = int(time_s)
            except ValueError:
                ts = 0
            ah_id: int | None = None
            if len(fields) > 3:
                try:
                    ah_id = int(fields[3])
                except ValueError:
                    ah_id = None
            keys = key_field.split("|")
            inner = _unwrap(code, tag, keys)
            if inner is None:
                self.entries.append(AppDataEntry(tag, key_field, code, ts, ah_id, raw=True))
                continue
            for k in keys:
                self.entries.append(AppDataEntry(tag, k, inner, ts, ah_id))

    def _find(self, tag: str, key: str) -> AppDataEntry | None:
        for e in reversed(self.entries):
            if e.tag == tag and e.key == key:
                return e
        return None

    def last_update(self, tag: str, key: str) -> int | None:
        """Stored timestamp for (tag, key), or None if absent."""
        e = self._find(tag, key)
        return e.time if e else None

    def update(
        self, tag: str, key: str, data: str, time: int, auction_house_id: int | None = None
    ) -> bool:
        """Insert or replace an entry. An older timestamp than the stored one is ignored."""
        e = self._find(tag, key)
        if e is not None and time < e.time:
            return False
        self._modified = True
        if e is None:
            self.entries.append(AppDataEntry(tag, key, data, time, auction_house_id))
        else:
            e.data, e.time, e.auction_house_id, e.raw = data, time, auction_house_id, False
        return True

    def remove(self, keys: Iterable[str]) -> list[str]:
        """Drop every entry for these keys. Returns the keys actually removed."""
        wanted = set(keys)
        removed: set[str] = set()
        kept = []
        for e in self.entries:
            if e.key in wanted:
                removed.add(e.key)
            else:
                kept.append(e)
        if removed:
            self.entries = kept
            self._modified = True
        return sorted(removed)

    def render(self) -> str:
        # Newest entries first, mirroring the official writer, and fold entries that
        # share an auction house and timestamp into one ipairs line.
        groups: list[tuple[AppDataEntry, list[str]]] = []
        by_ah: dict[tuple[str, int, int], list[str]] = {}
        for e in reversed(self.entries):
            if e.auction_house_id is not None and not e.raw:
                gk = (e.tag, e.auction_house_id, e.time)
                if gk in by_ah:
                    by_ah[gk].append(e.key)
                    continue
                keys = [e.key]
                by_ah[gk] = keys
            else:
                keys = [e.key]
            groups.append((e, keys))

        lines = []
        for e, keys in groups:
            meta = [e.tag, "|".join(keys), str(e.time)]
            if e.auction_house_id is not None:
                meta.append(str(e.auction_house_id))
            if e.raw:
                code = e.data
            else:
                prefix, suffix = _wrap(e.tag, keys)
                code = prefix + e.data + suffix
            lines.append(f"{code} --<{','.join(meta)}>")
        return "\n".join(lines) + "\n" if lines else ""

    def save(self, force: bool = False) -> bool:
        """Atomically write the file if anything changed. Returns True if written."""
        if not self._modified and not force:
            return False
        content = self.render()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        self._modified = False
        logger.info("Wrote %s (%d entries, %d bytes)", self.path, len(self.entries), len(content))
        return True


def lua_string(value: object) -> str:
    """Quote a value as a Lua string the way the official client does.

    Backslash, double quote, ] and control characters become decimal escapes, so
    the result is safe both as a Lua string and inside the [[...]] long bracket
    that wraps the whole APP_INFO table (a raw "]]" would close it early).
    """
    s = "" if value is None else str(value)
    out = []
    for ch in s:
        o = ord(ch)
        if ch in '\\"]' or o < 0x20 or o == 0x7F:
            out.append(f"\\{o:03d}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _lua_number(value: object) -> str:
    try:
        n = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "0"
    if n != n or n in (float("inf"), float("-inf")):
        return "0"
    return str(int(n)) if n.is_integer() else repr(n)


def render_app_info(
    version: str, last_sync: int, message: dict | None = None, news: list[dict] | None = None
) -> str:
    """APP_INFO blob in the official client's format."""
    message = message or {}
    items = [
        "{title="
        + lua_string(n.get("title"))
        + ",content="
        + lua_string(n.get("content"))
        + ",timestamp="
        + _lua_number(n.get("timestamp"))
        + ",link="
        + lua_string(n.get("link"))
        + "}"
        for n in (news or [])
    ]
    return (
        "{version="
        + lua_string(version)
        + f",lastSync={int(last_sync)}"
        + ",message={id="
        + _lua_number(message.get("id"))
        + ",msg="
        + lua_string(message.get("msg"))
        + "},news={"
        + ",".join(items)
        + "}}"
    )
