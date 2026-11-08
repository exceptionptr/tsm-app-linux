#!/usr/bin/env python3
"""Print the CHANGELOG.md section of one version, for the GitHub release body.

    python scripts/release_notes.py 2.0.0      # or v2.0.0

The section runs from its `## [x.y.z]` heading to the next `## ` heading or
`---` rule, without the heading itself. A version with no section, or an empty
one, is an error, so a release cannot go out with the notes missing.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def section(text: str, version: str) -> str | None:
    heading = re.compile(rf"^## \[{re.escape(version)}\][^\n]*\n", re.M)
    match = heading.search(text)
    if match is None:
        return None
    rest = text[match.end() :]
    end = re.search(r"^(## |---\s*$)", rest, re.M)
    body = rest[: end.start()] if end else rest
    return body.strip()


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    version = sys.argv[1].removeprefix("v").strip()
    body = section(CHANGELOG.read_text(encoding="utf-8"), version)
    if not body:
        print(f"CHANGELOG.md has no notes for {version}", file=sys.stderr)
        return 1

    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
