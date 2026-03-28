"""Zip extraction helpers with path-traversal protection."""

import os
from pathlib import Path
from zipfile import ZipFile


def safe_extractall(zf: ZipFile, dest: Path) -> None:
    """Extract all members of *zf* into *dest*, rejecting zip-slip paths.

    Raises ValueError if any member would resolve outside *dest*.
    """
    dest_resolved = dest.resolve()
    for member in zf.infolist():
        member_path = (dest_resolved / member.filename).resolve()
        if not str(member_path).startswith(str(dest_resolved) + os.sep):
            raise ValueError(f"Zip slip detected: {member.filename!r}")
    zf.extractall(dest)
