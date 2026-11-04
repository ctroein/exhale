"""Native-canvas regression for fitting after deferred startup layout changes."""

import os
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(shutil.which("Xvfb") is None, reason="Requires an isolated X11/OpenGL display")
@pytest.mark.parametrize("scale", ["1", "2"])
def test_initial_fit_tracks_real_canvas_then_preserves_navigation(scale):
    code = r"""
import numpy as np
from qtpy import QtCore, QtTest, QtWidgets
from exhale.analysis.naparihelper import NapariHelper
from exhale.analysis.segmentation_viewer import SegmentationViewer

app = QtWidgets.QApplication([])

def settle():
    QtTest.QTest.qWait(150)
    app.processEvents()

for viewer_type in (NapariHelper, SegmentationViewer):
    host = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(host)
    helper = viewer_type()
    layout.addWidget(helper.qtwidget)
    host.resize(640, 480)
    # Data are present before the first visible layout, as when opening a project.
    helper.viewer.add_image(np.ones((100, 200)), colormap="red", contrast_limits=(0, 1))
    helper.viewer.reset_view(margin=0)
    host.show()
    settle()

    for width, height in ((640, 480), (900, 700), (450, 600)):
        # Include sizes reached well after the original one-shot startup fit.
        host.resize(width, height)
        settle()
        native = helper.qtwidget.canvas.native
        expected = min(native.width() / 200, native.height() / 100)
        camera = getattr(helper.viewer, "scene", helper.viewer).camera
        np.testing.assert_allclose(camera.zoom, expected)
        frame = helper.qtwidget.screenshot(flash=False)
        red = (frame[..., 0] > 240) & (frame[..., 1] < 10) & (frame[..., 2] < 10)
        occupied = np.count_nonzero(red[frame.shape[0] // 2])
        expected_width = min(frame.shape[1], frame.shape[0] * 2)
        assert abs(occupied - expected_width) <= 2, (occupied, expected_width)

    # A navigation event ends startup fitting; subsequent resizes and tab-like
    # hide/show transitions must preserve the user's camera setting.
    QtTest.QTest.keyClick(native, QtCore.Qt.Key_Left)
    camera.zoom *= 0.7
    zoom = camera.zoom
    host.resize(800, 500)
    settle()
    np.testing.assert_allclose(camera.zoom, zoom)
    host.hide()
    host.show()
    settle()
    np.testing.assert_allclose(camera.zoom, zoom)

    # Reopening another project in the same viewer starts fitting afresh.
    host.hide()
    helper.reset_initial_fit()
    host.resize(700, 650)
    host.show()
    settle()
    expected = min(native.width() / 200, native.height() / 100)
    np.testing.assert_allclose(camera.zoom, expected)
    helper.qtwidget.close()
    host.close()
"""
    server = subprocess.Popen(
        ["Xvfb", "-displayfd", "1", "-screen", "0", "1920x1200x24"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        display = server.stdout.readline().strip()
        assert display, "Xvfb did not provide a display"
        env = {
            **os.environ,
            "DISPLAY": f":{display}",
            "QT_QPA_PLATFORM": "xcb",
            "QT_SCALE_FACTOR": scale,
        }
        subprocess.run([sys.executable, "-c", code], env=env, check=True, timeout=45)
    finally:
        server.terminate()
        server.wait(timeout=5)
