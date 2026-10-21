#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# OpenClip Editor — Flame hook installer
# Supports macOS and Rocky Linux (both platforms Flame runs on)
# Run from any location:  bash /path/to/flame_hook/install.sh
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

INSTALL_DIR="/opt/Autodesk/shared/python/openclip_editor"
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

# Flame bundles its own Python — look for it
FLAME_PY=""
for candidate in \
    /opt/Autodesk/python/python3/bin/python3 \
    /opt/Autodesk/python/3.9/bin/python3 \
    /opt/Autodesk/python/3.10/bin/python3 \
    /opt/Autodesk/python/3.11/bin/python3; do
    if [[ -x "$candidate" ]]; then
        FLAME_PY="$candidate"
        break
    fi
done

if [[ -n "$FLAME_PY" ]]; then
    if "$FLAME_PY" -c "import PySide2" 2>/dev/null || \
       "$FLAME_PY" -c "import PySide6" 2>/dev/null; then
        info "PySide found in Flame Python ($FLAME_PY) — good."
    else
        warn "Flame Python found but PySide2/PySide6 not importable from it."
        echo "  This is unexpected; Flame normally bundles PySide."
        echo "  The hook will be installed but may not display the editor window."
    fi
else
    warn "Flame Python not found at standard paths; skipping PySide check."
    echo "  The hook uses Flame's own Python at runtime, so this is usually fine."
fi

# ── install file ───────────────────────────────────────────────────────────────
section "Installing to $INSTALL_DIR"

if [[ ! -d "$INSTALL_DIR" ]]; then
    info "Creating directory..."
    mkdir -p "$INSTALL_DIR"
fi

cp "$HOOK_SRC" "$INSTALL_DIR/$HOOK_NAME"
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
