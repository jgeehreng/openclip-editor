"""
Script Name:    OpenClip Editor
Script Version: 2.0.0
Flame Version:  2023.2+

Description:
    Right-click any .clip file in the MediaHub to open it in OpenClip Editor.
    Built entirely with PySide2/PySide6 — the same Qt that ships with Flame.
    No extra packages, no subprocess, works on macOS and Rocky Linux.

Menu:
    MediaHub Files → OpenClip Editor → Open in OpenClip Editor

Install:
    Copy this single file to:
        /opt/Autodesk/shared/python/openclip_editor/openclip_editor.py
    Then reload: Flame → Python → Reload All Python Hooks

Standalone test (outside Flame):
    python3 openclip_editor.py [/path/to/file.clip]
    Requires PySide2 or PySide6:  pip install PySide6
"""

import os
import platform
import re
import subprocess
import sys
from collections import OrderedDict
from io import BytesIO
import xml.etree.ElementTree as ET

# ─── Qt import — PySide6 (Flame 2025+) or PySide2 (Flame 2023/2024) ──────────

try:
    from PySide6.QtWidgets import (
        QApplication, QDialog, QWidget, QSplitter, QGroupBox, QLabel,
        QLineEdit, QPushButton, QSpinBox, QComboBox, QTreeWidget,
        QTreeWidgetItem, QFrame, QFileDialog, QMessageBox, QTextEdit,
        QHBoxLayout, QVBoxLayout, QGridLayout, QSizePolicy, QMenuBar,
        QRadioButton, QScrollArea,
    )
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import (QAction, QKeySequence, QFont, QColor,
                               QStandardItemModel, QStandardItem, QBrush)
    _QT = 6
except ImportError:
    try:
        from PySide2.QtWidgets import (
            QApplication, QDialog, QWidget, QSplitter, QGroupBox, QLabel,
            QLineEdit, QPushButton, QSpinBox, QComboBox, QTreeWidget,
            QTreeWidgetItem, QFrame, QFileDialog, QMessageBox, QTextEdit,
            QHBoxLayout, QVBoxLayout, QGridLayout, QSizePolicy, QMenuBar,
            QAction, QRadioButton, QScrollArea,
        )
        from PySide2.QtCore import Qt, QTimer
        from PySide2.QtGui import (QKeySequence, QFont, QColor,
                                   QStandardItemModel, QStandardItem, QBrush)
        _QT = 2
    except ImportError:
        _QT = None


SCRIPT_NAME    = 'OpenClip Editor'
SCRIPT_VERSION = 'v2.0.0'


# ─── Timecode utilities ────────────────────────────────────────────────────────

def ticks_to_tc(nb_ticks, rate):
    rate = max(int(rate), 1)
    ff = nb_ticks % rate
    total_sec = nb_ticks // rate
    ss = total_sec % 60
    total_min = total_sec // 60
    mm = total_min % 60
    hh = total_min // 60
    return hh, mm, ss, ff


def tc_to_ticks(hh, mm, ss, ff, rate):
    rate = max(int(rate), 1)
    return hh * rate * 3600 + mm * rate * 60 + ss * rate + ff


def tc_to_str(hh, mm, ss, ff):
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


# ─── Path utilities ────────────────────────────────────────────────────────────

FRAME_RANGE_RE  = re.compile(r'\[(\d+)-(\d+)\]')
FRAME_NUMBER_RE = re.compile(r'^(.*?)\.(\d{4,})\.([\w]+)$')


def extract_frame_range(pattern):
    m = FRAME_RANGE_RE.search(pattern or "")
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def pattern_from_file(filepath):
    directory = os.path.dirname(filepath)
    filename  = os.path.basename(filepath)
    m = FRAME_NUMBER_RE.match(filename)
    if not m:
        return None, None, None
    prefix  = m.group(1)
    ext     = m.group(3)
    pad_len = len(m.group(2))
    scan_re = re.compile(
        r'^' + re.escape(prefix) + r'\.(\d{' + str(pad_len) + r',})\.' + re.escape(ext) + r'$')
    try:
        frame_nums = [int(scan_re.match(f).group(1))
                      for f in os.listdir(directory) if scan_re.match(f)]
    except OSError:
        return None, None, None
    if not frame_nums:
        return None, None, None
    frame_nums.sort()
    start, end = frame_nums[0], frame_nums[-1]
    return os.path.join(directory, f"{prefix}.[{start}-{end}].{ext}"), start, end


# ─── OCIO utilities ────────────────────────────────────────────────────────────

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


def find_ocio_config():
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
            parts = [p.strip() for p in family.split('/')][:2]
            category = ' / '.join(parts) if parts and parts[0] else 'Other'
            groups.setdefault(category, []).append(name)
    except Exception:
        pass
    return groups


def parse_ocio_colorspaces(path):
    groups = parse_ocio_grouped(path)
    return [n for names in groups.values() for n in names]


_OCIO_GROUPED = None


def get_ocio_grouped():
    global _OCIO_GROUPED
    if _OCIO_GROUPED is None:
        path = find_ocio_config()
        parsed = parse_ocio_grouped(path) if path else OrderedDict()
        _OCIO_GROUPED = parsed if parsed else OrderedDict(_OCIO_BUILTIN_GROUPED)
    return _OCIO_GROUPED


def get_ocio_colorspaces():
    return [n for names in get_ocio_grouped().values() for n in names]


def _build_grouped_combo_model(grouped):
    """Return a QStandardItemModel with bold non-selectable category headers."""
    model = QStandardItemModel()
    header_font = QFont()
    header_font.setBold(True)
    header_color = QBrush(QColor(140, 140, 140))
    for category, names in grouped.items():
        header = QStandardItem(category)
        header.setEnabled(False)
        header.setSelectable(False)
        header.setFont(header_font)
        header.setForeground(header_color)
        model.appendRow(header)
        for name in names:
            model.appendRow(QStandardItem(name))
    return model


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


# ─── XML helpers ───────────────────────────────────────────────────────────────

def _indent_xml(elem, level=0, indent_char='\t'):
    pad       = '\n' + indent_char * level
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
    root = tree.getroot()
    _indent_xml(root)
    buf = BytesIO()
    tree.write(buf, encoding='UTF-8', xml_declaration=True)
    content = buf.getvalue().replace(
        b"<?xml version='1.0' encoding='UTF-8'?>",
        b'<?xml version="1.0" encoding="UTF-8"?>'
    )
    with open(path, 'wb') as fh:
        fh.write(content)


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _separator(orientation='h'):
    line = QFrame()
    line.setFrameShape(QFrame.HLine if orientation == 'h' else QFrame.VLine)
    line.setFrameShadow(QFrame.Sunken)
    return line


def _hbox(*widgets, spacing=6):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for item in widgets:
        if isinstance(item, int):
            lay.addSpacing(item)
        elif item == 'stretch':
            lay.addStretch()
        else:
            lay.addWidget(item)
    return w


# ─── OpenClip Editor Dialog ────────────────────────────────────────────────────

class OpenClipEditorDialog(QDialog):

    def __init__(self, clip_path=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(SCRIPT_NAME)
        self.resize(1180, 740)
        self.setMinimumSize(960, 620)
        self.setWindowFlags(Qt.Window)

        self.clip_path     = None
        self.tree          = None
        self.clip_elem     = None
        self._dirty        = False
        self._current_vuid = None
        self._status_timer = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.setMenuBar(self._build_menu())
        outer.addWidget(self._build_path_bar())
        outer.addWidget(_separator())
        outer.addWidget(self._build_body(), stretch=1)
        outer.addWidget(_separator())
        outer.addWidget(self._build_status_bar())

        self._set_empty_state()
        if clip_path:
            self._load_file(clip_path)

    # ── Menu ──────────────────────────────────────────────────────────────────

    def _build_menu(self):
        mb = QMenuBar(self)

        file_menu = mb.addMenu("File")
        a = QAction("Open…", self)
        a.setShortcut(QKeySequence.Open)
        a.triggered.connect(self.cmd_open)
        file_menu.addAction(a)

        a = QAction("Save", self)
        a.setShortcut(QKeySequence.Save)
        a.triggered.connect(self.cmd_save)
        file_menu.addAction(a)

        a = QAction("Save As…", self)
        a.setShortcut(QKeySequence("Ctrl+Shift+S"))
        a.triggered.connect(self.cmd_save_as)
        file_menu.addAction(a)

        file_menu.addSeparator()

        a = QAction("Close", self)
        a.setShortcut(QKeySequence("Ctrl+W"))
        a.triggered.connect(self.close)
        file_menu.addAction(a)

        tools_menu = mb.addMenu("Tools")
        a = QAction("Fix Paths…", self)
        a.triggered.connect(self.cmd_fix_paths)
        tools_menu.addAction(a)

        return mb

    # ── Path bar ──────────────────────────────────────────────────────────────

    def _build_path_bar(self):
        bar = QWidget()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.addWidget(QLabel("File:"))
        self.path_label = QLabel("No file loaded")
        self.path_label.setStyleSheet("color: gray;")
        lay.addWidget(self.path_label, stretch=1)
        return bar

    # ── Body (splitter) ───────────────────────────────────────────────────────

    def _build_body(self):
        splitter = QSplitter(Qt.Horizontal)
        splitter.setContentsMargins(6, 4, 6, 4)

        left = QWidget()
        left.setMinimumWidth(260)
        left.setMaximumWidth(320)
        self._build_left_panel(left)
        splitter.addWidget(left)

        right = QWidget()
        self._build_right_panel(right)
        splitter.addWidget(right)

        splitter.setSizes([280, 880])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        return splitter

    # ── Left panel ────────────────────────────────────────────────────────────

    def _build_left_panel(self, parent):
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        # Clip Info
        clip_gr = QGroupBox("Clip Info")
        g = QGridLayout(clip_gr)
        g.setColumnStretch(1, 1)
        g.addWidget(QLabel("Clip Name:"),   0, 0, Qt.AlignRight)
        self.clip_name_edit = QLineEdit()
        g.addWidget(self.clip_name_edit,    0, 1)
        g.addWidget(QLabel("Source Name:"), 1, 0, Qt.AlignRight)
        self.source_name_edit = QLineEdit()
        g.addWidget(self.source_name_edit,  1, 1)
        lay.addWidget(clip_gr)

        # Track Info
        track_gr = QGroupBox("Track")
        g = QGridLayout(track_gr)
        g.setColumnStretch(1, 1)
        g.addWidget(QLabel("Track Name:"), 0, 0, Qt.AlignRight)
        self.track_name_edit = QLineEdit()
        g.addWidget(self.track_name_edit,  0, 1)
        g.addWidget(QLabel("Edit Rate:"),  1, 0, Qt.AlignRight)
        self.edit_rate_label = QLabel("—")
        g.addWidget(self.edit_rate_label,  1, 1)
        g.addWidget(QLabel("Type:"),       2, 0, Qt.AlignRight)
        self.track_type_label = QLabel("—")
        g.addWidget(self.track_type_label, 2, 1)
        lay.addWidget(track_gr)

        # Current Version
        cur_gr = QGroupBox("Current Version")
        g = QVBoxLayout(cur_gr)
        self.current_version_cb = QComboBox()
        self.current_version_cb.currentIndexChanged.connect(self._on_current_version_changed)
        g.addWidget(self.current_version_cb)
        lay.addWidget(cur_gr)

        # Metadata
        meta_gr = QGroupBox("Metadata")
        g = QGridLayout(meta_gr)
        g.setColumnStretch(1, 1)
        g.addWidget(QLabel("Flame:"),        0, 0, Qt.AlignRight)
        self.flame_ver_label = QLabel("—")
        g.addWidget(self.flame_ver_label,    0, 1)
        g.addWidget(QLabel("Module:"),       1, 0, Qt.AlignRight)
        self.module_label = QLabel("—")
        g.addWidget(self.module_label,       1, 1)
        g.addWidget(QLabel("Format Version:"), 2, 0, Qt.AlignRight)
        self.clip_ver_label = QLabel("—")
        g.addWidget(self.clip_ver_label,     2, 1)
        lay.addWidget(meta_gr)

        lay.addStretch()

    # ── Right panel ───────────────────────────────────────────────────────────

    def _build_right_panel(self, parent):
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        # Versions table
        ver_gr = QGroupBox("Versions")
        vl = QVBoxLayout(ver_gr)

        self.ver_tree = QTreeWidget()
        self.ver_tree.setColumnCount(5)
        self.ver_tree.setHeaderLabels(["Version", "Name", "Created", "Module", "Flame"])
        self.ver_tree.setRootIsDecorated(False)
        self.ver_tree.setSelectionMode(QTreeWidget.SingleSelection)
        self.ver_tree.setAlternatingRowColors(True)
        self.ver_tree.header().setStretchLastSection(False)
        self.ver_tree.setColumnWidth(0, 70)
        self.ver_tree.setColumnWidth(1, 200)
        self.ver_tree.setColumnWidth(2, 170)
        self.ver_tree.setColumnWidth(3, 90)
        self.ver_tree.setColumnWidth(4, 100)
        self.ver_tree.itemSelectionChanged.connect(self._on_version_select)
        vl.addWidget(self.ver_tree)

        self.remove_ver_btn = QPushButton("Remove Selected Version")
        self.remove_ver_btn.clicked.connect(self.cmd_remove_version)
        vl.addWidget(self.remove_ver_btn, alignment=Qt.AlignLeft)

        lay.addWidget(ver_gr)

        # Feed Details
        feed_gr = QGroupBox("Feed Details")
        self._build_feed_details(feed_gr)
        lay.addWidget(feed_gr, stretch=1)

    def _build_feed_details(self, parent):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        g = QGridLayout(content)
        g.setColumnStretch(1, 1)
        g.setSpacing(6)

        row = 0

        # Version Name
        g.addWidget(QLabel("Version Name:"), row, 0, Qt.AlignRight)
        self.ver_name_edit = QLineEdit()
        apply_vn = QPushButton("Apply")
        apply_vn.clicked.connect(self._apply_version_name)
        g.addWidget(_hbox(self.ver_name_edit, apply_vn), row, 1, 1, 2)
        row += 1

        g.addWidget(_separator(), row, 0, 1, 3)
        row += 1

        # Start TC
        g.addWidget(QLabel("Start TC:"), row, 0, Qt.AlignRight)
        self.tc_hh = QSpinBox(); self.tc_hh.setRange(0, 23);  self.tc_hh.setFixedWidth(52)
        self.tc_mm = QSpinBox(); self.tc_mm.setRange(0, 59);  self.tc_mm.setFixedWidth(52)
        self.tc_ss = QSpinBox(); self.tc_ss.setRange(0, 59);  self.tc_ss.setFixedWidth(52)
        self.tc_ff = QSpinBox(); self.tc_ff.setRange(0, 999); self.tc_ff.setFixedWidth(52)
        self.tc_info_label = QLabel("")
        self.tc_info_label.setStyleSheet("color: gray;")
        apply_tc = QPushButton("Apply")
        apply_tc.clicked.connect(self._apply_timecode)
        tc_row = _hbox(self.tc_hh, QLabel(":"), self.tc_mm, QLabel(":"),
                       self.tc_ss, QLabel(":"), self.tc_ff,
                       8, self.tc_info_label, 'stretch', apply_tc)
        g.addWidget(tc_row, row, 1, 1, 2)
        row += 1

        # Out TC
        g.addWidget(QLabel("Out TC:"), row, 0, Qt.AlignRight)
        self.out_tc_label = QLabel("—")
        self.out_tc_label.setStyleSheet("color: gray;")
        g.addWidget(self.out_tc_label, row, 1)
        row += 1

        g.addWidget(_separator(), row, 0, 1, 3)
        row += 1

        # File Path
        g.addWidget(QLabel("Path:"), row, 0, Qt.AlignRight)
        self.feed_path_edit = QLineEdit()
        apply_path = QPushButton("Apply")
        apply_path.clicked.connect(self._apply_feed_path)
        _finder_label = "Show in Finder" if platform.system() == "Darwin" else "Open Folder"
        finder_btn = QPushButton(_finder_label)
        finder_btn.clicked.connect(self._show_in_finder)
        g.addWidget(_hbox(self.feed_path_edit, apply_path, finder_btn), row, 1, 1, 2)
        row += 1

        # Start Frame
        g.addWidget(QLabel("Start Frame:"), row, 0, Qt.AlignRight)
        self.start_frame_spin = QSpinBox()
        self.start_frame_spin.setRange(0, 9_999_999)
        self.start_frame_spin.setFixedWidth(90)
        self.start_frame_spin.setSpecialValueText(" ")
        apply_sf = QPushButton("Apply")
        apply_sf.clicked.connect(self._apply_start_frame)
        g.addWidget(_hbox(self.start_frame_spin, apply_sf, 'stretch'), row, 1, 1, 2)
        row += 1

        # End Frame
        g.addWidget(QLabel("End Frame:"), row, 0, Qt.AlignRight)
        self.end_frame_spin = QSpinBox()
        self.end_frame_spin.setRange(0, 9_999_999)
        self.end_frame_spin.setFixedWidth(90)
        self.end_frame_spin.setSpecialValueText(" ")
        apply_ef     = QPushButton("Apply")
        apply_ef_all = QPushButton("Apply to All Versions")
        apply_ef.clicked.connect(self._apply_end_frame)
        apply_ef_all.clicked.connect(self._apply_end_frame_all)
        g.addWidget(_hbox(self.end_frame_spin, apply_ef, apply_ef_all, 'stretch'), row, 1, 1, 2)
        row += 1

        # Duration
        g.addWidget(QLabel("Duration:"), row, 0, Qt.AlignRight)
        self.frames_label = QLabel("—")
        self.frames_label.setStyleSheet("color: gray;")
        g.addWidget(self.frames_label, row, 1)
        row += 1

        g.addWidget(_separator(), row, 0, 1, 3)
        row += 1

        # Resolution
        g.addWidget(QLabel("Resolution:"), row, 0, Qt.AlignRight)
        self.res_label = QLabel("—")
        g.addWidget(self.res_label, row, 1)
        row += 1

        # Color Space (editable dropdown backed by OCIO config, grouped by family)
        g.addWidget(QLabel("Color Space:"), row, 0, Qt.AlignRight)
        self.color_edit = QComboBox()
        self.color_edit.setEditable(True)
        self.color_edit.setInsertPolicy(QComboBox.NoInsert)
        self.color_edit.setModel(_build_grouped_combo_model(get_ocio_grouped()))
        self.color_edit.setCurrentIndex(-1)
        self.color_edit.lineEdit().setPlaceholderText("Select or type a color space…")
        # When user picks from the list, put just the name (headers are non-selectable)
        self.color_edit.activated.connect(self._on_color_activated)
        apply_cs = QPushButton("Apply")
        apply_cs.clicked.connect(self._apply_color_space)
        ocio_browse_btn = QPushButton("…")
        ocio_browse_btn.setFixedWidth(28)
        ocio_browse_btn.setToolTip("Load a different OCIO config")
        ocio_browse_btn.clicked.connect(self._browse_ocio_config)
        g.addWidget(_hbox(self.color_edit, apply_cs, ocio_browse_btn), row, 1, 1, 2)
        row += 1

        # Format
        g.addWidget(QLabel("Format:"), row, 0, Qt.AlignRight)
        self.format_label = QLabel("—")
        g.addWidget(self.format_label, row, 1)
        row += 1

        g.setRowStretch(row, 1)

        scroll.setWidget(content)
        outer = QVBoxLayout(parent)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.addWidget(scroll)

    # ── Status bar ────────────────────────────────────────────────────────────

    def _build_status_bar(self):
        bar = QWidget()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 4, 8, 4)

        self.status_label = QLabel("No file loaded")
        lay.addWidget(self.status_label, stretch=1)

        fix_btn = QPushButton("Fix Paths…")
        fix_btn.clicked.connect(self.cmd_fix_paths)
        lay.addWidget(fix_btn)

        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.cmd_save)
        lay.addWidget(self.save_btn)

        return bar

    # ── State management ──────────────────────────────────────────────────────

    def _set_empty_state(self):
        self._current_vuid = None
        self.ver_tree.clear()
        self._clear_feed_details()
        self._set_widgets_enabled(False)
        self.status_label.setText("No file loaded")
        self.path_label.setText("No file loaded")
        self.path_label.setStyleSheet("color: gray;")
        self.setWindowTitle(SCRIPT_NAME)

    def _set_widgets_enabled(self, enabled):
        for w in [self.clip_name_edit, self.source_name_edit, self.track_name_edit,
                  self.remove_ver_btn, self.save_btn, self.feed_path_edit,
                  self.color_edit, self.start_frame_spin, self.end_frame_spin,
                  self.ver_name_edit, self.tc_hh, self.tc_mm, self.tc_ss, self.tc_ff,
                  self.current_version_cb]:
            w.setEnabled(enabled)

    def _clear_feed_details(self):
        self.ver_name_edit.setText("")
        self.tc_hh.setValue(0)
        self.tc_mm.setValue(0)
        self.tc_ss.setValue(0)
        self.tc_ff.setValue(0)
        self.tc_info_label.setText("")
        self.out_tc_label.setText("—")
        self.feed_path_edit.setText("")
        self.frames_label.setText("—")
        self.start_frame_spin.setValue(0)
        self.end_frame_spin.setValue(0)
        self.res_label.setText("—")
        self.color_edit.setCurrentText("")
        self.format_label.setText("—")

    # ── Populate ──────────────────────────────────────────────────────────────

    def _populate_from_xml(self):
        self._set_widgets_enabled(True)
        clip = self.clip_elem

        self.clip_ver_label.setText(clip.get("version", "—"))
        self.clip_name_edit.setText(self._get_text(clip, "name") or "")
        self.source_name_edit.setText(self._get_text(clip, "sourceName") or "")

        ud = clip.find("userData")
        if ud is not None:
            self.flame_ver_label.setText(self._get_text(ud, "appVersion") or "—")
            self.module_label.setText(self._get_text(ud, "module") or "—")

        track = self._get_track()
        if track is not None:
            self.track_name_edit.setText(self._get_text(track, "name") or "")
            er = track.find("editRate")
            if er is not None:
                num = int(er.findtext("numerator") or 24000)
                den = int(er.findtext("denominator") or 1001)
                self.edit_rate_label.setText(f"{num/den:.3f} fps  ({num}/{den})")
            self.track_type_label.setText(self._get_text(track, "trackType") or "—")

        self._populate_versions_table()

        versions_elem = clip.find("versions")
        cur_ver = versions_elem.get("currentVersion") if versions_elem is not None else None
        vuids = [v.get("uid") for v in (versions_elem if versions_elem is not None else [])
                 if v.tag == "version"]

        self.current_version_cb.blockSignals(True)
        self.current_version_cb.clear()
        self.current_version_cb.addItems(vuids)
        resolved = cur_ver if cur_ver in vuids else (vuids[-1] if vuids else "")
        idx = self.current_version_cb.findText(resolved)
        if idx >= 0:
            self.current_version_cb.setCurrentIndex(idx)
        self.current_version_cb.blockSignals(False)

        if resolved:
            self._select_version_in_table(resolved)

        fname = os.path.basename(self.clip_path)
        n = len(vuids)
        self.status_label.setText(f"Loaded {fname} — {n} version{'s' if n != 1 else ''}")
        self.setWindowTitle(f"{SCRIPT_NAME} — {fname}")

    def _populate_versions_table(self):
        self.ver_tree.clear()
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
            module    = (self._get_text(ud, "module")     if ud is not None else "") or ""
            flame_ver = (self._get_text(ud, "appVersion") if ud is not None else "") or ""
            item = QTreeWidgetItem([vuid, name, created, module, flame_ver])
            item.setData(0, Qt.UserRole, vuid)
            self.ver_tree.addTopLevelItem(item)

    def _select_version_in_table(self, vuid):
        for i in range(self.ver_tree.topLevelItemCount()):
            item = self.ver_tree.topLevelItem(i)
            if item.data(0, Qt.UserRole) == vuid:
                self.ver_tree.blockSignals(True)
                self.ver_tree.setCurrentItem(item)
                self.ver_tree.blockSignals(False)
                break
        self._populate_feed_details(vuid)

    def _populate_feed_details(self, vuid):
        self._current_vuid = vuid
        self._clear_feed_details()
        if not vuid:
            return

        versions_elem = self.clip_elem.find("versions")
        if versions_elem is not None:
            for ver in versions_elem:
                if ver.get("uid") == vuid:
                    self.ver_name_edit.setText(self._get_text(ver, "name") or "")
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
            self.tc_hh.setValue(hh)
            self.tc_mm.setValue(mm)
            self.tc_ss.setValue(ss)
            self.tc_ff.setValue(ff)
            self.tc_info_label.setText(f"{drop}  {rate}fps")
            duration = self._get_feed_duration(feed)
            if duration is not None:
                oh, om, os_, of_ = ticks_to_tc(nb + duration, rate)
                self.out_tc_label.setText(f"{tc_to_str(oh, om, os_, of_)}  ({duration} frames)")

        # Path
        span = feed.find("spans/span")
        if span is not None:
            path_elem = span.find("path")
            path_text = (path_elem.text or "") if path_elem is not None else ""
            self.feed_path_edit.setText(path_text)
            s_fr, e_fr = extract_frame_range(path_text)
            if s_fr is not None and e_fr is not None:
                self.end_frame_spin.setValue(e_fr)
                self.frames_label.setText(f"{e_fr - s_fr + 1} frames  ({s_fr}–{e_fr})")

        # Start frame
        sf = feed.findtext("startFrame")
        if not sf:
            span2 = feed.find("spans/span")
            if span2 is not None:
                pe = span2.find("path")
                s_fr, _ = extract_frame_range(pe.text or "" if pe is not None else "")
                if s_fr is not None:
                    sf = str(s_fr)
        if sf:
            try:
                self.start_frame_spin.setValue(int(sf))
            except ValueError:
                pass

        # Storage format
        sf_elem = feed.find("storageFormat")
        if sf_elem is not None:
            w   = sf_elem.findtext("width")  or "?"
            h   = sf_elem.findtext("height") or "?"
            self.res_label.setText(f"{w} × {h}")
            self.color_edit.setCurrentText(sf_elem.findtext("colourSpace") or "")
            fmt   = sf_elem.findtext("fileFormat")      or ""
            comp  = sf_elem.findtext("compression")      or ""
            depth = sf_elem.findtext("channelsDepth")    or ""
            enc   = sf_elem.findtext("channelsEncoding") or ""
            parts = []
            if fmt:  parts.append(fmt.upper())
            if comp: parts.append(comp)
            fmt_str = " / ".join(parts) or "—"
            if depth:
                fmt_str += f"   {depth}-bit {enc}".rstrip()
            self.format_label.setText(fmt_str)

    def _get_feed_duration(self, feed):
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

    def _on_version_select(self):
        items = self.ver_tree.selectedItems()
        if items:
            self._populate_feed_details(items[0].data(0, Qt.UserRole))

    def _on_current_version_changed(self, idx):
        if idx < 0:
            return
        vuid  = self.current_version_cb.currentText()
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
        new_name = self.ver_name_edit.text().strip()
        versions_elem = self.clip_elem.find("versions")
        if versions_elem is not None:
            for ver in versions_elem:
                if ver.get("uid") == self._current_vuid:
                    ne = ver.find("name")
                    if ne is not None:
                        ne.text = new_name
                    break
        self._populate_versions_table()
        self._select_version_in_table(self._current_vuid)
        self._mark_dirty()
        self._set_status(f"Version name updated for {self._current_vuid}")

    def _apply_timecode(self):
        if not self._current_vuid:
            return
        feed = self._get_feed(self._current_vuid)
        if feed is None:
            return
        hh = self.tc_hh.value()
        mm = self.tc_mm.value()
        ss = self.tc_ss.value()
        ff = self.tc_ff.value()

        targets = [feed.find("startTimecode")]
        ud = feed.find("userData")
        if ud is not None:
            rec = ud.find("recordTimecode")
            if rec is not None:
                targets.append(rec)

        for tc_elem in targets:
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
        new_path = self.feed_path_edit.text().strip()
        span = feed.find("spans/span")
        if span is not None:
            pe = span.find("path")
            if pe is not None:
                pe.text = new_path
        self._mark_dirty()
        self._populate_feed_details(self._current_vuid)
        self._set_status(f"Path updated for {self._current_vuid}")

    def _show_in_finder(self):
        path = self.feed_path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "No Path", "No path is set for this feed.")
            return
        if not open_in_file_manager(path):
            QMessageBox.warning(
                self, "Directory Not Found",
                f"Directory does not exist:\n{os.path.dirname(path)}")

    def _on_color_activated(self, index):
        """When the user picks from the dropdown, ensure the line edit shows just the name."""
        item = self.color_edit.model().item(index)
        if item and item.isEnabled():
            self.color_edit.lineEdit().setText(item.text())

    def _browse_ocio_config(self):
        """Let the user pick a .ocio file and reload the color space dropdown from it."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select OCIO Config", "",
            "OCIO Config (*.ocio);;All Files (*)")
        if not path:
            return
        global _OCIO_GROUPED
        _OCIO_GROUPED = parse_ocio_grouped(path)
        current = self.color_edit.currentText()
        self.color_edit.setModel(_build_grouped_combo_model(_OCIO_GROUPED))
        self.color_edit.lineEdit().setText(current)
        total = sum(len(v) for v in _OCIO_GROUPED.values())
        self._set_status(
            f"Loaded {total} color spaces from {os.path.basename(path)}")

    def _apply_color_space(self):
        if not self._current_vuid:
            return
        feed = self._get_feed(self._current_vuid)
        if feed is None:
            return
        sf_elem = feed.find("storageFormat")
        if sf_elem is not None:
            cs = sf_elem.find("colourSpace")
            if cs is not None:
                cs.text = self.color_edit.currentText().strip()
        self._mark_dirty()
        self._set_status(f"Color space updated for {self._current_vuid}")

    def _apply_start_frame(self):
        if not self._current_vuid:
            return
        feed = self._get_feed(self._current_vuid)
        if feed is None:
            return
        val = str(self.start_frame_spin.value())
        sf_elem = feed.find("startFrame")
        if sf_elem is not None:
            sf_elem.text = val
        else:
            sf_elem = ET.SubElement(feed, "startFrame")
            sf_elem.text = val
        self._mark_dirty()
        self._set_status(f"Start frame updated for {self._current_vuid}")

    def _apply_end_frame(self):
        if not self._current_vuid:
            return
        self._set_feed_end_frame(self._current_vuid, self.end_frame_spin.value())
        self._populate_feed_details(self._current_vuid)
        self._set_status(f"End frame updated for {self._current_vuid}")

    def _apply_end_frame_all(self):
        end   = self.end_frame_spin.value()
        feeds = self._get_all_feeds()
        if not feeds:
            return
        reply = QMessageBox.question(
            self, "Apply to All Versions",
            f"Set end frame to {end} for all {len(feeds)} version(s)?\n\n"
            "This updates each feed's path pattern and <duration> where present.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        for feed in feeds:
            self._set_feed_end_frame(feed.get("vuid", ""), end)
        self._populate_feed_details(self._current_vuid)
        self._set_status(f"End frame set to {end} across all {len(feeds)} version(s)")

    def _set_feed_end_frame(self, vuid, end_frame):
        feed = self._get_feed(vuid)
        if feed is None:
            return
        span = feed.find("spans/span")
        if span is None:
            return
        pe = span.find("path")
        if pe is not None and pe.text:
            pe.text = FRAME_RANGE_RE.sub(
                lambda m: f"[{m.group(1)}-{end_frame}]", pe.text)
            s_fr, e_fr = extract_frame_range(pe.text)
            if s_fr is not None:
                dur_elem = span.find("duration")
                if dur_elem is not None:
                    dur_elem.text = str(e_fr - s_fr + 1)
        self._mark_dirty()

    def _apply_clip_meta(self):
        self._set_text(self.clip_elem, "name", self.clip_name_edit.text())
        self._set_text(self.clip_elem, "sourceName", self.source_name_edit.text())
        track = self._get_track()
        if track is not None:
            self._set_text(track, "name", self.track_name_edit.text())

    # ── Commands ──────────────────────────────────────────────────────────────

    def cmd_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Clip File", "",
            "Flame Clip Files (*.clip);;All Files (*)")
        if path:
            self._load_file(path)

    def _load_file(self, path):
        try:
            tree = ET.parse(path)
        except ET.ParseError as e:
            QMessageBox.critical(self, "Parse Error", f"Could not parse clip file:\n{e}")
            return
        except OSError as e:
            QMessageBox.critical(self, "File Error", f"Could not open file:\n{e}")
            return
        self.tree      = tree
        self.clip_elem = tree.getroot()
        self.clip_path = path
        self._dirty    = False
        self.path_label.setText(path)
        self.path_label.setStyleSheet("")
        self._populate_from_xml()

    def cmd_save(self):
        if self.clip_path is None:
            self.cmd_save_as()
            return
        self._apply_clip_meta()
        try:
            write_clip(self.tree, self.clip_path)
        except OSError as e:
            QMessageBox.critical(self, "Save Error", f"Could not save file:\n{e}")
            return
        self._dirty = False
        fname = os.path.basename(self.clip_path)
        self.setWindowTitle(f"{SCRIPT_NAME} — {fname}")
        self._set_status(f"Saved: {self.clip_path}")
        _flame_refresh_mediahub()

    def cmd_save_as(self):
        init = os.path.basename(self.clip_path) if self.clip_path else "clip.clip"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Clip File As", init,
            "Flame Clip Files (*.clip);;All Files (*)")
        if not path:
            return
        self._apply_clip_meta()
        try:
            write_clip(self.tree, path)
        except OSError as e:
            QMessageBox.critical(self, "Save Error", f"Could not save file:\n{e}")
            return
        self.clip_path = path
        self.path_label.setText(path)
        self.path_label.setStyleSheet("")
        self._dirty = False
        fname = os.path.basename(path)
        self.setWindowTitle(f"{SCRIPT_NAME} — {fname}")
        self._set_status(f"Saved: {path}")
        _flame_refresh_mediahub()

    def cmd_remove_version(self):
        items = self.ver_tree.selectedItems()
        if not items:
            QMessageBox.warning(self, "No Selection", "Please select a version to remove.")
            return
        vuid = items[0].data(0, Qt.UserRole)

        versions_elem = self.clip_elem.find("versions")
        ver_name = vuid
        for v in (versions_elem if versions_elem is not None else []):
            if v.get("uid") == vuid:
                ver_name = self._get_text(v, "name") or vuid
                break

        reply = QMessageBox.question(
            self, "Remove Version",
            f"Remove version '{ver_name}' ({vuid})?\n\nThis will also remove its feed data.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        if versions_elem is not None:
            for v in list(versions_elem):
                if v.get("uid") == vuid:
                    versions_elem.remove(v)
                    break

        track = self._get_track()
        if track is not None:
            feeds = track.find("feeds")
            if feeds is not None:
                for f in list(feeds):
                    if f.get("vuid") == vuid:
                        feeds.remove(f)
                        break

        remaining = [v.get("uid") for v in (versions_elem if versions_elem is not None else [])
                     if v.tag == "version"]
        cur = self.current_version_cb.currentText()
        new_cur = cur if cur in remaining else (remaining[-1] if remaining else "")

        if versions_elem is not None:
            versions_elem.set("currentVersion", new_cur)
        if track is not None:
            feeds = track.find("feeds")
            if feeds is not None:
                feeds.set("currentVersion", new_cur)

        self._mark_dirty()
        self._populate_versions_table()
        self.current_version_cb.blockSignals(True)
        self.current_version_cb.clear()
        self.current_version_cb.addItems(remaining)
        self.current_version_cb.blockSignals(False)
        if new_cur:
            idx = self.current_version_cb.findText(new_cur)
            if idx >= 0:
                self.current_version_cb.setCurrentIndex(idx)
            self._select_version_in_table(new_cur)
        else:
            self._clear_feed_details()
        self._set_status(f"Removed version {vuid}")

    def cmd_fix_paths(self):
        if self.clip_elem is None:
            QMessageBox.information(self, "No File", "Please open a .clip file first.")
            return
        dlg = FixPathsDialog(self)
        dlg.exec_()

    def closeEvent(self, event):
        if self._dirty:
            msg = QMessageBox(self)
            msg.setWindowTitle("Unsaved Changes")
            msg.setText("You have unsaved changes. Save before closing?")
            msg.setStandardButtons(
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            msg.setDefaultButton(QMessageBox.Save)
            reply = msg.exec_()
            if reply == QMessageBox.Cancel:
                event.ignore()
                return
            if reply == QMessageBox.Save:
                self.cmd_save()
        event.accept()
        if self in _open_dialogs:
            _open_dialogs.remove(self)

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
            self.setWindowTitle(f"{SCRIPT_NAME} — {fname} •")

    def _set_status(self, msg):
        self.status_label.setText(msg)
        if self._status_timer:
            self._status_timer.stop()
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._restore_status)
        self._status_timer.start(4000)

    def _restore_status(self):
        if self.clip_path:
            n     = self.current_version_cb.count()
            fname = os.path.basename(self.clip_path)
            self.status_label.setText(
                f"Loaded {fname} — {n} version{'s' if n != 1 else ''}")


# ─── Fix Paths Dialog ──────────────────────────────────────────────────────────

class FixPathsDialog(QDialog):

    def __init__(self, editor: OpenClipEditorDialog):
        super().__init__(editor)
        self.editor = editor
        self.setWindowTitle("Fix Paths")
        self.resize(900, 640)
        self._build_ui()
        self._recheck_all()

    def _build_ui(self):
        lay = QVBoxLayout(self)

        # Batch replacement
        batch_gr = QGroupBox("Batch Prefix Replacement")
        g = QGridLayout(batch_gr)
        g.setColumnStretch(1, 1)
        g.addWidget(QLabel("Find:"),    0, 0, Qt.AlignRight)
        self.find_edit = QLineEdit()
        g.addWidget(self.find_edit,     0, 1)
        g.addWidget(QLabel("Replace:"), 1, 0, Qt.AlignRight)
        self.replace_edit = QLineEdit()
        g.addWidget(self.replace_edit,  1, 1)

        self.scope_all = QRadioButton("All versions")
        self.scope_sel = QRadioButton("Selected version only")
        self.scope_all.setChecked(True)
        scope_row = _hbox(self.scope_all, self.scope_sel, 'stretch')
        g.addWidget(scope_row, 2, 0, 1, 2)

        btn_row = _hbox(
            QPushButton("Preview"),
            QPushButton("Apply to Feeds"),
            'stretch')
        btn_row.layout().itemAt(0).widget().clicked.connect(self._preview_replace)
        btn_row.layout().itemAt(1).widget().clicked.connect(self._apply_replace)
        g.addWidget(btn_row, 3, 0, 1, 2)
        lay.addWidget(batch_gr)

        # Validation table
        val_gr = QGroupBox("Path Validation")
        vl = QVBoxLayout(val_gr)
        self.val_tree = QTreeWidget()
        self.val_tree.setColumnCount(4)
        self.val_tree.setHeaderLabels(["Version", "Type", "Path", "Status"])
        self.val_tree.setRootIsDecorated(False)
        self.val_tree.setColumnWidth(0, 70)
        self.val_tree.setColumnWidth(1, 70)
        self.val_tree.setColumnWidth(2, 580)
        self.val_tree.setColumnWidth(3, 120)
        vl.addWidget(self.val_tree)
        recheck = QPushButton("Recheck All")
        recheck.clicked.connect(self._recheck_all)
        vl.addWidget(recheck, alignment=Qt.AlignRight)
        lay.addWidget(val_gr, stretch=1)

        # Individual override
        ind_gr = QGroupBox("Individual Path Override")
        g2 = QGridLayout(ind_gr)
        g2.setColumnStretch(1, 1)
        g2.addWidget(QLabel("Version:"), 0, 0, Qt.AlignRight)
        vuids = [f.get("vuid") for f in self.editor._get_all_feeds() if f.get("vuid")]
        self.ind_ver_cb = QComboBox()
        self.ind_ver_cb.addItems(vuids)
        g2.addWidget(self.ind_ver_cb, 0, 1)
        g2.addWidget(QLabel("Path:"), 1, 0, Qt.AlignRight)
        self.ind_path_edit = QLineEdit()
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_frame)
        g2.addWidget(_hbox(self.ind_path_edit, browse_btn), 1, 1)
        apply_ind = QPushButton("Apply to Selected")
        apply_ind.clicked.connect(self._apply_individual)
        g2.addWidget(apply_ind, 2, 1, alignment=Qt.AlignLeft)
        lay.addWidget(ind_gr)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        lay.addWidget(close_btn, alignment=Qt.AlignRight)

    def _iter_all_paths(self):
        for feed in self.editor._get_all_feeds():
            vuid = feed.get("vuid", "")
            span = feed.find("spans/span")
            if span is not None:
                pe = span.find("path")
                if pe is not None and pe.text:
                    yield vuid, pe.text.strip(), "feed"
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
        self.val_tree.clear()
        RED    = "#c0392b"
        GREEN  = "#27ae60"
        GRAY   = "#7f8c8d"
        ORANGE = "#e67e22"
        for vuid, path, kind in self._iter_all_paths():
            if kind == "batch":
                exists = os.path.exists(path)
                color  = GRAY if exists else ORANGE
                status = "✓ OK" if exists else "✗ MISSING"
            else:
                exists = os.path.isdir(os.path.dirname(path))
                color  = GREEN if exists else RED
                status = "✓ OK" if exists else "✗ MISSING"
            item = QTreeWidgetItem([vuid, kind, path, status])
            item.setForeground(3, QColor(color))
            self.val_tree.addTopLevelItem(item)

    def _preview_replace(self):
        find = self.find_edit.text()
        if not find:
            QMessageBox.warning(self, "Empty Find", "Please enter a string to find.")
            return
        replace = self.replace_edit.text()
        lines = []
        for vuid, path, kind in self._iter_all_paths():
            if kind != "feed":
                continue
            if find in path:
                lines.append(f"[{vuid}]\n  OLD: {path}\n  NEW: {path.replace(find, replace)}")
        if not lines:
            QMessageBox.information(self, "No Matches",
                                    f"No feed paths contain:\n{find}")
            return
        PreviewDialog(self, "\n\n".join(lines))

    def _apply_replace(self):
        find = self.find_edit.text()
        if not find:
            QMessageBox.warning(self, "Empty Find", "Please enter a string to find.")
            return
        replace      = self.replace_edit.text()
        scope_all    = self.scope_all.isChecked()
        sel_vuid     = self.editor._current_vuid
        count = 0
        for feed in self.editor._get_all_feeds():
            vuid = feed.get("vuid", "")
            if not scope_all and vuid != sel_vuid:
                continue
            span = feed.find("spans/span")
            if span is not None:
                pe = span.find("path")
                if pe is not None and pe.text and find in pe.text:
                    pe.text = pe.text.replace(find, replace)
                    count += 1
        if count:
            self.editor._mark_dirty()
            self.editor._populate_feed_details(self.editor._current_vuid)
        self._recheck_all()
        QMessageBox.information(self, "Done", f"Updated {count} feed path(s).")

    def _browse_frame(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Any Frame File", "",
            "EXR Files (*.exr);;Image Files (*.exr *.dpx *.tif *.tiff *.jpg *.png);;All Files (*)")
        if not path:
            return
        pattern, start, end = pattern_from_file(path)
        if pattern is None:
            QMessageBox.warning(
                self, "Pattern Not Detected",
                "Could not detect a frame-number pattern from the selected file.\n"
                "The raw path has been set — edit manually if needed.")
            self.ind_path_edit.setText(path)
        else:
            self.ind_path_edit.setText(pattern)

    def _apply_individual(self):
        vuid     = self.ind_ver_cb.currentText()
        new_path = self.ind_path_edit.text().strip()
        if not vuid or not new_path:
            QMessageBox.warning(self, "Missing Info",
                                "Please select a version and enter a path.")
            return
        feed = self.editor._get_feed(vuid)
        if feed is None:
            QMessageBox.critical(self, "Error", f"Feed not found for {vuid}.")
            return
        span = feed.find("spans/span")
        if span is not None:
            pe = span.find("path")
            if pe is not None:
                pe.text = new_path
        self.editor._mark_dirty()
        self.editor._populate_feed_details(self.editor._current_vuid)
        self._recheck_all()
        QMessageBox.information(self, "Done", f"Path updated for {vuid}.")


# ─── Preview Dialog ────────────────────────────────────────────────────────────

class PreviewDialog(QDialog):
    def __init__(self, parent, text):
        super().__init__(parent)
        self.setWindowTitle("Preview Changes")
        self.resize(720, 420)
        lay = QVBoxLayout(self)
        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setFont(QFont("Menlo, Consolas, Monospace", 11))
        txt.setPlainText(text)
        lay.addWidget(txt)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        lay.addWidget(close, alignment=Qt.AlignRight)
        self.exec_()


# ─── Flame integration helpers ────────────────────────────────────────────────

def _flame_refresh_mediahub():
    """Tell Flame to refresh the MediaHub after a save (no-op outside Flame)."""
    try:
        import flame
        flame.execute_shortcut("Refresh the MediaHub's Folders and Files")
    except Exception:
        pass


# ─── Flame hook ────────────────────────────────────────────────────────────────

_open_dialogs = []   # keep references so Qt doesn't GC non-modal windows


def _open_editor(selection):
    if _QT is None:
        print(f"\n[{SCRIPT_NAME}] ERROR: PySide2/PySide6 not found in this Python environment.")
        return

    for item in selection:
        try:
            clip_path = str(item.path)
        except AttributeError:
            continue
        if not clip_path.endswith('.clip') or not os.path.isfile(clip_path):
            continue
        dlg = OpenClipEditorDialog(clip_path)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.destroyed.connect(lambda obj=None, d=dlg: _open_dialogs.remove(d)
                               if d in _open_dialogs else None)
        _open_dialogs.append(dlg)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()


def _scope_clip(selection):
    for item in selection:
        try:
            if str(item.path).endswith('.clip'):
                return True
        except AttributeError:
            pass
    return False


def get_mediahub_files_custom_ui_actions():
    return [
        {
            'hierarchy': [SCRIPT_NAME],
            'actions': [
                {
                    'name': 'Open in OpenClip Editor',
                    'execute': _open_editor,
                    'isVisible': _scope_clip,
                    'minimumVersion': '2023.2',
                }
            ]
        }
    ]


# ─── Standalone entry point ────────────────────────────────────────────────────

if __name__ == "__main__":
    if _QT is None:
        print("PySide2 or PySide6 is required.  Install with:  pip install PySide6")
        sys.exit(1)
    app = QApplication.instance() or QApplication(sys.argv)
    clip = sys.argv[1] if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]) else None
    dlg  = OpenClipEditorDialog(clip)
    dlg.show()
    sys.exit(app.exec_() if _QT == 2 else app.exec())
