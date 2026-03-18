#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(python -c "from tsm import __version__; print(__version__)" 2>/dev/null || echo "1.0.0")
echo "Building TSM App v$VERSION..."
python -m nuitka \
  --standalone \
  --onefile \
  --enable-plugin=pyside6 \
  --linux-icon=packaging/tsm-app.png \
  --output-dir=dist/ \
  --output-filename=tsm-app \
  --product-name="TSM Desktop App" \
  --product-version="$VERSION" \
  --company-name="tsm-app" \
  --assume-yes-for-downloads \
  tsm/__main__.py
echo "Build complete: dist/tsm-app"
