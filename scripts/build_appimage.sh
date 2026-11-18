#!/usr/bin/env bash
# Build a self-contained AppImage around a bundled CPython and the app wheel.
#
#   scripts/build_appimage.sh [path/to/tsm_app-*.whl]
#
# Without an argument a wheel is built from the working tree. The dependency
# list is derived from pyproject.toml so it cannot drift, with PySide6 split into
# PySide6-Essentials and PySide6-Addons: the login window needs QtWebEngine and
# QtWebChannel, and those live in the Addons half.
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
# python-appimage downloads its Python AppImage from GitHub releases, which
# answers with the odd 502 or 504. Retry a few times before giving up.
for attempt in 1 2 3 4; do
    if ( cd "${WORK}" && python -m python_appimage build app \
        --no-packaging -p "${PYTHON_VERSION}" recipe ); then
        break
    fi
    if [ "${attempt}" -eq 4 ]; then
        echo "Assembling the AppDir failed ${attempt} times" >&2
        exit 1
    fi
    echo "==> Attempt ${attempt} failed, retrying in $((attempt * 15)) s" >&2
    find "${WORK}" -mindepth 1 -maxdepth 1 ! -name recipe -exec rm -rf {} +
    sleep $((attempt * 15))
done

APPDIR="$(find "${WORK}" -maxdepth 1 -type d -name '*-*' ! -name recipe | head -1)"
if [ -z "${APPDIR}" ]; then
    echo "AppDir was not produced" >&2
    exit 1
fi
echo "==> AppDir: $(basename "${APPDIR}")"

# The login window runs on QtWebEngine. If a change to python-appimage or to the
# pins ever drops the Addons half, the AppImage would start and fail only when
# somebody signs in, so check that every piece the window needs is bundled.
PYSIDE="$(find "${APPDIR}" -maxdepth 6 -type d -name PySide6 | head -1)"
if [ -z "${PYSIDE}" ]; then
    echo "PySide6 is missing from the bundle" >&2
    exit 1
fi
for needed in \
    QtWebEngineCore.abi3.so \
    QtWebEngineWidgets.abi3.so \
    QtWebChannel.abi3.so \
    Qt/libexec/QtWebEngineProcess \
    Qt/resources/qtwebengine_resources.pak \
    Qt/resources/icudtl.dat \
    Qt/lib/libQt6WebEngineCore.so.6 \
    Qt/lib/libQt6WebChannel.so.6; do
    if [ ! -e "${PYSIDE}/${needed}" ]; then
        echo "QtWebEngine piece missing from the bundle: ${needed}" >&2
        exit 1
    fi
done

echo "==> Packaging"
mkdir -p dist
# python-appimage only fetches appimagetool when it packages an image itself,
# which --no-packaging skips, so ask for it explicitly. Without this "which"
# returns nothing on a cold cache and the packaging line runs an empty command.
python -c 'from python_appimage.utils.deps import ensure_appimagetool; ensure_appimagetool()'
APPIMAGETOOL="$(python -m python_appimage which appimagetool)"
if [ -z "${APPIMAGETOOL}" ]; then
    echo "appimagetool could not be located" >&2
    exit 1
fi
VERSION="$(basename "${WHEEL}" | cut -d- -f2)"
TARGET="dist/TSM_Desktop_App-${VERSION}-$(uname -m).AppImage"
# Runs inside containers and CI, where FUSE is usually unavailable.
APPIMAGE_EXTRACT_AND_RUN=1 ARCH="$(uname -m)" \
    "${APPIMAGETOOL}" "${APPDIR}" "${TARGET}"

chmod +x "${TARGET}"
echo "==> Built ${TARGET} ($(du -h "${TARGET}" | cut -f1))"
