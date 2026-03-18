#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
echo "Building .deb package..."
python -m build --wheel --no-isolation
dpkg-buildpackage -us -uc -b
echo "Deb package built."
