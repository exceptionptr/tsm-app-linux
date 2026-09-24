#!/usr/bin/env bash
# Build a self-contained AppImage around a bundled CPython and the app wheel.
#
#   scripts/build_appimage.sh [path/to/tsm_app-*.whl]
#
# Without an argument a wheel is built from the working tree. The dependency
# list is derived from pyproject.toml so it cannot drift, with PySide6 narrowed
# to PySide6-Essentials: the app imports only QtCore, QtGui, QtNetwork, QtSvg
# and QtWidgets, so the Addons half would add hundreds of megabytes for nothing.
#
# python-appimage assembles the AppDir, then appimagetool is run separately.
# Letting python-appimage package it too fails here: it derives the output name
# from the desktop file's "TSM Desktop App", while appimagetool replaces the
# spaces with underscores, so the copy at the end looks for a file that does
# not exist. Packaging separately also names the file after the version.
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON_VERSION="${APPIMAGE_PYTHON_VERSION:-3.12}"
RECIPE="packaging/appimage"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

WHEEL="${1:-}"
if [ -z "${WHEEL}" ]; then
    echo "==> Building wheel"
    python -m build --wheel >/dev/null
    WHEEL="$(ls -t dist/tsm_app-*.whl | head -1)"
fi
WHEEL="$(readlink -f "${WHEEL}")"
echo "==> Wheel: ${WHEEL}"

echo "==> Resolving dependencies"
cp -r "${RECIPE}" "${WORK}/recipe"
python scripts/appimage_pins.py \
    "${WORK}/recipe/requirements.txt" "${WHEEL}" "${PYTHON_VERSION}"

echo "==> Assembling AppDir (python ${PYTHON_VERSION})"
( cd "${WORK}" && python -m python_appimage build app \
    --no-packaging -p "${PYTHON_VERSION}" recipe )

APPDIR="$(find "${WORK}" -maxdepth 1 -type d -name '*-*' ! -name recipe | head -1)"
if [ -z "${APPDIR}" ]; then
    echo "AppDir was not produced" >&2
    exit 1
fi
echo "==> AppDir: $(basename "${APPDIR}")"

echo "==> Packaging"
mkdir -p dist
APPIMAGETOOL="$(python -m python_appimage which appimagetool)"
VERSION="$(basename "${WHEEL}" | cut -d- -f2)"
TARGET="dist/TSM_Desktop_App-${VERSION}-$(uname -m).AppImage"
# Runs inside containers and CI, where FUSE is usually unavailable.
APPIMAGE_EXTRACT_AND_RUN=1 ARCH="$(uname -m)" \
    "${APPIMAGETOOL}" "${APPDIR}" "${TARGET}"

chmod +x "${TARGET}"
echo "==> Built ${TARGET} ($(du -h "${TARGET}" | cut -f1))"
