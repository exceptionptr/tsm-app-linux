#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
echo "Preparing AUR package..."
cp packaging/PKGBUILD .
makepkg -si
echo "AUR package built and installed."
