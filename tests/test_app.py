"""Standalone app: Finder file-open events and quitting with unsaved changes."""
import os

from conftest import APP, DATA, oce

try:
    from PySide6.QtCore import QEvent, QTimer
    from PySide6.QtGui import QFileOpenEvent
except ImportError:
    from PySide2.QtCore import QEvent, QTimer
    from PySide2.QtGui import QFileOpenEvent


def titles():
    return sorted(d.windowTitle() for d in oce._open_dialogs)


def test_file_open_and_quit(clip_copy, dialogs):
    first, second = clip_copy("multitrack.clip"), clip_copy("df.clip")
    results = {}

    def run():
        results["launch"] = titles()
        oce.QApplication.sendEvent(APP, QFileOpenEvent(first))
        results["first"] = titles()
        oce.QApplication.sendEvent(APP, QFileOpenEvent(second))
        results["second"] = len(oce._open_dialogs)
        oce._open_dialogs[0]._mark_dirty()
        dialogs.box = oce.QMessageBox.Cancel
        oce.QApplication.sendEvent(APP, QEvent(QEvent.Quit))
        APP.processEvents()
        results["after_cancel"] = sum(d.isVisible() for d in oce._open_dialogs)
        dialogs.box = oce.QMessageBox.Discard
        QTimer.singleShot(3000, lambda: APP.exit(3))         # safety net
        oce.QApplication.sendEvent(APP, QEvent(QEvent.Quit))

    QTimer.singleShot(800, run)          # after main()'s 500 ms empty-window fallback
    rc = oce.main(["openclip"])

    assert results["launch"] == ["OpenClip Editor"]
    assert results["first"] == [f"OpenClip Editor — {os.path.basename(first)}"]
    assert results["second"] == 2
    assert results["after_cancel"] >= 1
    assert rc == 0
