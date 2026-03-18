#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(python -c "from tsm import __version__; print(__version__)" 2>/dev/null || echo "1.0.0")
echo "Building .rpm package for v$VERSION..."
python -m build --wheel --no-isolation
rpmbuild -ba packaging/rpm/tsm-app.spec \
  --define "_topdir $(pwd)/rpmbuild" \
  --define "_version $VERSION"
echo "RPM package built."
