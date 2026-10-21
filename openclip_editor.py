#!/usr/bin/env python3
"""
OpenClip Editor — Autodesk Flame .clip file editor
Supports editing timecodes, version names, paths; removing versions; fixing paths.
"""

import os
import platform
import re
import subprocess
import sys
import tkinter as tk
from collections import OrderedDict
from io import BytesIO
from tkinter import filedialog, messagebox, ttk
import xml.etree.ElementTree as ET

# On macOS, patch CFBundleName in the main bundle so the Application menu
# (the bold label next to the Apple logo) shows "OpenClip Editor" instead of
# "Python".  PyObjC is bundled inside the .app by build_dmg.sh; if it is not
# available the app still works — only the menu bar label is affected.
# Must run before tk.Tk() is created so Tk/Aqua picks up the patched name.
if platform.system() == "Darwin":
    try:
        from Foundation import NSBundle  # type: ignore[import]
        _info = NSBundle.mainBundle().infoDictionary()
        _info["CFBundleName"] = "OpenClip Editor"
        _info["CFBundleDisplayName"] = "OpenClip Editor"
    except Exception:
        pass


# ─── OCIO utilities ────────────────────────────────────────────────────────────

# Built-in grouped color spaces sourced from Flame 2027 ACES 2.0 config.
# Used when no OCIO config file is found on disk.
_OCIO_BUILTIN_GROUPED = OrderedDict([
    ("ACES", [
        "ACES2065-1", "ACEScg", "ACEScct", "ACEScc", "ADX10", "ADX16",
    ]),
    ("Input / Apple", [
        "Apple Log", "Apple Log 2", "Linear Apple Wide Gamut",
    ]),
    ("Input / ARRI", [
        "ARRI LogC3 (EI800)", "Linear ARRI Wide Gamut 3",
        "ARRI LogC4", "Linear ARRI Wide Gamut 4",
    ]),
    ("Input / Blackmagic", [
        "BMDFilm WideGamut Gen5", "Linear BMD WideGamut Gen5",
        "DaVinci Intermediate WideGamut", "Linear DaVinci WideGamut",
    ]),
    ("Input / Canon", [
        "CanonLog2 CinemaGamut D55", "CanonLog3 CinemaGamut D55",
        "Linear CinemaGamut D55",
    ]),
    ("Input / DJI", [
        "D-Log D-Gamut", "Linear D-Gamut",
    ]),
    ("Input / ITU", [
        "Camera Rec.2100-HLG", "Camera Rec.709",
    ]),
    ("Input / Panasonic", [
        "V-Log V-Gamut", "Linear V-Gamut",
    ]),
    ("Input / RED", [
        "Log3G10 REDWideGamutRGB", "Linear REDWideGamutRGB",
    ]),
    ("Input / Sony", [
        "S-Log3 S-Gamut3", "Linear S-Gamut3",
        "S-Log3 S-Gamut3.Cine", "Linear S-Gamut3.Cine",
        "S-Log3 Venice S-Gamut3", "Linear Venice S-Gamut3",
        "S-Log3 Venice S-Gamut3.Cine", "Linear Venice S-Gamut3.Cine",
    ]),
    ("Utility / Linear", [
        "CIE XYZ-D65 - Scene-referred", "Linear AdobeRGB",
        "Linear P3-D65", "Linear Rec.709 (sRGB)", "Linear Rec.2020",
    ]),
    ("Utility / Texture", [
        "sRGB Encoded Rec.709 (sRGB)", "sRGB Encoded P3-D65", "sRGB Encoded AP1",
        "Gamma 1.8 Encoded Rec.709", "Gamma 2.2 Encoded Rec.709",
        "Gamma 2.4 Encoded Rec.709", "Gamma 2.2 Encoded AdobeRGB",
        "Gamma 2.2 Encoded AP1",
    ]),
    ("Display", [
        "Rec.1886 Rec.709 - Display", "sRGB - Display",
        "Gamma 2.2 Rec.709 - Display", "Display P3 - Display",
        "Display P3 HDR - Display", "AdobeRGB - Display", "P3-D65 - Display",
        "ST2084-P3-D65 - Display", "ST2084-Rec.709 - Display",
        "Rec.2100-PQ - Display", "Rec.2100-HLG - Display",
        "DCDM G2.6-XYZ-D65 - Display", "DCDM ST2084-XYZ-D65 - Display",
        "Rec.601 - Display", "Rec.601 (PAL) - Display", "Rec.2020 - Display",
        "CIE XYZ-D65 - Display-referred", "ProPhotoRGB",
    ]),
    ("Data", [
        "Raw", "3D-Motion", "AO", "Matte", "Motion", "Normals",
        "ObjectID", "Position", "Roughness", "Shadows", "UV", "Z-Depth", "Unknown",
    ]),
])

# Separator prefix used in the tkinter combobox to mark non-selectable headers
_OCIO_SEP = "── "


def _grouped_to_combo_values(grouped):
    """Flatten a grouped OrderedDict into a list with ── Category ── headers."""
    values = []
    for category, names in grouped.items():
        values.append(f"{_OCIO_SEP}{category}")
        values.extend(names)
    return values


def find_ocio_config():
    """Return path to the best available OCIO config, or None."""
    env = os.environ.get('OCIO', '')
    if env and os.path.isfile(env):
        return env
    flame_root = '/opt/Autodesk/colour_mgmt/configs/flame_configs'
    if os.path.isdir(flame_root):
        try:
            for ver in sorted(os.listdir(flame_root), reverse=True):
                ver_dir = os.path.join(flame_root, ver)
                if not os.path.isdir(ver_dir):
                    continue
                for cfg in sorted(os.listdir(ver_dir), reverse=True):
                    candidate = os.path.join(ver_dir, cfg, 'config.ocio')
                    if os.path.isfile(candidate):
                        return candidate
        except OSError:
            pass
    return None


def parse_ocio_grouped(path):
    """Parse an OCIO config and return an OrderedDict of {category: [name, ...]}."""
    groups = OrderedDict()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
        cs_match = re.search(
            r'^colorspaces:\s*$(.*?)(?=^\S|\Z)', text, re.MULTILINE | re.DOTALL)
        if not cs_match:
            return groups
        for block in re.split(r'- !<ColorSpace>', cs_match.group(1))[1:]:
            nm = re.search(r'^\s+name:\s*(.+)$',   block, re.MULTILINE)
            fm = re.search(r'^\s+family:\s*(.+)$', block, re.MULTILINE)
            if not nm:
                continue
            name = nm.group(1).strip().strip('"\'')
            family = fm.group(1).strip().strip('"\'') if fm else ''
            # Cap hierarchy at two levels: "Input/Sony/Legacy" → "Input / Sony"
            parts = [p.strip() for p in family.split('/')][:2]
            category = ' / '.join(parts) if parts and parts[0] else 'Other'
            groups.setdefault(category, []).append(name)
    except Exception:
        pass
    return groups


def parse_ocio_colorspaces(path):
    """Return flat list of colorspace names from an OCIO config (compat wrapper)."""
    groups = parse_ocio_grouped(path)
    return [n for names in groups.values() for n in names]


_OCIO_GROUPED = None   # module-level cache


def get_ocio_grouped():
    """Return cached grouped color space dict, falling back to the built-in list."""
    global _OCIO_GROUPED
    if _OCIO_GROUPED is None:
        path = find_ocio_config()
        parsed = parse_ocio_grouped(path) if path else OrderedDict()
        _OCIO_GROUPED = parsed if parsed else OrderedDict(_OCIO_BUILTIN_GROUPED)
    return _OCIO_GROUPED


def get_ocio_colorspaces():
    """Return flat list of color space names (for backward compatibility)."""
    return [n for names in get_ocio_grouped().values() for n in names]


def open_in_file_manager(path):
    """Open the directory containing *path* in Finder (macOS) or file manager (Linux)."""
    directory = os.path.dirname(path) if not os.path.isdir(path) else path
    if not os.path.isdir(directory):
        return False
    try:
        if platform.system() == 'Darwin':
            subprocess.Popen(['open', directory])
        else:
            subprocess.Popen(['xdg-open', directory])
        return True
    except Exception:
        return False


# ─── Timecode utilities ────────────────────────────────────────────────────────

def ticks_to_tc(nb_ticks, rate):
    """Convert nbTicks (frame count) to (hh, mm, ss, ff) tuple."""
    rate = max(int(rate), 1)
    ff = nb_ticks % rate
    total_sec = nb_ticks // rate
    ss = total_sec % 60
    total_min = total_sec // 60
    mm = total_min % 60
    hh = total_min // 60
    return hh, mm, ss, ff


def tc_to_ticks(hh, mm, ss, ff, rate):
    """Convert HH:MM:SS:FF to nbTicks (frame count)."""
    rate = max(int(rate), 1)
    return hh * rate * 3600 + mm * rate * 60 + ss * rate + ff


def tc_to_str(hh, mm, ss, ff):
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


# ─── Path utilities ────────────────────────────────────────────────────────────

FRAME_RANGE_RE = re.compile(r'\[(\d+)-(\d+)\]')
FRAME_NUMBER_RE = re.compile(r'^(.*?)\.(\d{4,})\.([\w]+)$')


def extract_frame_range(pattern):
    """Return (start, end) ints from a '[start-end]' pattern, or (None, None)."""
    m = FRAME_RANGE_RE.search(pattern or "")
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def validate_path_pattern(pattern):
    """Return True if the directory containing the pattern path exists on disk."""
    if not pattern:
        return False
    return os.path.isdir(os.path.dirname(pattern))


def pattern_from_file(filepath):
    """
    Given a path to one frame file (e.g. /foo/clip.1001.exr), scan the directory
    for all matching frames and return (pattern_path, start_frame, end_frame).
    Returns (None, None, None) if the frame pattern cannot be determined.
    """
    directory = os.path.dirname(filepath)
    filename = os.path.basename(filepath)
    m = FRAME_NUMBER_RE.match(filename)
    if not m:
        return None, None, None

    prefix = m.group(1)
    ext = m.group(3)
    pad_len = len(m.group(2))

    scan_re = re.compile(r'^' + re.escape(prefix) + r'\.(\d{' + str(pad_len) + r',})\.' + re.escape(ext) + r'$')
    try:
        frame_nums = [int(scan_re.match(f).group(1))
                      for f in os.listdir(directory) if scan_re.match(f)]
    except OSError:
        return None, None, None

    if not frame_nums:
        return None, None, None

    frame_nums.sort()
    start, end = frame_nums[0], frame_nums[-1]
    pattern_path = os.path.join(directory, f"{prefix}.[{start}-{end}].{ext}")
    return pattern_path, start, end


# ─── XML helpers ───────────────────────────────────────────────────────────────

def _indent_xml(elem, level=0, indent_char='\t'):
    """Re-indent an ElementTree element in place using tabs, matching Flame's style."""
    pad = '\n' + indent_char * level
    child_pad = '\n' + indent_char * (level + 1)
    if len(elem):
        if not (elem.text and elem.text.strip()):
            elem.text = child_pad
        for child in elem:
            _indent_xml(child, level + 1, indent_char)
        last = elem[-1]
        if not (last.tail and last.tail.strip()):
            last.tail = pad
    else:
        if level and not (elem.tail and elem.tail.strip()):
            elem.tail = pad
    if not (elem.tail and elem.tail.strip()):
        elem.tail = pad if level else '\n'


def write_clip(tree, path):
    """Write ElementTree to file with XML declaration (double-quoted) and tab indentation."""
    root = tree.getroot()
    _indent_xml(root)
    buf = BytesIO()
    tree.write(buf, encoding='UTF-8', xml_declaration=True)
    content = buf.getvalue()
    # Normalize to double-quoted declaration (ElementTree uses single quotes)
    content = content.replace(
        b"<?xml version='1.0' encoding='UTF-8'?>",
        b'<?xml version="1.0" encoding="UTF-8"?>'
    )
    with open(path, 'wb') as fh:
        fh.write(content)


# ─── Main Application ──────────────────────────────────────────────────────────

class OpenClipEditor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("OpenClip Editor")
        self.geometry("1180x740")
        self.minsize(960, 620)

        self.clip_path = None
        self.tree = None        # ET.ElementTree
        self.clip_elem = None   # root <clip> element
        self._dirty = False
        self._current_vuid = None   # vuid of currently selected feed

        self._build_menu()
        self._build_ui()
        self._set_empty_state()

    # ── Menu ──────────────────────────────────────────────────────────────────

    def _build_menu(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open…",      command=self.cmd_open,    accelerator="Cmd+O")
        file_menu.add_command(label="Save",        command=self.cmd_save,    accelerator="Cmd+S")
        file_menu.add_command(label="Save As…",    command=self.cmd_save_as, accelerator="Cmd+Shift+S")
        file_menu.add_separator()
        file_menu.add_command(label="Quit",        command=self._on_quit,    accelerator="Cmd+Q")
        menubar.add_cascade(label="File", menu=file_menu)

        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label="Fix Paths…", command=self.cmd_fix_paths)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        self.config(menu=menubar)
        self.bind_all("<Command-o>", lambda e: self.cmd_open())
        self.bind_all("<Command-s>", lambda e: self.cmd_save())
        self.bind_all("<Command-S>", lambda e: self.cmd_save_as())
        self.protocol("WM_DELETE_WINDOW", self._on_quit)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # File path bar (top)
        path_bar = ttk.Frame(self, padding=(8, 4, 8, 2))
        path_bar.pack(fill=tk.X, side=tk.TOP)
        ttk.Label(path_bar, text="File:").pack(side=tk.LEFT)
        self.path_label = ttk.Label(path_bar, text="No file loaded", foreground="gray")
        self.path_label.pack(side=tk.LEFT, padx=(6, 0))

        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, side=tk.TOP)

        # Status bar must be packed to BOTTOM before the expanding main area
        self._build_status_bar()

        # Main content area
        outer = ttk.Frame(self)
        outer.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

        # Left panel — fixed 280 px wide, does not shrink
        left = ttk.Frame(outer, width=280)
        left.pack(side=tk.LEFT, fill=tk.Y)
        left.pack_propagate(False)

        ttk.Separator(outer, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        # Right panel — fills remaining space
        right = ttk.Frame(outer)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._build_left_panel(left)
        self._build_right_panel(right)

    def _build_left_panel(self, parent):
        parent.columnconfigure(0, weight=1)

        # ── Clip Info ──
        clip_fr = ttk.LabelFrame(parent, text="Clip Info", padding=8)
        clip_fr.grid(row=0, column=0, sticky="new", padx=4, pady=(4, 2))
        clip_fr.columnconfigure(1, weight=1)

        ttk.Label(clip_fr, text="Clip Name:").grid(row=0, column=0, sticky="w")
        self.clip_name_var = tk.StringVar()
        self.clip_name_entry = ttk.Entry(clip_fr, textvariable=self.clip_name_var)
        self.clip_name_entry.grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=2)

        ttk.Label(clip_fr, text="Source Name:").grid(row=1, column=0, sticky="w")
        self.source_name_var = tk.StringVar()
        self.source_name_entry = ttk.Entry(clip_fr, textvariable=self.source_name_var)
        self.source_name_entry.grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=2)

        # ── Track Info ──
        track_fr = ttk.LabelFrame(parent, text="Track", padding=8)
        track_fr.grid(row=1, column=0, sticky="new", padx=4, pady=2)
        track_fr.columnconfigure(1, weight=1)

        ttk.Label(track_fr, text="Track Name:").grid(row=0, column=0, sticky="w")
        self.track_name_var = tk.StringVar()
        self.track_name_entry = ttk.Entry(track_fr, textvariable=self.track_name_var)
        self.track_name_entry.grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=2)

        ttk.Label(track_fr, text="Edit Rate:").grid(row=1, column=0, sticky="w")
        self.edit_rate_label = ttk.Label(track_fr, text="—")
        self.edit_rate_label.grid(row=1, column=1, sticky="w", padx=(6, 0))

        ttk.Label(track_fr, text="Type:").grid(row=2, column=0, sticky="w")
        self.track_type_label = ttk.Label(track_fr, text="—")
        self.track_type_label.grid(row=2, column=1, sticky="w", padx=(6, 0))

        # ── Current Version ──
        cv_fr = ttk.LabelFrame(parent, text="Current Version", padding=8)
        cv_fr.grid(row=2, column=0, sticky="new", padx=4, pady=2)
        cv_fr.columnconfigure(0, weight=1)

        self.current_version_var = tk.StringVar()
        self.current_version_cb = ttk.Combobox(cv_fr, textvariable=self.current_version_var, state="readonly")
        self.current_version_cb.grid(row=0, column=0, sticky="ew")
        self.current_version_cb.bind("<<ComboboxSelected>>", self._on_current_version_changed)

        # ── Metadata ──
        meta_fr = ttk.LabelFrame(parent, text="Metadata", padding=8)
        meta_fr.grid(row=3, column=0, sticky="new", padx=4, pady=2)
        meta_fr.columnconfigure(1, weight=1)

        ttk.Label(meta_fr, text="Flame:").grid(row=0, column=0, sticky="w")
        self.flame_ver_label = ttk.Label(meta_fr, text="—")
        self.flame_ver_label.grid(row=0, column=1, sticky="w", padx=(6, 0))

        ttk.Label(meta_fr, text="Module:").grid(row=1, column=0, sticky="w")
        self.module_label = ttk.Label(meta_fr, text="—")
        self.module_label.grid(row=1, column=1, sticky="w", padx=(6, 0))

        ttk.Label(meta_fr, text="Format Version:").grid(row=2, column=0, sticky="w")
        self.clip_ver_label = ttk.Label(meta_fr, text="—")
        self.clip_ver_label.grid(row=2, column=1, sticky="w", padx=(6, 0))

    def _build_right_panel(self, parent):
        parent.rowconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)

        # ── Versions Table ──
        ver_fr = ttk.LabelFrame(parent, text="Versions", padding=8)
        ver_fr.grid(row=0, column=0, sticky="nsew", padx=4, pady=(4, 2))
        ver_fr.rowconfigure(0, weight=1)
        ver_fr.columnconfigure(0, weight=1)

        cols = ("vuid", "name", "created", "module", "flame_ver")
        self.ver_tree = ttk.Treeview(ver_fr, columns=cols, show="headings", height=6, selectmode="browse")
        self.ver_tree.heading("vuid",      text="Version")
        self.ver_tree.heading("name",      text="Name")
        self.ver_tree.heading("created",   text="Created")
        self.ver_tree.heading("module",    text="Module")
        self.ver_tree.heading("flame_ver", text="Flame")
        self.ver_tree.column("vuid",      width=70,  stretch=False)
        self.ver_tree.column("name",      width=180)
        self.ver_tree.column("created",   width=170, stretch=False)
        self.ver_tree.column("module",    width=80,  stretch=False)
        self.ver_tree.column("flame_ver", width=90,  stretch=False)
        self.ver_tree.grid(row=0, column=0, sticky="nsew")
        self.ver_tree.bind("<<TreeviewSelect>>", self._on_version_select)

        vsb = ttk.Scrollbar(ver_fr, orient=tk.VERTICAL, command=self.ver_tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self.ver_tree.configure(yscrollcommand=vsb.set)

        btn_row = ttk.Frame(ver_fr)
        btn_row.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.remove_ver_btn = ttk.Button(btn_row, text="Remove Selected Version",
                                          command=self.cmd_remove_version)
        self.remove_ver_btn.pack(side=tk.LEFT)

        # ── Feed Details ──
        feed_fr = ttk.LabelFrame(parent, text="Feed Details", padding=8)
        feed_fr.grid(row=1, column=0, sticky="nsew", padx=4, pady=2)
        feed_fr.columnconfigure(1, weight=1)
        self._build_feed_details(feed_fr)

    def _build_feed_details(self, parent):
        row = 0

        # Version Name (editable in the versions table entry)
        ttk.Label(parent, text="Version Name:").grid(row=row, column=0, sticky="w", pady=3)
        vn_frame = ttk.Frame(parent)
        vn_frame.grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)
        vn_frame.columnconfigure(0, weight=1)
        self.ver_name_var = tk.StringVar()
        self.ver_name_entry = ttk.Entry(vn_frame, textvariable=self.ver_name_var)
        self.ver_name_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(vn_frame, text="Apply", command=self._apply_version_name).grid(row=0, column=1, padx=(4, 0))
        row += 1

        ttk.Separator(parent, orient=tk.HORIZONTAL).grid(row=row, column=0, columnspan=3, sticky="ew", pady=4)
        row += 1

        # Start Timecode
        ttk.Label(parent, text="Start TC:").grid(row=row, column=0, sticky="w", pady=3)
        tc_frame = ttk.Frame(parent)
        tc_frame.grid(row=row, column=1, sticky="w", pady=3)
        self.tc_hh = ttk.Spinbox(tc_frame, width=3, from_=0, to=23, format="%02.0f", wrap=True)
        self.tc_hh.pack(side=tk.LEFT)
        ttk.Label(tc_frame, text=":").pack(side=tk.LEFT)
        self.tc_mm = ttk.Spinbox(tc_frame, width=3, from_=0, to=59, format="%02.0f", wrap=True)
        self.tc_mm.pack(side=tk.LEFT)
        ttk.Label(tc_frame, text=":").pack(side=tk.LEFT)
        self.tc_ss = ttk.Spinbox(tc_frame, width=3, from_=0, to=59, format="%02.0f", wrap=True)
        self.tc_ss.pack(side=tk.LEFT)
        ttk.Label(tc_frame, text=":").pack(side=tk.LEFT)
        self.tc_ff = ttk.Spinbox(tc_frame, width=3, from_=0, to=999, format="%02.0f", wrap=True)
        self.tc_ff.pack(side=tk.LEFT)
        self.tc_info_label = ttk.Label(tc_frame, text="", foreground="gray")
        self.tc_info_label.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(tc_frame, text="Apply", command=self._apply_timecode).pack(side=tk.LEFT, padx=(10, 0))
        row += 1

        # Out Timecode (read-only computed)
        ttk.Label(parent, text="Out TC:").grid(row=row, column=0, sticky="w")
        self.out_tc_label = ttk.Label(parent, text="—", foreground="gray")
        self.out_tc_label.grid(row=row, column=1, sticky="w")
        row += 1

        ttk.Separator(parent, orient=tk.HORIZONTAL).grid(row=row, column=0, columnspan=3, sticky="ew", pady=4)
        row += 1

        # File Path
        ttk.Label(parent, text="Path:").grid(row=row, column=0, sticky="w", pady=3)
        path_frame = ttk.Frame(parent)
        path_frame.grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)
        path_frame.columnconfigure(0, weight=1)
        self.feed_path_var = tk.StringVar()
        self.feed_path_entry = ttk.Entry(path_frame, textvariable=self.feed_path_var)
        self.feed_path_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(path_frame, text="Apply", command=self._apply_feed_path).grid(row=0, column=1, padx=(4, 0))
        _finder_label = "Show in Finder" if platform.system() == "Darwin" else "Open Folder"
        ttk.Button(path_frame, text=_finder_label, command=self._show_in_finder).grid(row=0, column=2, padx=(2, 0))
        row += 1

        # Start Frame
        ttk.Label(parent, text="Start Frame:").grid(row=row, column=0, sticky="w", pady=3)
        sf_frame = ttk.Frame(parent)
        sf_frame.grid(row=row, column=1, sticky="w", pady=3)
        self.start_frame_var = tk.StringVar()
        self.start_frame_entry = ttk.Entry(sf_frame, textvariable=self.start_frame_var, width=10)
        self.start_frame_entry.pack(side=tk.LEFT)
        ttk.Button(sf_frame, text="Apply", command=self._apply_start_frame).pack(side=tk.LEFT, padx=(4, 0))
        row += 1

        # End Frame (editable — updates path pattern and <duration>)
        ttk.Label(parent, text="End Frame:").grid(row=row, column=0, sticky="w", pady=3)
        ef_frame = ttk.Frame(parent)
        ef_frame.grid(row=row, column=1, columnspan=2, sticky="w", pady=3)
        self.end_frame_var = tk.StringVar()
        self.end_frame_entry = ttk.Entry(ef_frame, textvariable=self.end_frame_var, width=10)
        self.end_frame_entry.pack(side=tk.LEFT)
        ttk.Button(ef_frame, text="Apply",
                   command=self._apply_end_frame).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(ef_frame, text="Apply to All Versions",
                   command=self._apply_end_frame_all).pack(side=tk.LEFT, padx=(8, 0))
        row += 1

        # Duration (read-only computed)
        ttk.Label(parent, text="Duration:").grid(row=row, column=0, sticky="w")
        self.frames_label = ttk.Label(parent, text="—", foreground="gray")
        self.frames_label.grid(row=row, column=1, sticky="w")
        row += 1

        ttk.Separator(parent, orient=tk.HORIZONTAL).grid(row=row, column=0, columnspan=3, sticky="ew", pady=4)
        row += 1

        # Resolution (read-only)
        ttk.Label(parent, text="Resolution:").grid(row=row, column=0, sticky="w")
        self.res_label = ttk.Label(parent, text="—")
        self.res_label.grid(row=row, column=1, sticky="w")
        row += 1

        # Color Space (editable dropdown backed by OCIO config)
        ttk.Label(parent, text="Color Space:").grid(row=row, column=0, sticky="w", pady=3)
        cs_frame = ttk.Frame(parent)
        cs_frame.grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)
        cs_frame.columnconfigure(0, weight=1)
        self.color_var = tk.StringVar()
        self.color_combo = ttk.Combobox(cs_frame, textvariable=self.color_var)
        self.color_combo['values'] = _grouped_to_combo_values(get_ocio_grouped())
        self.color_combo.grid(row=0, column=0, sticky="ew")
        ttk.Button(cs_frame, text="Apply", command=self._apply_color_space).grid(row=0, column=1, padx=(4, 0))
        ttk.Button(cs_frame, text="…", width=2, command=self._browse_ocio_config).grid(row=0, column=2, padx=(2, 0))
        self.color_entry = self.color_combo   # alias so _set_widgets_enabled still works
        row += 1

        # File format (read-only)
        ttk.Label(parent, text="Format:").grid(row=row, column=0, sticky="w")
        self.format_label = ttk.Label(parent, text="—")
        self.format_label.grid(row=row, column=1, sticky="w")

    def _build_status_bar(self):
        # Pack bottom-up: bar first, then separator sits on top of it
        status_bar = ttk.Frame(self, padding=(8, 3))
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, side=tk.BOTTOM)

        self.save_btn = ttk.Button(status_bar, text="Save", command=self.cmd_save)
        self.save_btn.pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(status_bar, text="Fix Paths…", command=self.cmd_fix_paths).pack(side=tk.RIGHT, padx=(4, 0))

        self.status_label = ttk.Label(status_bar, text="No file loaded")
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

    # ── State management ──────────────────────────────────────────────────────

    def _set_empty_state(self):
        self._current_vuid = None
        for item in self.ver_tree.get_children():
            self.ver_tree.delete(item)
        self._clear_feed_details()
        self._set_widgets_enabled(False)
        self.status_label.config(text="No file loaded")
        self.path_label.config(text="No file loaded", foreground="gray")
        self.title("OpenClip Editor")

    def _set_widgets_enabled(self, enabled):
        state_normal = "normal" if enabled else "disabled"
        state_readonly = "readonly" if enabled else "disabled"
        for w in [self.clip_name_entry, self.source_name_entry,
                  self.track_name_entry, self.remove_ver_btn, self.save_btn,
                  self.feed_path_entry, self.color_entry, self.start_frame_entry,
                  self.end_frame_entry, self.ver_name_entry]:
            w.config(state=state_normal)
        self.current_version_cb.config(state=state_readonly)
        for w in [self.tc_hh, self.tc_mm, self.tc_ss, self.tc_ff]:
            w.config(state=state_normal)

    def _clear_feed_details(self):
        self.ver_name_var.set("")
        self.tc_hh.set("00")
        self.tc_mm.set("00")
        self.tc_ss.set("00")
        self.tc_ff.set("00")
        self.tc_info_label.config(text="")
        self.out_tc_label.config(text="—")
        self.feed_path_var.set("")
        self.frames_label.config(text="—")
        self.start_frame_var.set("")
        self.end_frame_var.set("")
        self.res_label.config(text="—")
        self.color_var.set("")
        self.format_label.config(text="—")

    # ── Populate ──────────────────────────────────────────────────────────────

    def _populate_from_xml(self):
        self._set_widgets_enabled(True)
        clip = self.clip_elem

        # Clip XML version attribute
        self.clip_ver_label.config(text=clip.get("version", "—"))

        # Clip info fields
        self.clip_name_var.set(self._get_text(clip, "name") or "")
        self.source_name_var.set(self._get_text(clip, "sourceName") or "")

        # Clip-level userData
        ud = clip.find("userData")
        if ud is not None:
            self.flame_ver_label.config(text=self._get_text(ud, "appVersion") or "—")
            self.module_label.config(text=self._get_text(ud, "module") or "—")

        # Track
        track = self._get_track()
        if track is not None:
            self.track_name_var.set(self._get_text(track, "name") or "")
            er = track.find("editRate")
            if er is not None:
                num = int(er.findtext("numerator") or 24000)
                den = int(er.findtext("denominator") or 1001)
                fps = num / den
                self.edit_rate_label.config(text=f"{fps:.3f} fps  ({num}/{den})")
            self.track_type_label.config(text=self._get_text(track, "trackType") or "—")

        # Versions table + combobox
        self._populate_versions_table()
        versions_elem = clip.find("versions")
        cur_ver = versions_elem.get("currentVersion") if versions_elem is not None else None
        vuids = [v.get("uid") for v in (versions_elem if versions_elem is not None else []) if v.tag == "version"]
        self.current_version_cb["values"] = vuids
        resolved = cur_ver if cur_ver in vuids else (vuids[-1] if vuids else "")
        self.current_version_var.set(resolved)

        # Select in table + populate details
        if resolved:
            self._select_version_in_table(resolved)

        n = len(vuids)
        fname = os.path.basename(self.clip_path)
        self.status_label.config(text=f"Loaded {fname} — {n} version{'s' if n != 1 else ''}")
        self.title(f"OpenClip Editor — {fname}")

    def _populate_versions_table(self):
        for item in self.ver_tree.get_children():
            self.ver_tree.delete(item)

        versions_elem = self.clip_elem.find("versions") if self.clip_elem is not None else None
        if versions_elem is None:
            return

        for ver in versions_elem:
            if ver.tag != "version":
                continue
            vuid      = ver.get("uid", "")
            name      = self._get_text(ver, "name") or ""
            created   = self._get_text(ver, "creationDate") or ""
            ud        = ver.find("userData")
            module    = self._get_text(ud, "module")    if ud is not None else ""
            flame_ver = self._get_text(ud, "appVersion") if ud is not None else ""
            self.ver_tree.insert("", "end", iid=vuid,
                                  values=(vuid, name, created, module, flame_ver))

    def _select_version_in_table(self, vuid):
        if vuid and self.ver_tree.exists(vuid):
            self.ver_tree.selection_set(vuid)
            self.ver_tree.see(vuid)
        self._populate_feed_details(vuid)

    def _populate_feed_details(self, vuid):
        self._current_vuid = vuid
        self._clear_feed_details()

        if not vuid:
            return

        # Version name from <versions> section
        versions_elem = self.clip_elem.find("versions")
        if versions_elem is not None:
            for ver in versions_elem:
                if ver.get("uid") == vuid:
                    self.ver_name_var.set(self._get_text(ver, "name") or "")
                    break

        feed = self._get_feed(vuid)
        if feed is None:
            return

        # Timecode
        tc_elem = feed.find("startTimecode")
        if tc_elem is not None:
            rate = int(tc_elem.findtext("rate") or 24)
            nb   = int(tc_elem.findtext("nbTicks") or 0)
            drop = tc_elem.findtext("dropMode") or "NDF"
            hh, mm, ss, ff = ticks_to_tc(nb, rate)
            self.tc_hh.set(f"{hh:02d}")
            self.tc_mm.set(f"{mm:02d}")
            self.tc_ss.set(f"{ss:02d}")
            self.tc_ff.set(f"{ff:02d}")
            self.tc_info_label.config(text=f"{drop}  {rate}fps")

            # Out TC: startTC + duration
            duration = self._get_feed_duration(feed)
            if duration is not None:
                oh, om, os_, of_ = ticks_to_tc(nb + duration, rate)
                self.out_tc_label.config(
                    text=f"{tc_to_str(oh, om, os_, of_)}  ({duration} frames)")
            else:
                self.out_tc_label.config(text="—")

        # Span path
        span = feed.find("spans/span")
        if span is not None:
            path_elem = span.find("path")
            path_text = (path_elem.text or "") if path_elem is not None else ""
            self.feed_path_var.set(path_text)

            s_fr, e_fr = extract_frame_range(path_text)
            if s_fr is not None and e_fr is not None:
                self.end_frame_var.set(str(e_fr))
                self.frames_label.config(text=f"{e_fr - s_fr + 1} frames  ({s_fr}–{e_fr})")

        # Start frame — use explicit element, fall back to path pattern range start
        sf = feed.findtext("startFrame")
        if not sf:
            span = feed.find("spans/span")
            if span is not None:
                path_elem = span.find("path")
                s_fr, _ = extract_frame_range(path_elem.text or "" if path_elem is not None else "")
                if s_fr is not None:
                    sf = str(s_fr)
        self.start_frame_var.set(sf or "")

        # Storage format
        sf_elem = feed.find("storageFormat")
        if sf_elem is not None:
            w   = sf_elem.findtext("width")  or "?"
            h   = sf_elem.findtext("height") or "?"
            self.res_label.config(text=f"{w} × {h}")

            cs = sf_elem.findtext("colourSpace") or ""
            self.color_var.set(cs)

            fmt   = sf_elem.findtext("fileFormat") or ""
            comp  = sf_elem.findtext("compression") or ""
            depth = sf_elem.findtext("channelsDepth") or ""
            enc   = sf_elem.findtext("channelsEncoding") or ""
            parts = []
            if fmt:  parts.append(fmt.upper())
            if comp: parts.append(comp)
            fmt_str = " / ".join(parts) or "—"
            if depth:
                fmt_str += f"   {depth}-bit {enc}".rstrip()
            self.format_label.config(text=fmt_str)

    def _get_feed_duration(self, feed):
        """Return duration in frames for a feed, from explicit <duration> or path pattern."""
        span = feed.find("spans/span")
        if span is None:
            return None
        dur_text = span.findtext("duration")
        if dur_text:
            return int(dur_text)
        path_elem = span.find("path")
        if path_elem is not None:
            s_fr, e_fr = extract_frame_range(path_elem.text or "")
            if s_fr is not None and e_fr is not None:
                return e_fr - s_fr + 1
        return None

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_version_select(self, event=None):
        sel = self.ver_tree.selection()
        if sel:
            self._populate_feed_details(sel[0])

    def _on_current_version_changed(self, event=None):
        vuid = self.current_version_var.get()
        track = self._get_track()
        if track is not None:
            feeds = track.find("feeds")
            if feeds is not None:
                feeds.set("currentVersion", vuid)
        versions_elem = self.clip_elem.find("versions")
        if versions_elem is not None:
            versions_elem.set("currentVersion", vuid)
        self._mark_dirty()
        self._select_version_in_table(vuid)

    # ── Apply helpers ─────────────────────────────────────────────────────────

    def _apply_version_name(self):
        if not self._current_vuid:
            return
        new_name = self.ver_name_var.get().strip()
        versions_elem = self.clip_elem.find("versions")
        if versions_elem is not None:
            for ver in versions_elem:
                if ver.get("uid") == self._current_vuid:
                    name_elem = ver.find("name")
                    if name_elem is not None:
                        name_elem.text = new_name
                    break
        self._populate_versions_table()
        self._mark_dirty()
        self._set_status(f"Version name updated for {self._current_vuid}")
        # Re-select
        self.ver_tree.selection_set(self._current_vuid)

    def _apply_timecode(self):
        if not self._current_vuid:
            return
        feed = self._get_feed(self._current_vuid)
        if feed is None:
            return
        try:
            hh = int(self.tc_hh.get())
            mm = int(self.tc_mm.get())
            ss = int(self.tc_ss.get())
            ff = int(self.tc_ff.get())
        except ValueError:
            messagebox.showerror("Invalid Timecode",
                                  "Please enter valid integer values for HH:MM:SS:FF.")
            return

        tc_targets = [feed.find("startTimecode")]
        ud = feed.find("userData")
        if ud is not None:
            rec = ud.find("recordTimecode")
            if rec is not None:
                tc_targets.append(rec)

        for tc_elem in tc_targets:
            if tc_elem is None:
                continue
            rate = int(tc_elem.findtext("rate") or 24)
            nb   = tc_to_ticks(hh, mm, ss, ff, rate)
            nb_e = tc_elem.find("nbTicks")
            if nb_e is not None:
                nb_e.text = str(nb)
            if tc_elem.get("label"):
                tc_elem.set("label", tc_to_str(hh, mm, ss, ff))

        self._mark_dirty()
        self._populate_feed_details(self._current_vuid)
        self._set_status(f"Timecode updated for {self._current_vuid}")

    def _apply_feed_path(self):
        if not self._current_vuid:
            return
        feed = self._get_feed(self._current_vuid)
        if feed is None:
            return
        new_path = self.feed_path_var.get().strip()
        span = feed.find("spans/span")
        if span is not None:
            path_elem = span.find("path")
            if path_elem is not None:
                path_elem.text = new_path
        self._mark_dirty()
        self._populate_feed_details(self._current_vuid)
        self._set_status(f"Path updated for {self._current_vuid}")

    def _show_in_finder(self):
        path = self.feed_path_var.get().strip()
        if not path:
            messagebox.showwarning("No Path", "No path is set for this feed.")
            return
        if not open_in_file_manager(path):
            messagebox.showwarning(
                "Directory Not Found",
                f"Directory does not exist:\n{os.path.dirname(path)}")

    def _apply_color_space(self):
        if not self._current_vuid:
            return
        val = self.color_var.get().strip()
        if val.startswith(_OCIO_SEP):
            return  # user clicked a category header, not a color space
        feed = self._get_feed(self._current_vuid)
        if feed is None:
            return
        sf_elem = feed.find("storageFormat")
        if sf_elem is not None:
            cs_elem = sf_elem.find("colourSpace")
            if cs_elem is not None:
                cs_elem.text = val
        self._mark_dirty()
        self._set_status(f"Color space updated for {self._current_vuid}")

    def _browse_ocio_config(self):
        """Let the user pick a .ocio file and reload the color space dropdown from it."""
        path = filedialog.askopenfilename(
            title="Select OCIO Config",
            filetypes=[("OCIO Config", "*.ocio"), ("All Files", "*.*")],
        )
        if not path:
            return
        global _OCIO_GROUPED
        _OCIO_GROUPED = parse_ocio_grouped(path)
        self.color_combo['values'] = _grouped_to_combo_values(_OCIO_GROUPED)
        total = sum(len(v) for v in _OCIO_GROUPED.values())
        self._set_status(f"Loaded {total} color spaces from {os.path.basename(path)}")

    def _apply_start_frame(self):
        if not self._current_vuid:
            return
        feed = self._get_feed(self._current_vuid)
        if feed is None:
            return
        val = self.start_frame_var.get().strip()
        sf_elem = feed.find("startFrame")
        if sf_elem is not None:
            sf_elem.text = val
        elif val:
            sf_elem = ET.SubElement(feed, "startFrame")
            sf_elem.text = val
        self._mark_dirty()
        self._set_status(f"Start frame updated for {self._current_vuid}")

    def _apply_end_frame(self):
        if not self._current_vuid:
            return
        val = self.end_frame_var.get().strip()
        if not val.isdigit():
            messagebox.showerror("Invalid Value", "End frame must be a whole number.")
            return
        self._set_feed_end_frame(self._current_vuid, int(val))
        self._populate_feed_details(self._current_vuid)
        self._set_status(f"End frame updated for {self._current_vuid}")

    def _apply_end_frame_all(self):
        val = self.end_frame_var.get().strip()
        if not val.isdigit():
            messagebox.showerror("Invalid Value", "Enter an end frame number first, then click Apply to All.")
            return
        end = int(val)
        feeds = self._get_all_feeds()
        if not feeds:
            return
        if not messagebox.askyesno(
                "Apply to All Versions",
                f"Set end frame to {end} for all {len(feeds)} version(s)?\n\n"
                "This updates each feed's path pattern and <duration> where present."):
            return
        for feed in feeds:
            self._set_feed_end_frame(feed.get("vuid", ""), end)
        self._mark_dirty()
        self._populate_feed_details(self._current_vuid)
        self._set_status(f"End frame set to {end} across all {len(feeds)} version(s)")

    def _set_feed_end_frame(self, vuid, end_frame):
        """Update a single feed's path pattern end frame and <duration> if present."""
        feed = self._get_feed(vuid)
        if feed is None:
            return
        span = feed.find("spans/span")
        if span is None:
            return
        path_elem = span.find("path")
        if path_elem is not None and path_elem.text:
            # Replace [start-oldEnd] with [start-newEnd] in the pattern
            path_elem.text = FRAME_RANGE_RE.sub(
                lambda m: f"[{m.group(1)}-{end_frame}]",
                path_elem.text
            )
            # Recompute duration from the updated pattern
            s_fr, e_fr = extract_frame_range(path_elem.text)
            if s_fr is not None:
                new_duration = e_fr - s_fr + 1
                dur_elem = span.find("duration")
                if dur_elem is not None:
                    dur_elem.text = str(new_duration)
        self._mark_dirty()

    def _apply_clip_meta(self):
        """Push editable left-panel fields back into the XML tree before saving."""
        self._set_text(self.clip_elem, "name", self.clip_name_var.get())
        self._set_text(self.clip_elem, "sourceName", self.source_name_var.get())
        track = self._get_track()
        if track is not None:
            self._set_text(track, "name", self.track_name_var.get())

    # ── Commands ──────────────────────────────────────────────────────────────

    def cmd_open(self):
        path = filedialog.askopenfilename(
            title="Open Clip File",
            filetypes=[("Flame Clip Files", "*.clip"), ("All Files", "*.*")],
        )
        if path:
            self._load_file(path)

    def _load_file(self, path):
        try:
            tree = ET.parse(path)
        except ET.ParseError as e:
            messagebox.showerror("Parse Error", f"Could not parse clip file:\n{e}")
            return
        except OSError as e:
            messagebox.showerror("File Error", f"Could not open file:\n{e}")
            return

        self.tree = tree
        self.clip_elem = tree.getroot()
        self.clip_path = path
        self._dirty = False
        self.path_label.config(text=path, foreground="black")
        self._populate_from_xml()

    def cmd_save(self):
        if self.clip_path is None:
            self.cmd_save_as()
            return
        self._apply_clip_meta()
        try:
            write_clip(self.tree, self.clip_path)
        except OSError as e:
            messagebox.showerror("Save Error", f"Could not save file:\n{e}")
            return
        self._dirty = False
        fname = os.path.basename(self.clip_path)
        self.title(f"OpenClip Editor — {fname}")
        self._set_status(f"Saved: {self.clip_path}")

    def cmd_save_as(self):
        init_file = os.path.basename(self.clip_path) if self.clip_path else "clip.clip"
        path = filedialog.asksaveasfilename(
            title="Save Clip File As",
            defaultextension=".clip",
            filetypes=[("Flame Clip Files", "*.clip"), ("All Files", "*.*")],
            initialfile=init_file,
        )
        if not path:
            return
        self._apply_clip_meta()
        try:
            write_clip(self.tree, path)
        except OSError as e:
            messagebox.showerror("Save Error", f"Could not save file:\n{e}")
            return
        self.clip_path = path
        self.path_label.config(text=path, foreground="black")
        self._dirty = False
        fname = os.path.basename(path)
        self.title(f"OpenClip Editor — {fname}")
        self._set_status(f"Saved: {path}")

    def cmd_remove_version(self):
        sel = self.ver_tree.selection()
        if not sel:
            messagebox.showwarning("No Selection", "Please select a version to remove.")
            return
        vuid = sel[0]

        # Get display name for confirmation
        versions_elem = self.clip_elem.find("versions")
        ver_name = vuid
        for v in (versions_elem if versions_elem is not None else []):
            if v.get("uid") == vuid:
                ver_name = self._get_text(v, "name") or vuid
                break

        if not messagebox.askyesno(
                "Remove Version",
                f"Remove version '{ver_name}' ({vuid})?\n\nThis will also remove its feed data."):
            return

        # Remove from <versions>
        if versions_elem is not None:
            for v in list(versions_elem):
                if v.get("uid") == vuid:
                    versions_elem.remove(v)
                    break

        # Remove from <feeds>
        track = self._get_track()
        if track is not None:
            feeds = track.find("feeds")
            if feeds is not None:
                for f in list(feeds):
                    if f.get("vuid") == vuid:
                        feeds.remove(f)
                        break

        # Update currentVersion if the removed one was current
        cur = self.current_version_var.get()
        remaining = [v.get("uid") for v in (versions_elem if versions_elem is not None else []) if v.tag == "version"]
        new_cur = cur if cur in remaining else (remaining[-1] if remaining else "")

        if versions_elem is not None:
            versions_elem.set("currentVersion", new_cur)
        if track is not None:
            feeds = track.find("feeds")
            if feeds is not None:
                feeds.set("currentVersion", new_cur)

        self._mark_dirty()
        self._populate_versions_table()
        self.current_version_cb["values"] = remaining
        self.current_version_var.set(new_cur)
        if new_cur:
            self._select_version_in_table(new_cur)
        else:
            self._clear_feed_details()

        self._set_status(f"Removed version {vuid}")

    def cmd_fix_paths(self):
        if self.clip_elem is None:
            messagebox.showinfo("No File", "Please open a .clip file first.")
            return
        FixPathsDialog(self)

    def _on_quit(self):
        if self._dirty:
            ans = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes. Save before quitting?")
            if ans is None:
                return
            if ans:
                self.cmd_save()
        self.destroy()

    # ── XML access helpers ────────────────────────────────────────────────────

    def _get_track(self):
        if self.clip_elem is None:
            return None
        tracks = self.clip_elem.find("tracks")
        return tracks.find("track") if tracks is not None else None

    def _get_feed(self, vuid):
        track = self._get_track()
        if track is None:
            return None
        feeds = track.find("feeds")
        if feeds is None:
            return None
        for f in feeds:
            if f.get("vuid") == vuid:
                return f
        return None

    def _get_all_feeds(self):
        track = self._get_track()
        if track is None:
            return []
        feeds = track.find("feeds")
        return list(feeds) if feeds is not None else []

    def _get_text(self, elem, tag):
        if elem is None:
            return None
        child = elem.find(tag)
        return child.text if child is not None else None

    def _set_text(self, elem, tag, value):
        if elem is None:
            return
        child = elem.find(tag)
        if child is not None:
            child.text = value

    # ── Dirty / status ────────────────────────────────────────────────────────

    def _mark_dirty(self):
        if not self._dirty:
            self._dirty = True
            fname = os.path.basename(self.clip_path) if self.clip_path else "untitled"
            self.title(f"OpenClip Editor — {fname} •")

    def _set_status(self, msg):
        self.status_label.config(text=msg)
        def _restore():
            if self.clip_path:
                n = len(self.current_version_cb["values"])
                fname = os.path.basename(self.clip_path)
                self.status_label.config(
                    text=f"Loaded {fname} — {n} version{'s' if n != 1 else ''}")
        self.after(4000, _restore)


# ─── Fix Paths Dialog ──────────────────────────────────────────────────────────

class FixPathsDialog(tk.Toplevel):
    def __init__(self, editor: OpenClipEditor):
        super().__init__(editor)
        self.editor = editor
        self.title("Fix Paths")
        self.geometry("900x620")
        self.resizable(True, True)
        self.transient(editor)
        self.grab_set()
        self._build_ui()
        self._recheck_all()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # ── Batch Prefix Replacement ──
        batch_fr = ttk.LabelFrame(self, text="Batch Prefix Replacement", padding=10)
        batch_fr.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        batch_fr.columnconfigure(1, weight=1)

        ttk.Label(batch_fr, text="Find:").grid(row=0, column=0, sticky="w")
        self.find_var = tk.StringVar()
        ttk.Entry(batch_fr, textvariable=self.find_var).grid(
            row=0, column=1, sticky="ew", padx=(6, 0), pady=2)

        ttk.Label(batch_fr, text="Replace:").grid(row=1, column=0, sticky="w")
        self.replace_var = tk.StringVar()
        ttk.Entry(batch_fr, textvariable=self.replace_var).grid(
            row=1, column=1, sticky="ew", padx=(6, 0), pady=2)

        scope_fr = ttk.Frame(batch_fr)
        scope_fr.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 2))
        self.scope_var = tk.StringVar(value="all")
        ttk.Radiobutton(scope_fr, text="All versions",
                         variable=self.scope_var, value="all").pack(side=tk.LEFT)
        ttk.Radiobutton(scope_fr, text="Selected version only",
                         variable=self.scope_var, value="selected").pack(
            side=tk.LEFT, padx=(14, 0))

        btn_fr = ttk.Frame(batch_fr)
        btn_fr.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(btn_fr, text="Preview",         command=self._preview_replace).pack(side=tk.LEFT)
        ttk.Button(btn_fr, text="Apply to Feeds",  command=self._apply_replace).pack(
            side=tk.LEFT, padx=(8, 0))

        # ── Validation Table ──
        val_fr = ttk.LabelFrame(self, text="Path Validation", padding=8)
        val_fr.grid(row=1, column=0, sticky="nsew", padx=10, pady=4)
        val_fr.rowconfigure(0, weight=1)
        val_fr.columnconfigure(0, weight=1)

        cols = ("version", "type", "path", "status")
        self.val_tree = ttk.Treeview(val_fr, columns=cols, show="headings")
        self.val_tree.heading("version", text="Version")
        self.val_tree.heading("type",    text="Type")
        self.val_tree.heading("path",    text="Path")
        self.val_tree.heading("status",  text="Status")
        self.val_tree.column("version", width=70,  stretch=False)
        self.val_tree.column("type",    width=70,  stretch=False)
        self.val_tree.column("path",    width=600)
        self.val_tree.column("status",  width=130, stretch=False)
        self.val_tree.grid(row=0, column=0, sticky="nsew")

        vsb = ttk.Scrollbar(val_fr, orient=tk.VERTICAL, command=self.val_tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self.val_tree.configure(yscrollcommand=vsb.set)

        self.val_tree.tag_configure("ok",      foreground="green")
        self.val_tree.tag_configure("missing", foreground="red")
        self.val_tree.tag_configure("batch_ok",      foreground="#888")
        self.val_tree.tag_configure("batch_missing", foreground="#c06000")

        recheck_btn = ttk.Button(val_fr, text="Recheck All", command=self._recheck_all)
        recheck_btn.grid(row=1, column=0, sticky="e", pady=(4, 0))

        # ── Individual Override ──
        ind_fr = ttk.LabelFrame(self, text="Individual Path Override", padding=10)
        ind_fr.grid(row=2, column=0, sticky="ew", padx=10, pady=4)
        ind_fr.columnconfigure(1, weight=1)

        ttk.Label(ind_fr, text="Version:").grid(row=0, column=0, sticky="w")
        self.ind_ver_var = tk.StringVar()
        feeds = self.editor._get_all_feeds()
        vuids = [f.get("vuid") for f in feeds if f.get("vuid")]
        self.ind_ver_cb = ttk.Combobox(ind_fr, textvariable=self.ind_ver_var,
                                        values=vuids, state="readonly", width=10)
        self.ind_ver_cb.grid(row=0, column=1, sticky="w", padx=(6, 0))
        if vuids:
            self.ind_ver_cb.current(0)

        ttk.Label(ind_fr, text="Path:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.ind_path_var = tk.StringVar()
        ttk.Entry(ind_fr, textvariable=self.ind_path_var).grid(
            row=1, column=1, sticky="ew", padx=(6, 0), pady=(6, 0))
        ttk.Button(ind_fr, text="Browse…", command=self._browse_frame).grid(
            row=1, column=2, padx=(4, 0), pady=(6, 0))

        ttk.Button(ind_fr, text="Apply to Selected",
                    command=self._apply_individual).grid(
            row=2, column=1, sticky="w", padx=(6, 0), pady=(6, 0))

        # ── Close ──
        close_fr = ttk.Frame(self, padding=(0, 0, 10, 8))
        close_fr.grid(row=3, column=0, sticky="e")
        ttk.Button(close_fr, text="Close", command=self.destroy).pack()

    # ── Validation ────────────────────────────────────────────────────────────

    def _iter_all_paths(self):
        """Yield (vuid, path_text, kind) where kind is 'feed' or 'batch'."""
        for feed in self.editor._get_all_feeds():
            vuid = feed.get("vuid", "")
            span = feed.find("spans/span")
            if span is not None:
                path_elem = span.find("path")
                if path_elem is not None and path_elem.text:
                    yield vuid, path_elem.text.strip(), "feed"

        versions_elem = self.editor.clip_elem.find("versions")
        if versions_elem is not None:
            for ver in versions_elem:
                if ver.tag != "version":
                    continue
                vuid = ver.get("uid", "")
                ud   = ver.find("userData")
                if ud is not None:
                    bs = ud.find("batchSetup")
                    if bs is not None and bs.text:
                        yield vuid, bs.text.strip(), "batch"

    def _recheck_all(self):
        for item in self.val_tree.get_children():
            self.val_tree.delete(item)

        for vuid, path, kind in self._iter_all_paths():
            if kind == "batch":
                exists = os.path.exists(path)
                tag    = "batch_ok" if exists else "batch_missing"
                status = "✓ OK" if exists else "✗ MISSING"
            else:
                exists = os.path.isdir(os.path.dirname(path))
                tag    = "ok"      if exists else "missing"
                status = "✓ OK" if exists else "✗ MISSING"

            self.val_tree.insert("", "end",
                                  values=(vuid, kind, path, status),
                                  tags=(tag,))

    # ── Batch replacement ─────────────────────────────────────────────────────

    def _preview_replace(self):
        find    = self.find_var.get()
        replace = self.replace_var.get()
        if not find:
            messagebox.showwarning("Empty Find", "Please enter a string to find.", parent=self)
            return

        lines = []
        for vuid, path, kind in self._iter_all_paths():
            if kind != "feed":
                continue
            if find in path:
                new_path = path.replace(find, replace)
                lines.append(f"[{vuid}]\n  OLD: {path}\n  NEW: {new_path}")

        if not lines:
            messagebox.showinfo("No Matches",
                                 f"No feed paths contain:\n{find}", parent=self)
            return
        PreviewDialog(self, "\n\n".join(lines))

    def _apply_replace(self):
        find    = self.find_var.get()
        replace = self.replace_var.get()
        if not find:
            messagebox.showwarning("Empty Find", "Please enter a string to find.", parent=self)
            return

        scope          = self.scope_var.get()
        selected_vuid  = self.editor._current_vuid
        count = 0

        for feed in self.editor._get_all_feeds():
            vuid = feed.get("vuid", "")
            if scope == "selected" and vuid != selected_vuid:
                continue
            span = feed.find("spans/span")
            if span is not None:
                path_elem = span.find("path")
                if path_elem is not None and path_elem.text and find in path_elem.text:
                    path_elem.text = path_elem.text.replace(find, replace)
                    count += 1

        if count:
            self.editor._mark_dirty()
            self.editor._populate_feed_details(self.editor._current_vuid)

        self._recheck_all()
        messagebox.showinfo("Done", f"Updated {count} feed path(s).", parent=self)

    # ── Individual override ───────────────────────────────────────────────────

    def _browse_frame(self):
        path = filedialog.askopenfilename(
            title="Select Any Frame File",
            filetypes=[("EXR Files", "*.exr"), ("All Image Files",
                        "*.exr *.dpx *.tif *.tiff *.jpg *.png"),
                       ("All Files", "*.*")],
            parent=self,
        )
        if not path:
            return

        pattern, start, end = pattern_from_file(path)
        if pattern is None:
            messagebox.showwarning(
                "Pattern Not Detected",
                "Could not detect a frame-number pattern from the selected file.\n"
                "The raw path has been set — edit manually if needed.",
                parent=self)
            self.ind_path_var.set(path)
        else:
            self.ind_path_var.set(pattern)

    def _apply_individual(self):
        vuid     = self.ind_ver_var.get()
        new_path = self.ind_path_var.get().strip()
        if not vuid or not new_path:
            messagebox.showwarning(
                "Missing Info", "Please select a version and enter a path.", parent=self)
            return

        feed = self.editor._get_feed(vuid)
        if feed is None:
            messagebox.showerror("Error", f"Feed not found for {vuid}.", parent=self)
            return

        span = feed.find("spans/span")
        if span is not None:
            path_elem = span.find("path")
            if path_elem is not None:
                path_elem.text = new_path

        self.editor._mark_dirty()
        self.editor._populate_feed_details(self.editor._current_vuid)
        self._recheck_all()
        messagebox.showinfo("Done", f"Path updated for {vuid}.", parent=self)


# ─── Preview Dialog ────────────────────────────────────────────────────────────

class PreviewDialog(tk.Toplevel):
    def __init__(self, parent, text):
        super().__init__(parent)
        self.title("Preview Changes")
        self.geometry("720x420")
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        fr = ttk.Frame(self, padding=10)
        fr.pack(fill=tk.BOTH, expand=True)
        fr.rowconfigure(0, weight=1)
        fr.columnconfigure(0, weight=1)

        txt = tk.Text(fr, wrap=tk.NONE, font=("Menlo", 11), relief=tk.FLAT)
        txt.grid(row=0, column=0, sticky="nsew")

        sb_v = ttk.Scrollbar(fr, orient=tk.VERTICAL,   command=txt.yview)
        sb_v.grid(row=0, column=1, sticky="ns")
        sb_h = ttk.Scrollbar(fr, orient=tk.HORIZONTAL, command=txt.xview)
        sb_h.grid(row=1, column=0, sticky="ew")
        txt.configure(yscrollcommand=sb_v.set, xscrollcommand=sb_h.set)

        txt.insert("1.0", text)
        txt.config(state="disabled")

        ttk.Button(fr, text="Close", command=self.destroy).grid(
            row=2, column=0, sticky="e", pady=(8, 0))


# ─── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = OpenClipEditor()

    # macOS opens files via Apple Events, not sys.argv.
    # ::tk::mac::OpenDocument is the Tk/Aqua callback for the openDocument: event
    # sent by Finder when the user double-clicks a .clip file or uses "Open With".
    if platform.system() == "Darwin":
        def _apple_open(*paths):
            for p in paths:
                if os.path.isfile(p):
                    app._load_file(p)
                    app.lift()
                    app.focus_force()
                    break
        app.createcommand("::tk::mac::OpenDocument", _apple_open)

    # Fallback: honour a path passed on the command line (e.g. terminal usage)
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        app._load_file(sys.argv[1])

    app.mainloop()
