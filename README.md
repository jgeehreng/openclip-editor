# OpenClip Editor

Edit Autodesk Flame **Open Clip** (`.clip`) files outside the timeline: timecodes, version names, frame ranges, paths, and OCIO color spaces.

Two ways to run it:

| Platform | How |
|----------|-----|
| **macOS (standalone)** | Install `OpenClip Editor.app` from the DMG — double-click `.clip` files or open from the app |
| **Flame (macOS / Rocky Linux)** | Install the Python hook — right-click a `.clip` in MediaHub |

Not affiliated with Autodesk.

## Features

- Edit clip metadata, track info, and per-version feed details
- Adjust start/out timecodes and frame ranges (with path frame tokens kept in sync)
- Remove versions
- **Fix Paths** — batch find/replace with validation and per-path overrides
- OCIO color space picker (parsed from Flame’s config or built-in ACES 2.0 list), grouped by family
- **Show in Finder** / **Open Folder** for the sequence path
- macOS app: opens `.clip` files from Finder (double-click, Open With, drop on the Dock icon), one window per clip

## macOS standalone app

The app is the same editor as the Flame hook, run outside Flame. It's self-contained: Python and Qt are bundled inside, so nothing needs to be installed on each Mac. It's a universal app (Apple Silicon and Intel) and needs macOS 13 or later.

### Install

Open `OpenClip Editor.dmg` and drag the app to **Applications**. The app is ad-hoc signed, not notarized, so the first time you open it on a Mac, right-click it and choose **Open** (or use **System Settings → Privacy & Security → Open Anyway**).

### Build the DMG

You only need these on the Mac you build on: a universal2 [python.org Python](https://www.python.org/downloads/macos/) 3.10+ and internet access for the first run.

```bash
./build_dmg.sh
```

Outputs:

- `dist/OpenClip Editor.app`
- `dist/OpenClip Editor.dmg`

The script creates a build virtualenv in `build/`, installs the pinned tools from `macos/requirements-build.txt`, generates the icon from `OpenClipEditor.iconset`, and runs PyInstaller with `macos/OpenClipEditor.spec`. To use a different Python, set `PYTHON=/path/to/python3`.

### Run from source

```bash
pip install PySide6
python3 flame_hook/openclip_editor.py /path/to/shot.clip
```

## Flame hook (in-app)

Install on a Flame workstation (requires write access to `/opt/Autodesk/shared/python`):

```bash
sudo bash flame_hook/install.sh
```

Then in Flame: **Python → Reload All Python Hooks**.

**MediaHub** → right-click a `.clip` → **OpenClip Editor** → **Open in OpenClip Editor**.

The hook uses **PySide2/PySide6** from Flame’s Python — no extra packages on Linux or macOS Flame hosts.

## Project layout

```
flame_hook/
  openclip_editor.py      # The editor: Flame MediaHub hook and standalone app (PySide2/PySide6)
  install.sh              # Installs the hook on a Flame workstation
macos/
  openclip_app.py         # PyInstaller entry point
  OpenClipEditor.spec     # App bundle config (Info.plist, .clip document type)
  requirements-build.txt  # Pinned build tools
build_dmg.sh              # Builds the .app + DMG into dist/
OpenClipEditor.iconset/   # App icon source (.icns is generated at build time)
```

## License

MIT — see [LICENSE](LICENSE).
