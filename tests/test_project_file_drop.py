"""External file drops use the normal project import and never move source files."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import Mock

import h5py
import numpy as np
import pytest
from PIL import Image
from qtpy import QtCore, QtGui, QtWidgets

from exhale.main_window import MainWindow


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    class LocalSettings(QtCore.QSettings):
        def __init__(self, *args, **kwargs):
            super().__init__(str(tmp_path / "settings.ini"), self.IniFormat)

    monkeypatch.setattr(QtCore, "QSettings", LocalSettings)
    window = MainWindow(initialize_analysis_view=False)
    window.show_error = Mock()
    window.resize(1100, 750)
    window.show()
    app.processEvents()
    yield window
    window.source_manager.close_source_handles()
    window.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def source_file(path):
    """Write a minimal valid HDF5 element-map source."""
    with h5py.File(path, "w") as handle:
        handle.attrs["default"] = "entry"
        handle.create_dataset("entry/plotselect/Fe", data=np.arange(12).reshape(3, 4))
    return path


def drag_event(window, urls, *, drop=True, actions=None):
    """Send external drag/drop events through the sample tree's viewport."""
    actions = actions or QtCore.Qt.CopyAction | QtCore.Qt.MoveAction
    mime = QtCore.QMimeData()
    mime.setUrls(urls)
    viewport = window.sampleTree.viewport()
    enter = QtGui.QDragEnterEvent(
        QtCore.QPoint(10, 10), actions, mime, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier
    )
    QtWidgets.QApplication.sendEvent(viewport, enter)
    if not drop or not enter.isAccepted():
        return enter
    move = QtGui.QDragMoveEvent(
        QtCore.QPoint(10, 10), actions, mime, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier
    )
    QtWidgets.QApplication.sendEvent(viewport, move)
    assert move.isAccepted()
    assert move.dropAction() == QtCore.Qt.CopyAction
    event = QtGui.QDropEvent(
        QtCore.QPointF(10, 10), actions, mime, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier
    )
    QtWidgets.QApplication.sendEvent(viewport, event)
    return event


def test_drop_imports_new_sample_even_when_an_existing_row_is_selected(window, tmp_path):
    first = source_file(tmp_path / "first.h5")
    window.source_manager.open_files([str(first)])
    original_sample = next(iter(window.project_data.samples))
    second = source_file(tmp_path / "sample with spaces µ.h5")
    url = QtCore.QUrl.fromLocalFile(str(second))
    enter = drag_event(window, [url], drop=False)
    assert enter.isAccepted()
    assert enter.dropAction() == QtCore.Qt.CopyAction
    assert len(window.project_data.samples) == 1

    drop = drag_event(window, [url])
    assert drop.isAccepted()
    assert drop.dropAction() == QtCore.Qt.CopyAction
    assert len(window.project_data.samples) == 2
    assert len(window.project_data.samples[original_sample].asset_ids) == 1
    assert second.is_file()
    assert window.project_state_manager.compare_now()
    window.show_error.assert_not_called()


def test_multiple_tiffs_drop_as_one_sample_and_duplicates_are_not_reimported(window, tmp_path):
    files = [tmp_path / "calcium.tiff", tmp_path / "iron.tiff"]
    for path in files:
        Image.fromarray(np.arange(12, dtype=np.uint16).reshape(3, 4)).save(path)
    urls = [QtCore.QUrl.fromLocalFile(str(path)) for path in files]
    assert drag_event(window, urls).isAccepted()
    assert len(window.project_data.samples) == 1
    assert len(window.project_data.assets) == 2
    assert drag_event(window, urls).isAccepted()
    assert len(window.project_data.samples) == 1
    assert len(window.project_data.assets) == 2
    window.show_error.assert_not_called()


def test_drop_rejects_directories_remote_urls_and_move_only_sources(window, tmp_path):
    source = source_file(tmp_path / "valid.h5")
    local = QtCore.QUrl.fromLocalFile(str(source))
    for urls in (
        [QtCore.QUrl.fromLocalFile(str(tmp_path))],
        [QtCore.QUrl("https://example.com/sample.h5")],
        [local, QtCore.QUrl.fromLocalFile(str(tmp_path / "missing.h5"))],
    ):
        assert not drag_event(window, urls).isAccepted()
    assert not drag_event(window, [local], actions=QtCore.Qt.MoveAction).isAccepted()
    assert not window.project_data.samples


def test_invalid_file_reports_error_and_does_not_block_other_dropped_files(window, tmp_path):
    bad = tmp_path / "invalid.h5"
    bad.write_text("Invalid sample")
    good = source_file(tmp_path / "valid.h5")
    urls = [QtCore.QUrl.fromLocalFile(str(path)) for path in (bad, good)]
    assert drag_event(window, urls).isAccepted()
    assert len(window.project_data.samples) == 1
    window.show_error.assert_called_once()
