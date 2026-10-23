# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the standalone OpenClip Editor.app — run via build_dmg.sh.
import os
import re

ROOT = os.path.dirname(SPECPATH)
HOOK = os.path.join(ROOT, 'flame_hook', 'openclip_editor.py')
with open(HOOK, encoding='utf-8') as fh:
    VERSION = re.search(r"SCRIPT_VERSION\s*=\s*'v?([\d.]+)'", fh.read()).group(1)

APP_NAME = 'OpenClip Editor'

a = Analysis(
    [os.path.join(SPECPATH, 'openclip_app.py')],
    pathex=[os.path.join(ROOT, 'flame_hook')],
    excludes=['tkinter', 'PySide2'],   # the hook only falls back to PySide2 inside old Flames
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,
    target_arch='universal2',
    codesign_identity=None,            # ad-hoc signature
)
coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME)
app = BUNDLE(
    coll,
    name=f'{APP_NAME}.app',
    icon=os.path.join(ROOT, 'build', 'OpenClipEditor.icns'),
    bundle_identifier='com.uc.openclipeditor',
    version=VERSION,
    info_plist={
        'CFBundleName': APP_NAME,
        'CFBundleDisplayName': APP_NAME,
        'CFBundleVersion': VERSION,
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '13.0',
        'CFBundleDocumentTypes': [{
            'CFBundleTypeName': 'Flame Open Clip',
            'CFBundleTypeRole': 'Editor',
            'CFBundleTypeExtensions': ['clip'],
            'LSItemContentTypes': ['com.autodesk.flame.clip'],
            'LSHandlerRank': 'Owner',
        }],
        # Imported, not exported: the .clip type belongs to Flame, we just open it
        'UTImportedTypeDeclarations': [{
            'UTTypeIdentifier': 'com.autodesk.flame.clip',
            'UTTypeDescription': 'Flame Open Clip',
            'UTTypeConformsTo': ['public.xml'],
            'UTTypeTagSpecification': {'public.filename-extension': ['clip']},
        }],
    },
)
