#!/usr/bin/env python3
"""Write exact version pins for the AppImage's dependencies.

    python scripts/appimage_pins.py <requirements.txt> <wheel> <python-version>

python-appimage joins its pip arguments into one shell string without quoting
them, so a requirement carrying < or > is mangled into a redirect and the
constraint is silently dropped: "PySide6-Essentials>=6.6.0" installs whatever
version happens to be newest and writes a file called "=6.6.0". Exact == pins
contain nothing the shell treats specially, and they make the bundle
reproducible besides.

The dependency set comes from pyproject.toml, with PySide6 narrowed to
PySide6-Essentials, so it cannot drift from what the app actually declares.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

PLATFORMS = ("manylinux_2_28_x86_64", "manylinux2014_x86_64", "manylinux_2_17_x86_64")


def requirements() -> list[str]:
    with open("pyproject.toml", "rb") as fh:
        deps = tomllib.load(fh)["project"]["dependencies"]

    out = []
    for dep in deps:
        spec = dep.split("#", 1)[0].strip()
        if spec.lower().startswith("pyside6"):
            spec = "PySide6-Essentials" + spec[len("PySide6") :]
        out.append(spec)
    return out


def resolve(specs: list[str], python_version: str) -> list[str]:
    abi = "cp" + python_version.replace(".", "")
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        cmd = [
            sys.executable, "-m", "pip", "install",
            "--dry-run", "--quiet", "--only-binary", ":all:",
            "--target", str(Path(tmp) / "unused"),
            "--report", str(report),
            "--python-version", python_version,
            "--implementation", "cp",
            "--abi", abi,
        ]
        for platform in PLATFORMS:
            cmd += ["--platform", platform]
        subprocess.run([*cmd, *specs], check=True)
        installed = json.loads(report.read_text())["install"]

    return sorted(
        f"{item['metadata']['name']}=={item['metadata']['version']}" for item in installed
    )


def main() -> None:
    target, wheel, python_version = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    pins = resolve(requirements(), python_version)

    shell_unsafe = [pin for pin in pins if any(c in pin for c in "<>|&;$()")]
    if shell_unsafe:
        raise SystemExit(f"refusing to emit shell-unsafe requirements: {shell_unsafe}")

    target.write_text("\n".join([*pins, wheel]) + "\n")
    print(f"    {len(pins)} pinned dependencies")


if __name__ == "__main__":
    main()
