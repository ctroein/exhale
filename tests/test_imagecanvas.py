"""Image display invariants, including rendering and array orientation."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
import numpy as np
from qtpy import QtCore, QtGui, QtTest, QtWidgets

from exhale.imagecanvas import ImageCanvas


class ImageCanvasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.canvas = ImageCanvas()
        self.canvas.resize(360, 240)
        self.canvas.show()
        self.app.processEvents()
        self.addCleanup(self.dispose)

    def dispose(self):
        self.canvas.close()
        self.canvas.deleteLater()
        self.app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)

    def rendered_pixel(self, row, column):
        self.app.processEvents()
        scene = self.canvas.image_item.mapToScene(
            QtCore.QPointF(column + 0.5, row + 0.5))
        point = self.canvas.mapFromScene(scene)
        pixmap = self.canvas.viewport().grab()
        ratio = pixmap.devicePixelRatio()
        return pixmap.toImage().pixelColor(round(point.x() * ratio),
                                          round(point.y() * ratio)).getRgb()

    def test_grayscale_levels_are_fixed_and_image_is_not_flipped(self):
        data = np.array([[0.2, 0.4, 0.6], [0.8, 1, 0]], dtype=np.float32)
        self.canvas.set_image(data)
        for row in range(2):
            for column in range(3):
                expected = round(float(data[row, column]) * 255)
                color = self.rendered_pixel(row, column)
                for channel in color[:3]:
                    self.assertAlmostEqual(channel, expected, delta=1)
        top = self.canvas.image_item.mapToScene(QtCore.QPointF(0.5, 0.5))
        bottom = self.canvas.image_item.mapToScene(QtCore.QPointF(0.5, 1.5))
        self.assertLess(top.y(), bottom.y())

    def test_rgba_switching_preserves_colors(self):
        self.canvas.set_image(np.ones((2, 3)))
        data = np.array([[[255, 0, 0, 255], [0, 255, 0, 255], [0, 0, 255, 255]],
                         [[25, 50, 75, 255], [200, 100, 50, 255], [0, 0, 0, 255]]],
                        dtype=np.uint8)
        self.canvas.set_image(data)
        for row in range(2):
            for column in range(3):
                self.assertEqual(self.rendered_pixel(row, column), tuple(data[row, column]))
        self.canvas.set_image(np.full((2, 3), 0.5))
        self.assertAlmostEqual(self.rendered_pixel(0, 0)[0], 127, delta=1)

    def test_pixel_geometry_and_owned_array(self):
        data = np.arange(24, dtype=float).reshape(4, 6)[:, ::2] / 24
        self.canvas.set_image(data)
        self.assertEqual(self.canvas.image_item.boundingRect(), QtCore.QRectF(0, 0, 3, 4))
        self.assertTrue(self.canvas.image_item.image.flags.c_contiguous)
        expected = data.copy()
        data[:] = 0
        np.testing.assert_array_equal(self.canvas.image_item.image, expected)
        x = self.canvas.image_item.mapToScene(QtCore.QPointF(1, 0))
        y = self.canvas.image_item.mapToScene(QtCore.QPointF(0, 1))
        origin = self.canvas.image_item.mapToScene(QtCore.QPointF(0, 0))
        self.assertAlmostEqual(x.x() - origin.x(), y.y() - origin.y())

    def test_updates_preserve_view_and_clear_resets(self):
        self.canvas.set_image(np.zeros((10, 20)))
        self.canvas.view_box.setRange(xRange=(2, 8), yRange=(3, 7), padding=0)
        before = self.canvas.view_box.viewRange()
        self.canvas.set_image(np.ones((10, 20)))
        np.testing.assert_allclose(self.canvas.view_box.viewRange(), before)
        self.canvas.clear_image()
        self.assertIsNone(self.canvas.image_item.image)
        self.canvas.set_image(np.zeros((4, 6)))
        bounds = self.canvas.view_box.viewRect()
        self.assertTrue(bounds.contains(QtCore.QRectF(0, 0, 6, 4)))

    def test_invalid_input_does_not_replace_image(self):
        self.canvas.set_image(np.zeros((2, 3)))
        for data in (np.zeros((0, 3)), np.zeros(3), np.zeros((2, 3, 3)),
                     np.zeros((2, 3, 4), dtype=float), np.full((2, 3), 'text')):
            with self.subTest(shape=data.shape), self.assertRaises(ValueError):
                self.canvas.set_image(data)
        self.assertEqual(self.canvas.image_item.image.shape, (2, 3))

    def test_keyboard_pan_zoom_and_fit(self):
        self.canvas.set_image(np.zeros((100, 200)))
        self.canvas.view_box.setRange(xRange=(50, 150), yRange=(25, 75), padding=0)
        self.canvas.setFocus()
        self.app.processEvents()

        before = np.asarray(self.canvas.view_box.viewRange())
        QtTest.QTest.keyClick(self.canvas, QtCore.Qt.Key.Key_Right)
        after_pan = np.asarray(self.canvas.view_box.viewRange())
        self.assertGreater(after_pan[0].mean(), before[0].mean())
        self.assertAlmostEqual(after_pan[1].mean(), before[1].mean())

        QtTest.QTest.keyClick(self.canvas, QtCore.Qt.Key.Key_Up)
        after_up = np.asarray(self.canvas.view_box.viewRange())
        self.assertLess(after_up[1].mean(), after_pan[1].mean())

        QtTest.QTest.keyClick(self.canvas, QtCore.Qt.Key.Key_Plus)
        after_zoom = np.asarray(self.canvas.view_box.viewRange())
        self.assertLess(np.diff(after_zoom[0])[0], np.diff(after_up[0])[0])
        self.assertLess(np.diff(after_zoom[1])[0], np.diff(after_up[1])[0])

        QtTest.QTest.keyClick(self.canvas, QtCore.Qt.Key.Key_Minus)
        after_out = np.asarray(self.canvas.view_box.viewRange())
        np.testing.assert_allclose(
            np.diff(after_out, axis=1), np.diff(after_up, axis=1), rtol=1e-12)

        QtTest.QTest.keyClick(self.canvas, QtCore.Qt.Key.Key_Home)
        self.assertTrue(self.canvas.view_box.viewRect().contains(
            QtCore.QRectF(0, 0, 200, 100)))

    def test_zoom_out_stops_at_fitted_view(self):
        self.canvas.set_image(np.zeros((100, 200)))
        fitted = np.asarray(self.canvas.view_box.viewRange())

        self.canvas._zoom(1.25)
        np.testing.assert_allclose(
            self.canvas.view_box.viewRange(), fitted, rtol=1e-12, atol=1e-12)

        self.canvas._zoom(0.8)
        self.canvas._zoom(2)
        np.testing.assert_allclose(
            self.canvas.view_box.viewRange(), fitted, rtol=1e-12, atol=1e-12)

    def test_panning_stops_at_image_edges_and_centers_padding(self):
        self.canvas.set_image(np.zeros((100, 200)))

        for zoom in (1, 0.8, 0.5):
            self.canvas.fit_image()
            self.canvas._zoom(zoom)
            self.canvas.view_box.translateBy(x=10000, y=10000)
            ranges = self.canvas.view_box.viewRange()
            for limits, image_size in zip(ranges, (200, 100)):
                span = limits[1] - limits[0]
                if span >= image_size:
                    self.assertAlmostEqual(sum(limits) / 2, image_size / 2)
                else:
                    self.assertGreaterEqual(limits[0], -1e-12)
                    self.assertLessEqual(limits[1], image_size + 1e-12)

    def test_fit_button_is_visible_and_restores_full_image(self):
        self.canvas.set_image(np.zeros((20, 40)))
        self.assertTrue(self.canvas.fit_button.isVisible())
        self.assertGreaterEqual(self.canvas.fit_button.x(), 0)
        self.canvas.view_box.setRange(xRange=(10, 20), yRange=(5, 10), padding=0)
        QtTest.QTest.mouseClick(
            self.canvas.fit_button, QtCore.Qt.MouseButton.LeftButton)
        self.assertTrue(self.canvas.view_box.viewRect().contains(
            QtCore.QRectF(0, 0, 40, 20)))

    def test_left_drag_pans(self):
        self.canvas.set_image(np.zeros((100, 200)))
        self.canvas.view_box.setRange(xRange=(50, 150), yRange=(25, 75), padding=0)
        self.app.processEvents()
        viewport = self.canvas.viewport()
        start = viewport.rect().center()
        before = np.asarray(self.canvas.view_box.viewRange())
        QtTest.QTest.mousePress(
            viewport, QtCore.Qt.MouseButton.LeftButton, pos=start)
        end = start + QtCore.QPoint(30, 15)
        move = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseMove, QtCore.QPointF(end),
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier)
        QtWidgets.QApplication.sendEvent(viewport, move)
        QtTest.QTest.mouseRelease(
            viewport, QtCore.Qt.MouseButton.LeftButton,
            pos=end)
        self.app.processEvents()
        after = np.asarray(self.canvas.view_box.viewRange())
        self.assertFalse(np.allclose(after, before))

    def test_wheel_zooms_around_pointer(self):
        self.canvas.set_image(np.zeros((100, 200)))
        self.canvas.view_box.setRange(xRange=(0, 200), yRange=(0, 100), padding=0)
        self.app.processEvents()
        viewport = self.canvas.viewport()
        pos = QtCore.QPointF(viewport.rect().center())
        before = np.asarray(self.canvas.view_box.viewRange())
        event = QtGui.QWheelEvent(
            pos, self.canvas.mapToGlobal(pos.toPoint()), QtCore.QPoint(),
            QtCore.QPoint(0, 120), QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
            QtCore.Qt.ScrollPhase.ScrollUpdate, False)
        QtWidgets.QApplication.sendEvent(viewport, event)
        self.app.processEvents()
        after = np.asarray(self.canvas.view_box.viewRange())
        self.assertLess(np.diff(after[0])[0], np.diff(before[0])[0])
        self.assertLess(np.diff(after[1])[0], np.diff(before[1])[0])

    def test_pixel_mapping_is_exact_after_pan_and_zoom(self):
        self.canvas.set_image(np.zeros((17, 23)))
        self.canvas.view_box.setRange(
            xRange=(3.25, 11.75), yRange=(4.5, 10.5), padding=0)
        self.canvas.view_box.scaleBy((0.63, 0.63), center=(7.5, 7.5))
        self.canvas.view_box.translateBy(x=1.125, y=-0.75)
        self.app.processEvents()

        for x, y in ((0, 0), (5, 8), (22, 16)):
            scene = self.canvas.image_item.mapToScene(
                QtCore.QPointF(x + 0.5, y + 0.5))
            self.assertEqual(self.canvas.pixel_at_scene(scene), (x, y))
            viewport = self.canvas.mapFromScene(scene)
            self.assertEqual(self.canvas.pixel_at_viewport(viewport), (x, y))

        for point in ((-0.001, 0), (0, -0.001), (23, 0), (0, 17)):
            scene = self.canvas.image_item.mapToScene(QtCore.QPointF(*point))
            self.assertIsNone(self.canvas.pixel_at_scene(scene))
