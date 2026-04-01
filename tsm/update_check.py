"""GitHub release tag check for update notifications."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_TAGS_URL = "https://api.github.com/repos/exceptionptr/tsm-app-linux/tags"


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse 'v1.2.3' or '1.2.3' to (1, 2, 3). Returns (0,) on parse failure."""
    try:
        return tuple(int(x) for x in v.lstrip("v").split("."))
    except ValueError:
        return (0,)


async def fetch_latest_tag() -> str | None:
    """Return the latest tag name from GitHub (e.g. 'v1.1.5'), or None on error."""
    try:
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=10)
        async with (
            aiohttp.ClientSession() as session,
            session.get(_TAGS_URL, timeout=timeout) as resp,
        ):
            if resp.status != 200:
                logger.debug("update_check: GitHub API returned %d", resp.status)
                return None
            tags: list[dict[str, object]] = await resp.json()
            if not tags or not isinstance(tags, list):
                return None
            return str(tags[0]["name"])
    except Exception:
        logger.debug("update_check: failed to fetch tags", exc_info=True)
        return None


def is_newer(tag: str, current: str) -> bool:
    """Return True if tag represents a version newer than current."""
    return _parse_version(tag) > _parse_version(current)
