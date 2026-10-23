"""Editor window: multi-track edits, saving, un-applied edits, close behaviour."""
import os
import stat
import xml.etree.ElementTree as ET

from conftest import DATA, oce

try:
    from PySide6.QtGui import QCloseEvent
except ImportError:
    from PySide2.QtGui import QCloseEvent


def reparse(dlg):
    return ET.parse(dlg.clip_path).getroot()


def feed_on(root, track_type, vuid):
    for track in root.find("tracks"):
        if track.findtext("trackType") == track_type:
            for feed in track.find("feeds"):
                if feed.get("vuid") == vuid:
                    return feed


def test_primary_track_is_video_even_when_audio_is_first(editor):
    dlg = editor()
    assert dlg.track_type_label.text() == "video"
    assert dlg._current_vuid == "v01"
    assert dlg.tc_info_label.text() == "NDF  23.976 fps"


def test_typing_clip_name_marks_dirty(editor):
    dlg = editor()
    dlg.clip_name_edit.setText("renamed")
    dlg.clip_name_edit.textEdited.emit("renamed")
    assert dlg._dirty


def test_timecode_applies_to_every_track(editor):
    dlg = editor()
    dlg.tc_edit.setText("01:00:00+00")
    dlg._apply_timecode()
    ticks = [f.findtext("startTimecode/nbTicks") for f in dlg._get_feeds_for_version("v01")]
    assert ticks == ["86400", "86400"]


def test_unapplied_path_is_applied_on_save(editor, dialogs):
    dlg = editor()
    new = "/new/place/sh010.[1001-1036].exr"
    dlg.feed_path_edit.setText(new)
    dlg.clip_name_edit.setText("renamed")
    assert dlg._pending_fields() == ["Path"]
    assert dlg.cmd_save() is True
    assert any(kind == "question" and "Unapplied" in title for kind, title in dialogs.log)
    root = reparse(dlg)
    assert feed_on(root, "video", "v01").findtext("spans/span/path") == new
    assert root.findtext("name") == "renamed"


def test_atomic_save_keeps_mode_and_one_backup(editor, tmp_path):
    dlg = editor()
    original = open(dlg.clip_path, "rb").read()
    dlg._mark_dirty()
    dlg.cmd_save()
    assert open(dlg.clip_path + ".bak", "rb").read() == original
    assert stat.S_IMODE(os.stat(dlg.clip_path).st_mode) == 0o664
    assert not [n for n in os.listdir(tmp_path) if n.endswith(".tmp")]
    dlg.ver_name_edit.setText("hero")
    dlg._apply_version_name()
    dlg.cmd_save()
    assert open(dlg.clip_path + ".bak", "rb").read() == original   # still pre-session
    assert reparse(dlg).find("versions/version[@uid='v01']/name").text == "hero"


def test_remove_version_drops_feeds_on_every_track(editor):
    dlg = editor()
    dlg._select_version_in_table("v01")
    dlg.cmd_remove_version()
    dlg.cmd_save()
    root = reparse(dlg)
    left = sorted((t.get("uid"), f.get("vuid")) for t in root.find("tracks")
                  for f in t.find("feeds"))
    assert left == [("a0", "v00"), ("v0", "v00")]
    current = {fs.get("currentVersion") for fs in root.iter("feeds")}
    assert current | {root.find("versions").get("currentVersion")} == {"v00"}


def test_apply_creates_missing_colour_space(editor):
    dlg = editor()
    sf = dlg._get_feed("v01").find("storageFormat")
    sf.remove(sf.find("colourSpace"))
    dlg._populate_feed_details("v01")
    dlg.color_edit.setCurrentText("ACEScg")
    dlg._apply_color_space()
    assert dlg._get_feed("v01").findtext("storageFormat/colourSpace") == "ACEScg"


def test_apply_path_without_path_element_warns(editor, dialogs):
    dlg = editor()
    span = dlg._get_feed("v01").find("spans/span")
    span.remove(span.find("path"))
    dlg._apply_feed_path()
    assert not dlg._dirty
    assert "warning" in dialogs.kinds()


def test_failed_save_keeps_window_and_file(editor, dialogs, tmp_path):
    dlg = editor()
    before = open(dlg.clip_path, "rb").read()
    dlg._mark_dirty()
    os.chmod(tmp_path, 0o555)
    try:
        ev = QCloseEvent()
        dlg.closeEvent(ev)
    finally:
        os.chmod(tmp_path, 0o755)
    assert not ev.isAccepted()
    assert "critical" in dialogs.kinds()
    assert open(dlg.clip_path, "rb").read() == before


def test_close_cancel_and_discard(editor, dialogs):
    dlg = editor()
    dlg._mark_dirty()
    dialogs.box = oce.QMessageBox.Cancel
    ev = QCloseEvent()
    dlg.closeEvent(ev)
    assert not ev.isAccepted()
    dialogs.box = oce.QMessageBox.Discard
    ev = QCloseEvent()
    dlg.closeEvent(ev)
    assert ev.isAccepted()


def test_unedited_save_preserves_content(editor):
    dlg = editor()
    assert dlg._pending_fields() == []
    dlg._dirty = True
    dlg.cmd_save()
    squash = lambda root: b"".join(ET.tostring(root).split())
    assert squash(reparse(dlg)) == squash(ET.parse(os.path.join(DATA, "multitrack.clip")).getroot())


def test_new_clip_does_not_show_previous_labels(editor, clip_copy):
    dlg = editor()
    assert dlg.flame_ver_label.text() == "2027.1"
    path = clip_copy("df.clip")
    tree = ET.parse(path)
    root = tree.getroot()
    root.remove(root.find("userData"))
    track = root.find("tracks/track")
    track.remove(track.find("editRate"))
    track.remove(track.find("trackType"))
    tree.write(path)
    dlg._load_file(path)
    assert dlg.flame_ver_label.text() == "—"
    assert dlg.module_label.text() == "—"
    assert dlg.edit_rate_label.text() == "—"
    assert dlg.track_type_label.text() == "—"


def test_multi_span_feed_shows_warning(editor, clip_copy):
    path = clip_copy()
    tree = ET.parse(path)
    spans = [t for t in tree.getroot().find("tracks")
             if t.findtext("trackType") == "video"][0].find("feeds/feed[@vuid='v01']/spans")
    spans.append(ET.fromstring(ET.tostring(spans.find("span"))))
    tree.write(path)
    dlg = oce.OpenClipEditorDialog(path)
    oce._open_dialogs.append(dlg)
    assert not dlg.span_warn_label.isHidden()
    assert "2 spans" in dlg.span_warn_label.text()
    dlg._select_version_in_table("v00")
    assert dlg.span_warn_label.isHidden()
