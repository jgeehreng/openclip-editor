#!/usr/bin/env bash
# build_dmg.sh — Builds a lightweight OpenClip Editor.app wrapper + DMG.
#
# Instead of py2app (which bundles Tk and causes Tk 9/NSCalendarDate crashes on
# macOS 15 Sequoia), this creates a shell-script .app that calls the Homebrew
# Python 3.12 already installed on the machine.  Much lighter, no Tk bundling.
#
# Requirements on every machine that RUNS the app:
#   brew install python-tk@3.12
#
# Usage:
#   chmod +x build_dmg.sh && ./build_dmg.sh
set -euo pipefail

APP_NAME="OpenClip Editor"
APP_BUNDLE="${APP_NAME}.app"
APP_PATH="${APP_BUNDLE}"
DMG_NAME="${APP_NAME}.dmg"
STAGING_DIR="$(mktemp -d /tmp/openclip_dmg_staging.XXXXXX)"

# ─── Helpers ──────────────────────────────────────────────────────────────────

step() { echo ""; echo "==> $*"; }
die()  { echo ""; echo "ERROR: $*" >&2; exit 1; }

# ─── 1. Clean previous build ──────────────────────────────────────────────────

step "Cleaning previous build..."
rm -rf "${APP_PATH}" "${DMG_NAME}"

# ─── 2. Create .app bundle structure ──────────────────────────────────────────

step "Building ${APP_BUNDLE}..."
mkdir -p "${APP_PATH}/Contents/MacOS"
mkdir -p "${APP_PATH}/Contents/Resources"

# Copy payload
cp openclip_editor.py "${APP_PATH}/Contents/Resources/"
cp openclip_icon.icns "${APP_PATH}/Contents/Resources/"

# Bundle minimal PyObjC so the menu bar shows "OpenClip Editor" (not "Python").
# PyObjC's bridge handles the NSDictionary mutation correctly and safely.
SITE_PKGS="${APP_PATH}/Contents/Resources/site-packages"
mkdir -p "${SITE_PKGS}"
if /opt/homebrew/bin/python3.12 -m pip install --quiet --target="${SITE_PKGS}" \
       pyobjc-core pyobjc-framework-Cocoa 2>/dev/null; then
    echo "   PyObjC bundled (menu bar name fix)."
else
    echo "   Warning: PyObjC bundling failed — menu bar will fall back to 'Python'."
fi

# Launcher — searches all common Python locations, verifies tkinter works
cat > "${APP_PATH}/Contents/MacOS/OpenClip Editor" << 'LAUNCHER'
#!/usr/bin/env bash
PYTHON=""

# Build candidate list: Homebrew (Apple Silicon + Intel), python.org framework,
# pyenv, and anything on PATH — newest versions first.
CANDIDATES=(
    /opt/homebrew/bin/python3.12
    /opt/homebrew/bin/python3.11
    /opt/homebrew/bin/python3.13
    /usr/local/bin/python3.12
    /usr/local/bin/python3.11
    /usr/local/bin/python3.13
    /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12
    /Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11
    /Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13
    /Library/Frameworks/Python.framework/Versions/3.10/bin/python3.10
)

# Also append anything on the user's PATH
for name in python3.12 python3.11 python3.13 python3.10 python3; do
    found="$(command -v "$name" 2>/dev/null)"
    [[ -n "$found" ]] && CANDIDATES+=("$found")
done

for candidate in "${CANDIDATES[@]}"; do
    [[ -x "$candidate" ]] || continue
    # Verify tkinter is importable (python.org includes it; system Python does not)
    if "$candidate" -c "import tkinter" 2>/dev/null; then
        PYTHON="$candidate"
        break
    fi
done

if [[ -z "$PYTHON" ]]; then
    osascript << 'APPLESCRIPT'
tell application "System Events"
    display dialog "OpenClip Editor requires Python 3 with tkinter, which was not found on this machine.

Download the free installer from:
  https://www.python.org/downloads/macos/

The standard python.org installer includes tkinter.

Alternatively, if you have Homebrew:
  brew install python-tk@3.12" buttons {"OK"} default button 1 with icon stop with title "OpenClip Editor — Python Not Found"
end tell
APPLESCRIPT
    exit 1
fi

RESOURCES="$(dirname "$0")/../Resources"
# Add bundled site-packages (PyObjC) so the menu bar shows "OpenClip Editor"
SITE_PKGS="$RESOURCES/site-packages"
if [[ -d "$SITE_PKGS" ]]; then
    export PYTHONPATH="$SITE_PKGS${PYTHONPATH:+:$PYTHONPATH}"
fi
exec -a "OpenClip Editor" "$PYTHON" "$RESOURCES/openclip_editor.py" "$@"
LAUNCHER
chmod +x "${APP_PATH}/Contents/MacOS/OpenClip Editor"

# Info.plist
cat > "${APP_PATH}/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>             <string>OpenClip Editor</string>
  <key>CFBundleDisplayName</key>      <string>OpenClip Editor</string>
  <key>CFBundleIdentifier</key>       <string>com.uc.openclipeditor</string>
  <key>CFBundleVersion</key>          <string>1.1.0</string>
  <key>CFBundleShortVersionString</key><string>1.1.0</string>
  <key>CFBundleExecutable</key>       <string>OpenClip Editor</string>
  <key>CFBundleIconFile</key>         <string>openclip_icon</string>
  <key>CFBundlePackageType</key>      <string>APPL</string>
  <key>NSHighResolutionCapable</key>  <true/>
  <key>LSMinimumSystemVersion</key>   <string>13.0</string>

  <!-- Register .clip as a known file type owned by this app -->
  <key>CFBundleDocumentTypes</key>
  <array>
    <dict>
      <key>CFBundleTypeName</key>       <string>Flame Open Clip</string>
      <key>CFBundleTypeRole</key>       <string>Editor</string>
      <key>CFBundleTypeExtensions</key> <array><string>clip</string></array>
      <key>LSItemContentTypes</key>     <array><string>com.autodesk.flame.clip</string></array>
      <key>LSHandlerRank</key>          <string>Owner</string>
    </dict>
  </array>

  <!-- Declare the UTI so macOS Launch Services recognises .clip as distinct -->
  <key>UTExportedTypeDeclarations</key>
  <array>
    <dict>
      <key>UTTypeIdentifier</key>  <string>com.autodesk.flame.clip</string>
      <key>UTTypeDescription</key> <string>Flame Open Clip</string>
      <key>UTTypeConformsTo</key>  <array><string>public.xml</string></array>
      <key>UTTypeTagSpecification</key>
      <dict>
        <key>public.filename-extension</key> <array><string>clip</string></array>
      </dict>
    </dict>
  </array>
</dict>
</plist>
PLIST

# ─── 3. Stage DMG contents ────────────────────────────────────────────────────

step "Staging DMG content..."
cp -r "${APP_PATH}" "${STAGING_DIR}/"
ln -s /Applications "${STAGING_DIR}/Applications"

# ─── 4. Create DMG ────────────────────────────────────────────────────────────

step "Creating ${DMG_NAME}..."
hdiutil create \
    -volname  "${APP_NAME}" \
    -srcfolder "${STAGING_DIR}" \
    -ov \
    -format   UDZO \
    "${DMG_NAME}"

# ─── 5. Cleanup ───────────────────────────────────────────────────────────────

rm -rf "${STAGING_DIR}"

# ─── Done ─────────────────────────────────────────────────────────────────────

echo ""
echo "Done!"
echo "  App : $(pwd)/${APP_PATH}"
echo "  DMG : $(pwd)/${DMG_NAME}"
echo ""
echo "Each machine that runs the app needs Python 3 with tkinter:"
echo "  Option A (no Homebrew): https://www.python.org/downloads/macos/"
echo "  Option B (Homebrew):    brew install python-tk@3.12"
echo ""
echo "To run directly without the .app:"
echo "  /opt/homebrew/bin/python3.12 openclip_editor.py [/path/to/file.clip]"
