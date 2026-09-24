#!/usr/bin/env python3
"""Check that every hardcoded version matches the one being released.

    python scripts/check_version.py 1.1.16      # or v1.1.16

The app takes its own version from the git tag through hatch-vcs, so the wheel,
deb, rpm and AppImage are always right. Several files cannot read the tag and
carry the version themselves, and a forgotten one is silent rather than loud:

  - flake.nix matters most. A flake cannot see git tags, so its hardcoded
    version is what `nix run` reports to NixOS users.
  - the Flatpak manifest is rewritten from the tag by CI, so a stale value only
    affects someone building it by hand, but it should still be right.
  - the distribution changelogs are what users read to see what they installed.

Run before tagging. The release workflow runs it too, so a mismatch fails the
release instead of shipping a wrong version.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_ID = "io.github.exceptionptr.tsm-app-linux"

# Each entry: file, a regex with one capture group, and what it feeds.
CHECKS: list[tuple[str, str, str]] = [
    # Both Nix files also define apscheduler4, whose version must not be picked
    # up instead, so each pattern is anchored on something unique to the app.
    (
        "flake.nix",
        r'# Keep in step with the version the release is tagged with\.\s*\n\s*version = "([^"]+)";',
        "the version nix run reports",
    ),
    (
        "packaging/nixpkgs/package.nix",
        r'pname = "tsm-app";\s*\n\s*version = "([^"]+)";',
        "the nixpkgs expression",
    ),
    ("packaging/PKGBUILD", r"^pkgver=(.+)$", "the AUR package"),
    ("packaging/rpm/tsm-app.spec", r"^Version:\s+(.+?)\s*$", "the rpm"),
    ("packaging/debian/changelog", r"^tsm-app \(([^-)]+)", "the deb changelog"),
    ("CHANGELOG.md", r"^## \[([0-9][^\]]*)\]", "the changelog"),
    (
        f"packaging/flatpak/{APP_ID}.metainfo.xml",
        r'<release version="([^"]+)"',
        "what app stores show",
    ),
    (f"packaging/flatpak/{APP_ID}.yml", r"^\s*tag: v(.+)$", "the Flatpak source tag"),
    (
        f"packaging/flatpak/{APP_ID}.yml",
        r"SETUPTOOLS_SCM_PRETEND_VERSION=(\S+)",
        "the version built into the Flatpak",
    ),
]


def first_match(path: Path, pattern: str) -> str | None:
    regex = re.compile(pattern, re.M)
    match = regex.search(path.read_text())
    return match.group(1) if match else None


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    expected = sys.argv[1].removeprefix("v").strip()
    print(f"Expecting {expected}\n")

    failures = []
    for filename, pattern, purpose in CHECKS:
        path = ROOT / filename
        if not path.exists():
            failures.append(f"{filename}: missing")
            continue

        found = first_match(path, pattern)
        if found is None:
            failures.append(f"{filename}: no version found, the check pattern needs updating")
        elif found != expected:
            failures.append(f"{filename}: has {found}, expected {expected} ({purpose})")
        else:
            print(f"  ok  {filename}")

    if failures:
        sys.stdout.flush()
        print("\nVersion mismatch:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1

    print(f"\nAll {len(CHECKS)} version references agree on {expected}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
