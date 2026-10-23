"""Shared fixtures: load the editor module headlessly and auto-answer its dialogs."""
import importlib.util
import os
import shutil

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "tests", "data")

_spec = importlib.util.spec_from_file_location(
    "openclip_editor", os.path.join(ROOT, "flame_hook", "openclip_editor.py"))
oce = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oce)

if oce._QT is None:
    pytest.exit("PySide6 or PySide2 is required to run the tests", returncode=1)

APP = oce.QApplication.instance() or oce._EditorApp([])


class Dialogs:
    """Stands in for QMessageBox: records what was shown and returns preset answers."""

    def __init__(self):
        self.question = oce.QMessageBox.Yes     # answer to QMessageBox.question
        self.box = oce.QMessageBox.Save          # answer to QMessageBox(...).exec()
        self.log = []                            # [(kind, title_or_text)]

    def kinds(self):
        return [kind for kind, _ in self.log]


@pytest.fixture(autouse=True)
def dialogs(monkeypatch):
    d = Dialogs()
    QMB = oce.QMessageBox

    def recorder(kind, answer=None):
        def show(*args, **kwargs):
            d.log.append((kind, args[1] if len(args) > 1 else ""))
            return answer() if answer else None
        return staticmethod(show)

    monkeypatch.setattr(QMB, "question", recorder("question", lambda: d.question))
    monkeypatch.setattr(QMB, "warning", recorder("warning"))
    monkeypatch.setattr(QMB, "critical", recorder("critical"))
    monkeypatch.setattr(QMB, "information", recorder("info"))

    def exec_box(self):
        d.log.append(("box", self.text()))
        return d.box
    monkeypatch.setattr(QMB, "exec", exec_box, raising=False)
    monkeypatch.setattr(QMB, "exec_", exec_box, raising=False)
    monkeypatch.setattr(oce, "_flame_refresh_mediahub", lambda: None)
    yield d
    for dlg in list(oce._open_dialogs):
        dlg._dirty = False
        dlg._feed_snapshot = None      # skip the unapplied-edits prompt
        dlg.close()
    oce._open_dialogs.clear()


@pytest.fixture
def clip_copy(tmp_path):
    """Copy a clip from tests/data into a temp folder and return its path."""
    def copy(name="multitrack.clip"):
        dst = tmp_path / name
        shutil.copy(os.path.join(DATA, name), dst)
        os.chmod(dst, 0o664)
        return str(dst)
    return copy


@pytest.fixture
def editor(clip_copy):
    """An editor window on a fresh copy of multitrack.clip."""
    def open_editor(name="multitrack.clip"):
        dlg = oce.OpenClipEditorDialog(clip_copy(name))
        oce._open_dialogs.append(dlg)
        return dlg
    return open_editor
