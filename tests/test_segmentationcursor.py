"""Brush preview paths match the editing rasterizer without changing labels."""

import numpy as np
import pytest
from qtpy import QtCore

from exhale.analysis.segmentationcursor import brush_path
from exhale.data.segmentationediting import SegmentationEditSession


@pytest.mark.parametrize("size", [1, 2, 3, 4, 5, 12])
@pytest.mark.parametrize("position", [(7.1, 8.2), (0.1, 0.2), (-1.2, 8.1), (19.8, 19.9)])
def test_preview_footprint_matches_brush_pixels_including_image_edges(size, position):
    shape = (20, 20)
    path = brush_path(shape, position, size)
    expected = SegmentationEditSession.brush_mask(shape, [position], size)
    actual = np.array(
        [[path.contains(QtCore.QPointF(x, y)) for x in range(shape[1])] for y in range(shape[0])]
    )
    np.testing.assert_array_equal(actual, expected)
    if not path.isEmpty():
        bounds = path.boundingRect()
        assert bounds.left() >= -0.5 and bounds.top() >= -0.5
        assert bounds.right() <= shape[1] - 0.5 and bounds.bottom() <= shape[0] - 0.5


def test_native_cursor_lifecycle_and_stationary_modifiers():
    """Exercise actual Qt cursor updates and clean teardown on an isolated display."""
    import os
    import shutil
    import subprocess
    import sys

    if shutil.which("Xvfb") is None:
        pytest.skip("Requires an isolated X11/OpenGL display")
    code = r"""
import numpy as np
from qtpy import QtCore, QtTest, QtWidgets
from exhale.analysis.segmentation_viewer import SegmentationViewer
from exhale.data.projectdata import SegmentationResult
from exhale.data.segmentation import SegmentationOutput, SegmentationParameters
from exhale.data.segmentationediting import SegmentationEditSession
from exhale.data.segmentationhistory import SegmentationCandidate
from exhale.data.source_refs import ElementRef

app = QtWidgets.QApplication([])
host = QtWidgets.QWidget()
layout = QtWidgets.QVBoxLayout(host)
helper = SegmentationViewer()
layout.addWidget(helper.qtwidget)
result = SegmentationResult('sample', 'stardist', ElementRef('source', '/P'),
    SegmentationParameters(), SegmentationOutput(np.ones((100, 100), dtype=np.uint32), 'model', '1'))
session = SegmentationEditSession(SegmentationCandidate.from_result(result))
helper.set_result(result, np.arange(10000).reshape(100,100), edit_session=session)
host.resize(600, 500)
host.show()
host.activateWindow()
QtTest.QTest.qWait(200)
native = helper.qtwidget.canvas.native
native.setFocus()
overlay = helper._editing_cursor
point = native.rect().center()
helper.set_edit_tool('add')
helper.set_brush_size(2)
QtTest.QTest.mouseMove(native, point)
QtTest.QTest.qWait(60)
assert overlay.isVisible()
assert overlay._paint_tool == 'add'
QtTest.QTest.keyPress(native, QtCore.Qt.Key_Control)
assert overlay._paint_tool == 'add' and helper.edit_tool == 'add'
QtTest.QTest.keyRelease(native, QtCore.Qt.Key_Control)
assert overlay._paint_tool == 'add'
QtTest.QTest.mousePress(native, QtCore.Qt.RightButton, pos=point)
assert overlay._paint_tool == 'remove' and helper.edit_tool == 'add'
QtTest.QTest.mouseRelease(native, QtCore.Qt.RightButton, pos=point)
assert overlay._paint_tool == 'add'
zoom = helper.viewer.scene.camera.zoom
assert abs(overlay._path.boundingRect().width() - 2 * zoom) < 1e-6
QtTest.QTest.mouseMove(native, QtCore.QPoint(-10, -10))
QtTest.QTest.qWait(40)
assert not overlay.isVisible()
QtTest.QTest.mouseMove(native, point)
QtTest.QTest.qWait(40)
assert overlay.isVisible()
helper.set_edit_tool('draw')
assert not overlay.isVisible()
QtTest.QTest.keyPress(native, QtCore.Qt.Key_Shift)
assert overlay._base_cursor is not None
plus = native.cursor().pixmap().toImage()
QtTest.QTest.keyRelease(native, QtCore.Qt.Key_Shift)
assert overlay._base_cursor is None
QtTest.QTest.keyPress(native, QtCore.Qt.Key_Control)
minus = native.cursor().pixmap().toImage()
assert not plus.isNull() and not minus.isNull() and plus != minus
QtTest.QTest.keyRelease(native, QtCore.Qt.Key_Control)
assert overlay._base_cursor is None
# Area drags are consumed before Napari can pan or point-select.
helper.set_edit_tool('select')
selected = []
helper.rectangle_selection_callback = lambda corners, additive: selected.append(
    (session.rectangle_ids(corners), additive))
center = tuple(helper.viewer.scene.camera.center)
start, end = point - QtCore.QPoint(8, 8), point + QtCore.QPoint(8, 8)
QtTest.QTest.mousePress(native, QtCore.Qt.LeftButton, QtCore.Qt.ShiftModifier, pos=start)
QtTest.QTest.mouseMove(native, end)
QtTest.QTest.qWait(60)
assert overlay._selection_rect is not None and overlay.isVisible()
assert overlay._ant_timer.isActive()
QtTest.QTest.mouseRelease(native, QtCore.Qt.LeftButton, QtCore.Qt.ShiftModifier, pos=end)
assert selected == [({1}, False)]
assert overlay._selection_rect is None and not overlay._ant_timer.isActive()
assert tuple(helper.viewer.scene.camera.center) == center
mods = QtCore.Qt.ShiftModifier | QtCore.Qt.ControlModifier
QtTest.QTest.mousePress(native, QtCore.Qt.LeftButton, mods, pos=end)
QtTest.QTest.mouseMove(native, start)
QtTest.QTest.qWait(60)
QtTest.QTest.mouseRelease(native, QtCore.Qt.LeftButton, mods, pos=start)
assert selected[-1] == ({1}, True)
QtTest.QTest.mousePress(native, QtCore.Qt.LeftButton, mods, pos=start)
QtTest.QTest.mouseMove(native, end)
QtTest.QTest.qWait(60)
QtTest.QTest.keyClick(native, QtCore.Qt.Key_Escape)
assert overlay._selection_rect is None and not overlay._ant_timer.isActive()
QtTest.QTest.mouseRelease(native, QtCore.Qt.LeftButton, mods, pos=end)
assert len(selected) == 2
assert not session.changed and not session.can_undo
# Hiding unregisters the global key observer; showing restores it.
host.hide()
assert not overlay._watching_keys
host.show()
QtTest.QTest.qWait(30)
assert overlay._watching_keys
helper.qtwidget.close()
assert not overlay._watching_keys
host.close()
"""
    server = subprocess.Popen(
        ["Xvfb", "-displayfd", "1", "-screen", "0", "1600x1100x24"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        display = server.stdout.readline().strip()
        assert display
        env = {
            **os.environ,
            "DISPLAY": f":{display}",
            "QT_QPA_PLATFORM": "xcb",
            "QT_SCALE_FACTOR": "1",
        }
        subprocess.run([sys.executable, "-c", code], env=env, check=True, timeout=35)
    finally:
        server.terminate()
        server.wait(timeout=5)
