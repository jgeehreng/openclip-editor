"""PyInstaller entry point for the OpenClip Editor macOS app.

The app is the Flame hook's editor run standalone; see flame_hook/openclip_editor.py.
"""
import sys

import openclip_editor

sys.exit(openclip_editor.main())
