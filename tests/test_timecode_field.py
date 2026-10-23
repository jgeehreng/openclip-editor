"""The single-field Start TC editor (TimecodeEdit) and its use in the editor."""
import xml.etree.ElementTree as ET

import pytest

from conftest import oce

try:
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
except ImportError:
    from PySide2.QtCore import QEvent
    from PySide2.QtGui import QKeyEvent

Qt = oce.Qt


def key(widget, k, text="", mods=Qt.NoModifier):
    ev = QKeyEvent(QEvent.KeyPress, k, mods, text)
    oce.QApplication.sendEvent(widget, ev)
    return ev.isAccepted()


def type_digits(widget, digits):
    for ch in digits:
        key(widget, getattr(Qt, f"Key_{ch}"), ch)


@pytest.fixture
def tc():
    w = oce.TimecodeEdit()
    w.set_format(24)
    w.set_ticks(86400)
    return w


def test_24fps_uses_plus(tc):
    assert tc.text() == "01:00:00+00"


def test_digits_fill_from_the_right(tc):
    tc.selectAll()
    type_digits(tc, "1000105")
    assert tc.text() == "01:00:01+05"
    key(tc, Qt.Key_Backspace)
    assert tc.text() == "00:10:00+10"


def test_nudge(tc):
    key(tc, Qt.Key_Up)
    assert tc.text() == "01:00:00+01"
    key(tc, Qt.Key_Down, mods=Qt.ShiftModifier)
    assert tc.text() == "00:59:59+01"


def test_letters_ignored_and_esc_reverts(tc):
    key(tc, Qt.Key_Up)
    key(tc, Qt.Key_A, "a")
    key(tc, Qt.Key_Colon, ":")
    assert tc.text() == "01:00:00+01"
    assert key(tc, Qt.Key_Escape)                 # consumed, so the window stays open
    assert tc.text() == "01:00:00+00"


def test_paste_reformats(tc):
    oce.QGuiApplication.clipboard().setText("10:20:30:12")
    key(tc, Qt.Key_V, "v", Qt.ControlModifier)
    assert tc.text() == "10:20:30+12"
    tc._paste("02;00;00;00")
    assert tc.text() == "02:00:00+00"


def test_invalid_turns_red(tc):
    tc.setText("00:00:00+30")
    assert tc.value() is None and "c0392b" in tc.styleSheet()
    tc.setText("00:00:00+23")
    assert tc.value() == (0, 0, 0, 23) and tc.styleSheet() == ""


def test_enter_emits_return_pressed(tc):
    fired = []
    tc.returnPressed.connect(lambda: fired.append(1))
    assert key(tc, Qt.Key_Return)
    assert fired


def test_drop_frame_field():
    w = oce.TimecodeEdit()
    w.set_format(30, True)
    w.set_ticks(107892)
    assert w.text() == "01:00:00;00"
    key(w, Qt.Key_Down)
    assert w.text() == "00:59:59;29"
    w.set_ticks(1799)
    key(w, Qt.Key_Up)
    assert w.text() == "00:01:00;02"
    w.setText("00:01:00;00")
    assert w.value() is None


def test_25fps_uses_colon():
    w = oce.TimecodeEdit()
    w.set_format(25)
    w.set_ticks(90000)
    assert w.text() == "01:00:00:00"


def test_in_editor(editor):
    dlg = editor()
    assert dlg.tc_edit.text() == "13:27:36+20"
    assert dlg.out_tc_label.text().startswith("13:27:38+08")
    dlg.tc_edit.setFocus()
    dlg.tc_edit.selectAll()
    type_digits(dlg.tc_edit, "1000000")
    assert dlg.out_tc_label.text().startswith("01:00:01+12")      # live preview
    assert dlg._pending_fields() == ["Start TC"]
    dlg.tc_edit.setText("01:00:00+99")
    assert not dlg.apply_tc_btn.isEnabled() and dlg.out_tc_label.text() == "—"
    dlg.tc_edit.setText("01:00:00+00")
    assert dlg.apply_tc_btn.isEnabled()
    key(dlg.tc_edit, Qt.Key_Return)
    assert dlg._get_feed("v01").findtext("startTimecode/nbTicks") == "86400"
    assert dlg._pending_fields() == []
    dlg.cmd_save()
    video = [t for t in ET.parse(dlg.clip_path).getroot().find("tracks")
             if t.findtext("trackType") == "video"][0]
    assert video.findtext("feeds/feed[@vuid='v01']/startTimecode/nbTicks") == "86400"


def test_df_clip_in_editor(editor):
    dlg = editor("df.clip")
    assert dlg.tc_edit.text() == "01:00:00;00"
    assert dlg.tc_info_label.text() == "DF  29.97 fps"


def test_esc_on_window_asks_first(editor, dialogs):
    dlg = editor()
    dlg._mark_dirty()
    dialogs.box = oce.QMessageBox.Cancel
    dlg.show()
    oce.QApplication.processEvents()
    key(dlg, Qt.Key_Escape)
    oce.QApplication.processEvents()
    assert dlg.isVisible()
    assert "box" in dialogs.kinds()
