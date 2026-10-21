# OpenClip Editor

Edit Autodesk Flame **Open Clip** (`.clip`) files outside the timeline: timecodes, version names, frame ranges, paths, and OCIO color spaces.

Two ways to run it:

| Platform | How |
|----------|-----|
| **macOS (standalone)** | Build or install the `.app` — double-click `.clip` files or open from the app |
| **Flame (macOS / Rocky Linux)** | Install the Python hook — right-click a `.clip` in MediaHub |

Not affiliated with Autodesk.

## Features

- Edit clip metadata, track info, and per-version feed details
- Adjust start/out timecodes and frame ranges (with path frame tokens kept in sync)
- Remove versions
- **Fix Paths** — batch find/replace with validation and per-path overrides
- OCIO color space picker (parsed from Flame’s config or built-in ACES 2.0 list), grouped by family
- **Show in Finder** / **Open Folder** for the sequence path
- macOS: registered `.clip` handler, correct menu bar name, Apple Event open from Finder

## macOS standalone app

### Requirements on each Mac

Python 3 with **tkinter** (the app bundle does not embed Python):

- [python.org installer](https://www.python.org/downloads/macos/) (includes tkinter), or  
- Homebrew: `brew install python-tk@3.12`

### Build the DMG

```bash
chmod +x build_dmg.sh
./build_dmg.sh
```

Outputs:

- `OpenClip Editor.app`
- `OpenClip Editor.dmg`

Copy the app to `/Applications`. The build bundles a small PyObjC slice so the menu bar shows **OpenClip Editor** instead of **Python**.

### Run from source

```bash
python3 openclip_editor.py /path/to/shot.clip
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
openclip_editor.py      # Standalone tkinter app (macOS)
build_dmg.sh            # Builds .app + DMG
flame_hook/
  openclip_editor.py      # PySide hook for Flame
  install.sh
openclip_icon.icns        # App icon
setup.py                  # Legacy py2app config (optional; DMG uses build_dmg.sh)
```

## License

MIT — see [LICENSE](LICENSE).
