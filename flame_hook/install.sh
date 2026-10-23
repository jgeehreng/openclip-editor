#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# OpenClip Editor — Flame hook installer
# Supports macOS and Rocky Linux (both platforms Flame runs on)
# Run from any location:  bash /path/to/flame_hook/install.sh
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

INSTALL_DIR="${OPENCLIP_INSTALL_DIR:-/opt/Autodesk/shared/python/openclip_editor}"
HOOK_SRC="$SCRIPT_DIR/openclip_editor.py"
HOOK_NAME="openclip_editor.py"

OS="$(uname -s)"

# ── colour helpers ─────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${GREEN}==>$NC $*"; }
warn()    { echo -e "${YELLOW}WARNING:$NC $*"; }
error()   { echo -e "${RED}ERROR:$NC $*"; exit 1; }
section() { echo -e "\n${BOLD}$*${NC}"; }

# ── verify source file ─────────────────────────────────────────────────────────
section "Checking source file"
[[ -f "$HOOK_SRC" ]] || error "Hook not found: $HOOK_SRC"
info "Found: $HOOK_SRC"

# ── verify PySide is available in Flame's Python ───────────────────────────────
section "Checking for PySide2/PySide6"

# Flame bundles its own Python under /opt/Autodesk/python/<flame version>/
FOUND_ANY=""
PYSIDE_OK=""
for candidate in /opt/Autodesk/python/*/bin/python3; do
    [[ -x "$candidate" ]] || continue
    FOUND_ANY=1
    flame_ver="$(basename "$(dirname "$(dirname "$candidate")")")"
    if qt="$("$candidate" -c 'import PySide6; print("PySide6", PySide6.__version__)' 2>/dev/null)" || \
       qt="$("$candidate" -c 'import PySide2; print("PySide2", PySide2.__version__)' 2>/dev/null)"; then
        info "Flame $flame_ver: $qt"
        PYSIDE_OK=1
    else
        echo "    Flame $flame_ver: no usable PySide (or not runnable on this CPU) — skipped"
    fi
done

if [[ -z "$FOUND_ANY" ]]; then
    warn "No Flame Python found under /opt/Autodesk/python; skipping PySide check."
    echo "  The hook uses Flame's own Python at runtime, so this is usually fine."
elif [[ -z "$PYSIDE_OK" ]]; then
    warn "None of the Flame Pythons could import PySide2/PySide6."
    echo "  This is unexpected; Flame normally bundles PySide."
    echo "  The hook will be installed but may not display the editor window."
fi

# ── install file ───────────────────────────────────────────────────────────────
section "Installing to $INSTALL_DIR"

PARENT_DIR="$(dirname "$INSTALL_DIR")"
if [[ -d "$INSTALL_DIR" && ! -w "$INSTALL_DIR" ]] || \
   [[ ! -d "$INSTALL_DIR" && ! -w "$PARENT_DIR" ]]; then
    error "No write access to $INSTALL_DIR — rerun with: sudo bash $0"
fi

mkdir -p "$INSTALL_DIR"
install -m 644 "$HOOK_SRC" "$INSTALL_DIR/$HOOK_NAME"
rm -rf "$INSTALL_DIR/__pycache__"     # don't let Flame load a stale compiled copy
info "Installed: $INSTALL_DIR/$HOOK_NAME"

# ── done ───────────────────────────────────────────────────────────────────────
section "Installation complete"
echo ""
echo "  File installed:"
echo "    $INSTALL_DIR/$HOOK_NAME"
echo ""
echo "  Reload Flame hooks:"
echo "    Flame menu → Python → Reload All Python Hooks"
echo ""
echo "  Usage:"
echo "    MediaHub → right-click any .clip file"
echo "    → OpenClip Editor → Open in OpenClip Editor"
echo ""
echo "  The editor runs inside Flame's own Qt/Python environment."
echo "  No extra packages, no extra Python, works on macOS and Rocky Linux."
echo ""
