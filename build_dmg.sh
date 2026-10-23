#!/usr/bin/env bash
# build_dmg.sh — Builds a self-contained "OpenClip Editor.app" and DMG.
#
# PyInstaller bundles Python, Qt (PySide6) and the editor from
# flame_hook/openclip_editor.py into one universal2 app (Apple Silicon + Intel).
# Nothing needs to be installed on the Macs that run it.
#
# Build requirements (this machine only):
#   - a universal2 python.org Python 3.10+ (override with PYTHON=/path/to/python3)
#   - internet access the first time, to pip-install the build tools
#
# Usage:
#   ./build_dmg.sh            → dist/OpenClip Editor.app, dist/OpenClip Editor.dmg
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

APP_NAME="OpenClip Editor"
PYTHON="${PYTHON:-/Library/Frameworks/Python.framework/Versions/3.11/bin/python3}"
BUILD_DIR="build"
VENV="${BUILD_DIR}/venv"
DIST_DIR="dist"

# ─── Helpers ──────────────────────────────────────────────────────────────────

step() { echo ""; echo "==> $*"; }
die()  { echo ""; echo "ERROR: $*" >&2; exit 1; }

# ─── 1. Build environment ─────────────────────────────────────────────────────

step "Preparing build environment..."
[[ -x "$PYTHON" ]] || die "Python not found: $PYTHON (set PYTHON=/path/to/python3)"
file -b "$PYTHON" | grep -q universal \
    || echo "   Warning: $PYTHON is not universal2 — the app will only run on this Mac's architecture."
mkdir -p "$BUILD_DIR"
[[ -x "${VENV}/bin/python" ]] || "$PYTHON" -m venv "$VENV"
"${VENV}/bin/python" -m pip install --quiet --upgrade pip
"${VENV}/bin/python" -m pip install --quiet -r macos/requirements-build.txt

# ─── 2. Icon ──────────────────────────────────────────────────────────────────

step "Building icon..."
iconutil -c icns OpenClipEditor.iconset -o "${BUILD_DIR}/OpenClipEditor.icns"

# ─── 3. App bundle ────────────────────────────────────────────────────────────

step "Building ${APP_NAME}.app..."
"${VENV}/bin/pyinstaller" --noconfirm --clean --log-level WARN \
    --distpath "$DIST_DIR" --workpath "${BUILD_DIR}/pyinstaller" \
    macos/OpenClipEditor.spec
rm -rf "${DIST_DIR:?}/${APP_NAME}"     # COLLECT folder; the .app holds a copy

# ─── 4. DMG ───────────────────────────────────────────────────────────────────

step "Creating ${APP_NAME}.dmg..."
STAGING_DIR="$(mktemp -d /tmp/openclip_dmg_staging.XXXXXX)"
trap 'rm -rf "$STAGING_DIR"' EXIT
cp -R "${DIST_DIR}/${APP_NAME}.app" "$STAGING_DIR/"
ln -s /Applications "${STAGING_DIR}/Applications"
hdiutil create -quiet -ov -format UDZO \
    -volname "$APP_NAME" -srcfolder "$STAGING_DIR" \
    "${DIST_DIR}/${APP_NAME}.dmg"

# ─── Done ─────────────────────────────────────────────────────────────────────

echo ""
echo "Done!"
echo "  App : $(pwd)/${DIST_DIR}/${APP_NAME}.app  ($(du -sh "${DIST_DIR}/${APP_NAME}.app" | cut -f1))"
echo "  DMG : $(pwd)/${DIST_DIR}/${APP_NAME}.dmg  ($(du -sh "${DIST_DIR}/${APP_NAME}.dmg" | cut -f1))"
echo ""
echo "The app is ad-hoc signed, not notarized. On other Macs, the first launch"
echo "needs right-click → Open (or System Settings → Privacy & Security → Open Anyway)."
