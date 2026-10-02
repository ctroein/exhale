"""Main-window integration for the pyqtgraph image and histogram widgets."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import h5py
import numpy as np
from qtpy import QtCore, QtWidgets

from exhale.exhalewindow import ExhaleWindow
from exhale.histogramwidget import HistogramWidget
from exhale.imagecanvas import ImageCanvas
from exhale.imagesettings import ImageSettings, Layouts, Scalebars
from exhale.listwidgets import ElementListWidget


class PlotIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = np.arange(1, 21, dtype=np.float64).reshape(4, 5)
        self.filename = str(Path(self.temp.name) / "elements.h5")
        with h5py.File(self.filename, "w") as handle:
            handle.attrs["default"] = "entry"
            handle.create_dataset("entry/plotselect/Fe", data=self.data)
        with patch.object(ExhaleWindow, "create_analysisTab",
                          lambda window: setattr(window, "naparihelper", None)):
            self.window = ExhaleWindow()
        self.addCleanup(self.dispose)
        self.window.open_files([self.filename])

    def dispose(self):
        self.window.close_all_files()
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)

    def select_element(self):
        item = self.window.elementList.item(0)
        self.window.elementList.setCurrentItem(item)
        self.app.processEvents()
        return item.data(ElementListWidget.ELEMENT_REF_ROLE)

    def test_generated_ui_uses_new_widgets(self):
        self.assertIsInstance(self.window.elementPlot, ImageCanvas)
        self.assertIsInstance(self.window.elementHistogramPlot, HistogramWidget)

    def test_element_selection_populates_image_histogram_and_markers(self):
        ref = self.select_element()
        element = self.window.elementSettings[ref]
        np.testing.assert_allclose(
            self.window.elementPlot.image_item.image,
            element.transformedData())
        self.assertEqual(
            self.window.elementHistogramPlot.limits,
            tuple(element.trfRange))
        x, counts = self.window.elementHistogramPlot.curve.getData()
        self.assertEqual(len(x), 257)
        self.assertEqual(int(np.sum(counts)), self.data.size)

        new_minimum = float(sum(element.trfRange) / 2)
        self.window.elementHistogramPlot.minimum_marker.setValue(new_minimum)
        self.assertAlmostEqual(element.trfRange[0], new_minimum)
        self.assertAlmostEqual(
            self.window.elementNormalizeMin.value(), new_minimum)

    def test_composed_image_and_hover_use_canvas_coordinates(self):
        ref = self.select_element()
        element = self.window.elementSettings[ref]
        image = ImageSettings("Composed")
        image.layout = Layouts.MERGED
        image.scalebar = Scalebars.NONE
        image.panelLabels = False
        image.elementLabels = False
        image.elements[0] = element.copy()
        self.window.imageSettings[1] = image
        self.window.imageList.addImage(1, image)
        self.window.imageList.setCurrentRow(0)
        self.app.processEvents()

        shown = self.window.elementPlot.image_item.image
        self.assertEqual(shown.ndim, 3)
        self.assertEqual(shown.shape[2], 4)
        mapping = self.window.imageComposer.coord_mapping
        with patch.object(QtWidgets.QToolTip, "showText") as show_text:
            self.window.elementPlot.pixelHovered.emit((mapping.x, mapping.y))
        show_text.assert_called_once()
        tooltip = show_text.call_args.args[1]
        self.assertIn("Pos (0, 0)", tooltip)
        self.assertIn(f"{self.data[0, 0]:.4g}", tooltip)

    def test_layout_and_element_changes_reset_composed_image_zoom(self):
        ref = self.select_element()
        image = ImageSettings("Composed")
        image.layout = Layouts.MERGED
        image.scalebar = Scalebars.NONE
        image.panelLabels = False
        image.elementLabels = False
        image.elements[0] = self.window.elementSettings[ref].copy()
        self.window.imageSettings[1] = image
        self.window.imageList.addImage(1, image)
        self.window.imageElementBoxes[0].combo.addItem("Fe", ref)
        self.window.showComposedImage(1)
        self.window.updateComposedImage(reset_view=True)
        self.app.processEvents()

        canvas = self.window.elementPlot
        canvas._zoom(0.5)
        self.window.composeLayoutCB.setCurrentIndex(Layouts.IL.value)
        self.app.processEvents()
        self.assertTrue(canvas.view_box.viewRect().contains(
            canvas.image_item.boundingRect()))

        canvas._zoom(0.5)
        self.window.imageElementBoxes[0].combo.setCurrentIndex(0)
        self.app.processEvents()
        self.assertIsNone(canvas.image_item.image)

        combo = self.window.imageElementBoxes[0].combo
        combo.setCurrentIndex(combo.findData(ref))
        self.app.processEvents()
        self.assertTrue(canvas.view_box.viewRect().contains(
            canvas.image_item.boundingRect()))


if __name__ == "__main__":
    unittest.main()
