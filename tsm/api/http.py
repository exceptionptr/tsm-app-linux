"""aiohttp request class that sends exactly the headers a channel asks for.

aiohttp always puts Host first, appends Accept, Accept-Encoding and User-Agent when
they are missing, and appends Content-Length and Content-Type after the headers it
was given. The official client's channels (node-fetch, undici, the ws library) each
send a fixed header set in a fixed order and casing, so OrderedRequest

* adds no automatic headers at all,
* lets a channel builder fix the position of the headers aiohttp fills in itself
  (Host, Connection, Content-Length, Content-Type) by listing them with the value
  AUTO,
* puts the websocket handshake headers in the order of the ws library.

Headers that are not listed keep aiohttp's order after the listed ones, with Host
first when the builder did not place it (the polling channel relies on that).
"""

from __future__ import annotations

import ssl
from collections.abc import Iterable, Mapping
from functools import cache
from typing import Any

from aiohttp import ClientRequest, hdrs
from multidict import CIMultiDict
from yarl import URL

# Value of a placeholder: the position is fixed by the builder, aiohttp supplies the value.
AUTO = ""

# Handshake of the ws library: extraHeaders first, then its own, Host last (Node adds
# it after every header it was given).
WS_ORDER = (
    "Authorization",
    "Sec-WebSocket-Version",
    "Sec-WebSocket-Key",
    "Connection",
    "Upgrade",
    "Sec-WebSocket-Extensions",
    "Host",
)


@cache
def ssl_context(alpn: tuple[str, ...] = ()) -> ssl.SSLContext:
    """TLS context of one official channel, as far as Python's ssl can match it.

    Electron's Node offers TLS 1.2 and 1.3 and, on node-fetch, the ws library and
    the XHR polling, no ALPN at all; undici offers http/1.1 only. Python's default
    context would offer neither the same ALPN list nor an explicit version floor.
    Cipher list, extension order, groups and signature algorithms stay OpenSSL's:
    they cannot be set to BoringSSL's from Python (see docs/api.md).
    """
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.maximum_version = ssl.TLSVersion.MAXIMUM_SUPPORTED
    if alpn:
        ctx.set_alpn_protocols(list(alpn))
    return ctx


# node-fetch, the ws library and the XHR polling send no ALPN extension.
NODE_SSL = ssl_context()
# undici offers http/1.1.
UNDICI_SSL = ssl_context(("http/1.1",))


def raw_url(url: str) -> URL:
    """A URL that goes out byte for byte (presigned query strings keep %2B, %2F, =)."""
    return URL(url, encoded=True)


class OrderedRequest(ClientRequest):
    """ClientRequest that sends the builder's header order, casing and nothing else."""

    _template: list[str]

    def update_headers(self, headers: Any) -> None:
        template: list[str] = []
        given: list[tuple[str, str]] = []
        items: Iterable[tuple[str, str]]
        if not headers:
            items = ()
        elif isinstance(headers, Mapping) or hasattr(headers, "items"):
            items = headers.items()
        else:
            items = headers
        for key, value in items:
            template.append(key)
            if value != AUTO:
                given.append((key, value))
        self._template = template
        super().update_headers(given)

    def update_auto_headers(self, skip_auto_headers: Iterable[str] | None) -> None:
        """Add nothing: every header comes from the channel builder."""

    async def send(self, conn: Any) -> Any:
        self._arrange()
        return await super().send(conn)

    def _arrange(self) -> None:
        current: CIMultiDict[str] = self.headers
        if hdrs.SEC_WEBSOCKET_KEY in current:
            template: list[str] = list(WS_ORDER)
        else:
            template = list(self._template)
        if self.method == hdrs.METH_DELETE and current.get(hdrs.CONTENT_LENGTH) == "0":
            del current[hdrs.CONTENT_LENGTH]
        lowered = {name.lower() for name in template}
        if hdrs.CONNECTION.lower() in lowered and hdrs.CONNECTION not in current:
            current[hdrs.CONNECTION] = "keep-alive"
        out: CIMultiDict[str] = CIMultiDict()
        placed: set[str] = set()
        for name in template:
            key = name.lower()
            if key in placed or name not in current:
                continue
            placed.add(key)
            for value in current.getall(name):
                out.add(name, value)
        host = current.get(hdrs.HOST)
        if hdrs.HOST.lower() not in placed and host is not None:
            # Host is first unless the builder placed it.
            first: CIMultiDict[str] = CIMultiDict()
            first.add(hdrs.HOST, host)
            first.extend(out)
            out = first
            placed.add(hdrs.HOST.lower())
        for name, value in current.items():
            if name.lower() not in placed:
                out.add(name, value)
        self.headers = out
