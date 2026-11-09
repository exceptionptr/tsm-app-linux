#!/usr/bin/env python3
"""Probe TSM API endpoints for HTTPS/SSL support.

Run this script to determine which TSM API hosts support verified HTTPS
and which fall back to plain HTTP. Results guide the ssl= settings in
tsm/api/client.py.

Usage:
    python3 scripts/check_ssl.py
"""

from __future__ import annotations

import socket
import ssl
from dataclasses import dataclass
from typing import Any

# All known TSM API hostnames
_HOSTS = [
    "id.tradeskillmaster.com",  # OIDC auth (always HTTPS - Keycloak)
    "app-server.tradeskillmaster.com",  # v2/auth, v2/realms2, v2/status
    "realm-data.tradeskillmaster.com",  # typical endpointSubdomain
    "data.tradeskillmaster.com",  # CDN blob downloads
    "tradeskillmaster.com",  # base domain
]

_TIMEOUT = 5


@dataclass
class Result:
    host: str
    https_ok: bool
    cert_subject: str
    cert_san: list[str]
    error: str


def _failure(host: str, error: str) -> Result:
    return Result(host=host, https_ok=False, cert_subject="", cert_san=[], error=error)


def _cert_fields(cert: dict[str, Any] | None) -> tuple[str, list[str]]:
    """Return (common name, DNS SANs) from a getpeercert() dict."""
    cert = cert or {}
    cn = "?"
    for rdn in cert.get("subject", ()):
        for key, value in rdn:
            if key == "commonName":
                cn = str(value)
    san = [str(v) for (t, v) in cert.get("subjectAltName", ()) if t == "DNS"]
    return cn, san


def probe(host: str) -> Result:
    try:
        ctx = ssl.create_default_context()
        with (
            socket.create_connection((host, 443), timeout=_TIMEOUT) as sock,
            ctx.wrap_socket(sock, server_hostname=host) as ssock,
        ):
            cn, san = _cert_fields(ssock.getpeercert())
            return Result(
                host=host,
                https_ok=True,
                cert_subject=cn,
                cert_san=san,
                error="",
            )
    except ssl.SSLCertVerificationError as e:
        # Connect succeeded but cert verification failed - get cert anyway
        try:
            ctx_noverify = ssl.create_default_context()
            ctx_noverify.check_hostname = False
            ctx_noverify.verify_mode = ssl.CERT_NONE
            with (
                socket.create_connection((host, 443), timeout=_TIMEOUT) as sock,
                ctx_noverify.wrap_socket(sock, server_hostname=host) as ssock,
            ):
                cn, san = _cert_fields(ssock.getpeercert(binary_form=False))
                return Result(
                    host=host,
                    https_ok=False,
                    cert_subject=cn,
                    cert_san=san,
                    error=str(e),
                )
        except Exception as e2:
            return _failure(host, str(e2))
    except ConnectionRefusedError:
        return _failure(host, "Port 443 refused (HTTP only?)")
    except TimeoutError:
        return _failure(host, "Connection timed out")
    except Exception as e:
        return _failure(host, str(e))


def main() -> None:
    print("TSM API SSL probe")
    print("=" * 60)
    for host in _HOSTS:
        r = probe(host)
        status = "HTTPS OK" if r.https_ok else "HTTPS FAIL"
        print(f"\n[{status}] {r.host}")
        if r.cert_subject:
            print(f"  Cert CN:  {r.cert_subject}")
        if r.cert_san:
            print(f"  Cert SAN: {', '.join(r.cert_san)}")
        if r.error:
            print(f"  Error:    {r.error}")

    print("\n" + "=" * 60)
    print("Summary - use in tsm/api/client.py:")
    for host in _HOSTS:
        r = probe(host)
        scheme = "https" if r.https_ok else "http"
        ssl_note = "" if r.https_ok else "  # ssl=False or ssl=None (cert mismatch)"
        print(f"  {host}: {scheme}://{host}/...{ssl_note}")


if __name__ == "__main__":
    main()
