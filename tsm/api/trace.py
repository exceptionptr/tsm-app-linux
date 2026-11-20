"""Debug tracing of REST requests and socket frames (visible with --debug).

Everything goes to the ``tsm.trace`` logger at DEBUG level. Secrets are masked
before anything is logged: bearer tokens, JWTs, signed URL parameters and token
fields in JSON bodies.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

trace_logger = logging.getLogger("tsm.trace")

MAX_BODY = 2000
MASK = "***"

_SECRET_HEADERS = frozenset({"authorization", "cookie", "set-cookie", "proxy-authorization"})
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*")
_BEARER = re.compile(r"(?i)\bbearer\s+[^\s\"',]+")
_QUERY_SECRET = re.compile(
    r"(?i)([?&](?:[^=&\s\"']*(?:signature|token|credential|secret|key|sig)[^=&\s\"']*)=)[^&\s\"']*"
)
_JSON_SECRET = re.compile(
    r"(?i)(\"[^\"]*(?:token|password|secret|authorization|cookie)[^\"]*\"\s*:\s*)\"[^\"]*\""
)


def enabled() -> bool:
    return trace_logger.isEnabledFor(logging.DEBUG)


def mask(text: str) -> str:
    """Hide secrets in free text (URLs, JSON bodies, socket frames)."""
    text = _JWT.sub(MASK, text)
    text = _BEARER.sub("Bearer " + MASK, text)
    text = _QUERY_SECRET.sub(lambda m: m.group(1) + MASK, text)
    return _JSON_SECRET.sub(lambda m: m.group(1) + f'"{MASK}"', text)


def shorten(text: str, limit: int = MAX_BODY) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [{len(text) - limit} more chars]"


def mask_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {k: MASK if k.lower() in _SECRET_HEADERS else mask(str(v)) for k, v in headers.items()}


def _clean(value: Any) -> str:
    return shorten(mask(value if isinstance(value, str) else repr(value)))


def log_request(method: str, url: str, headers: Mapping[str, str], body: Any = None) -> None:
    if not enabled():
        return
    trace_logger.debug(
        "HTTP -> %s %s headers=%s body=%s",
        method,
        mask(url),
        mask_headers(headers),
        _clean(body) if body is not None else "-",
    )


def log_response(
    method: str, url: str, status: int, headers: Mapping[str, str], body: Any = None
) -> None:
    if not enabled():
        return
    trace_logger.debug(
        "HTTP <- %s %s %s headers=%s body=%s",
        status,
        method,
        mask(url),
        mask_headers(headers),
        _clean(body) if body is not None else "-",
    )


def log_frame(direction: str, transport: str, text: str) -> None:
    """direction is ``->`` (sent) or ``<-`` (received)."""
    if not enabled():
        return
    trace_logger.debug("SOCKET %s %s %s", direction, transport, _clean(text))
