"""Fix Paths: prefix vs anywhere matching, scope, batch setups, spans, frame counts."""
import xml.etree.ElementTree as ET

import pytest

from conftest import oce

JOB = "/jobs/DEMO_Job/SHOTS/sh010"


@pytest.fixture
def fix(editor):
    dlg = editor()
    return dlg, oce.FixPathsDialog(dlg)


def all_paths(dlg):
    return sorted(elem.text for _v, _l, _k, elem in oce.FixPathsDialog(dlg)._path_targets())


def test_targets_cover_tracks_and_batch_setups(fix):
    _dlg, fp = fix
    labels = sorted((label, kind) for _v, label, kind, _e in fp._path_targets())
    assert labels == [("v00", "batch"), ("v00", "feed"), ("v00 (audio)", "feed"),
                      ("v01", "batch"), ("v01", "feed"), ("v01 (audio)", "feed")]


def test_prefix_match_only_at_start(fix):
    dlg, fp = fix
    fp.find_edit.setText("SHOTS/")
    fp.replace_edit.setText("X/")
    assert fp._planned_changes() == []           # "SHOTS/" is mid-path
    fp.anywhere_cb.setChecked(True)
    assert len(fp._planned_changes()) == 6


def test_prefix_replace_all_including_batch(fix, dialogs):
    dlg, fp = fix
    fp.find_edit.setText("/jobs/")
    fp.replace_edit.setText("/Volumes/vfx/")
    fp._apply_replace()
    assert all(p.startswith("/Volumes/vfx/DEMO_Job/") for p in all_paths(dlg))
    assert dlg._dirty
    assert ("info", "Done") in dialogs.log


def test_batch_setups_can_be_excluded(fix):
    dlg, fp = fix
    fp.find_edit.setText("/jobs/")
    fp.replace_edit.setText("/mnt/")
    fp.batch_cb.setChecked(False)
    fp._apply_replace()
    batch = [e.text for _v, _l, kind, e in fp._path_targets() if kind == "batch"]
    feeds = [e.text for _v, _l, kind, e in fp._path_targets() if kind == "feed"]
    assert all(p.startswith("/jobs/") for p in batch)
    assert all(p.startswith("/mnt/") for p in feeds)


def test_preview_matches_apply_for_selected_scope(fix, monkeypatch):
    dlg, fp = fix
    shown = []
    monkeypatch.setattr(oce, "PreviewDialog", lambda parent, text: shown.append(text))
    fp.find_edit.setText("/jobs/")
    fp.replace_edit.setText("/mnt/")
    fp.scope_sel.setChecked(True)                 # current version is v01
    fp._preview_replace()
    assert shown and "v00" not in shown[0] and "v01" in shown[0]
    planned = [(label, kind) for label, kind, *_ in fp._planned_changes()]
    fp._apply_replace()
    changed = sorted((label, kind) for _v, label, kind, e in fp._path_targets()
                     if e.text.startswith("/mnt/"))
    assert changed == sorted(planned) == [("v01", "batch"), ("v01", "feed"),
                                          ("v01 (audio)", "feed")]


def test_every_span_is_replaced(editor, clip_copy):
    path = clip_copy()
    tree = ET.parse(path)
    video = [t for t in tree.getroot().find("tracks") if t.findtext("trackType") == "video"][0]
    spans = video.find("feeds/feed[@vuid='v01']/spans")
    extra = ET.fromstring(ET.tostring(spans.find("span")))
    extra.find("path").text = f"{JOB}/Plates/v01b/sh010.[1037-1050].exr"
    spans.append(extra)
    tree.write(path)
    dlg = oce.OpenClipEditorDialog(path)
    oce._open_dialogs.append(dlg)
    fp = oce.FixPathsDialog(dlg)
    labels = [label for _v, label, _k, _e in fp._path_targets()]
    assert "v01 span 1" in labels and "v01 span 2" in labels
    fp.find_edit.setText("/jobs/")
    fp.replace_edit.setText("/mnt/")
    fp._apply_replace()
    edited = dlg._get_feed("v01").findall("spans/span/path")
    assert len(edited) == 2 and all(p.text.startswith("/mnt/") for p in edited)


def make_frames(folder, frames, pad=4):
    folder.mkdir(parents=True, exist_ok=True)
    for f in frames:
        (folder / f"sh010.{f:0{pad}d}.exr").write_bytes(b"")


def test_count_frames(tmp_path):
    seq = tmp_path / "plates"
    make_frames(seq, range(1001, 1037))
    assert oce.count_frames(str(seq / "sh010.[1001-1036].exr")) == (36, 36)
    (seq / "sh010.1010.exr").unlink()
    assert oce.count_frames(str(seq / "sh010.[1001-1036].exr")) == (35, 36)
    assert oce.count_frames(str(tmp_path / "nope" / "sh010.[1001-1036].exr")) == (0, 36)
    make_frames(tmp_path / "pad", range(1, 11), pad=6)      # any padding counts
    assert oce.count_frames(str(tmp_path / "pad" / "sh010.[1-10].exr")) == (10, 10)
    movie = tmp_path / "ref.mov"
    movie.write_bytes(b"")
    assert oce.count_frames(str(movie)) == (1, 1)
    assert oce.count_frames(str(tmp_path / "missing.mov")) == (0, 1)


def test_validation_statuses(editor, clip_copy, tmp_path):
    path = clip_copy()
    tree = ET.parse(path)
    video = [t for t in tree.getroot().find("tracks") if t.findtext("trackType") == "video"][0]
    for vuid in ("v00", "v01"):
        video.find(f"feeds/feed[@vuid='{vuid}']/spans/span/path").text = \
            str(tmp_path / vuid / "sh010.[1001-1036].exr")
    tree.write(path)
    make_frames(tmp_path / "v00", range(1001, 1037))
    make_frames(tmp_path / "v01", range(1001, 1020))
    dlg = oce.OpenClipEditorDialog(path)
    oce._open_dialogs.append(dlg)
    fp = oce.FixPathsDialog(dlg)
    rows = {}
    for i in range(fp.val_tree.topLevelItemCount()):
        item = fp.val_tree.topLevelItem(i)
        rows[(item.text(0), item.text(1))] = item.text(3)
    assert rows[("v00", "feed")] == "✓ OK  36/36"
    assert rows[("v01", "feed")] == "⚠ PARTIAL  19/36"
    assert rows[("v00 (audio)", "feed")] == "✗ MISSING"
    assert rows[("v00", "batch")] == "✗ MISSING"
