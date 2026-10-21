"""
py2app build configuration for OpenClip Editor.

Usage (from this directory):
    pip install py2app
    python setup.py py2app
"""

from setuptools import setup

APP     = ["openclip_editor.py"]
OPTIONS = {
    "argv_emulation": True,
    "iconfile": "openclip_icon.icns",
    "packages": ["tkinter"],
    "plist": {
        "CFBundleName":               "OpenClip Editor",
        "CFBundleDisplayName":        "OpenClip Editor",
        "CFBundleIdentifier":         "com.uc.openclipeditor",
        "CFBundleVersion":            "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "NSHighResolutionCapable":    True,
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName":       "Flame Clip File",
                "CFBundleTypeRole":       "Editor",
                "CFBundleTypeExtensions": ["clip"],
                "LSItemContentTypes":     ["public.xml"],
            }
        ],
    },
}

setup(
    name="OpenClip Editor",
    app=APP,
    data_files=[],
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
