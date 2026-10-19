"""Main-window integration for the pyqtgraph image and histogram widgets."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np
from qtpy import QtCore, QtWidgets

from exhale.analysis.controller import AnalysisController
from exhale.data.elementsettings import Normalizers
from exhale.data.imagesettings import ImageSettings, Layouts, Scalebars
from exhale.imaging.histogramwidget import HistogramWidget
from exhale.imaging.imagecanvas import ImageCanvas
from exhale.imaging.imagecomposer import ColoredRasterPrimitive
from exhale.imaging.listwidgets import ElementListWidget
from exhale.main_window import MainWindow


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
        with patch.object(AnalysisController, "setup", lambda controller: None):
            self.window = MainWindow()
        self.addCleanup(self.dispose)
        self.window.source_manager.open_files([self.filename])

    def dispose(self):
        self.window.source_manager.close_source_handles()
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
        element = self.window.project_data.element_settings[ref]
        np.testing.assert_allclose(
            self.window.elementPlot.image_item.image, element.transformedData()
        )
        self.assertEqual(self.window.elementHistogramPlot.limits, tuple(element.trfRange))
        x, counts = self.window.elementHistogramPlot.curve.getData()
        self.assertEqual(len(x), 257)
        self.assertEqual(int(np.sum(counts)), self.data.size)

        new_minimum = float(sum(element.trfRange) / 2)
        self.window.elementHistogramPlot.minimum_marker.setValue(new_minimum)
        self.assertAlmostEqual(element.trfRange[0], new_minimum)
        self.assertAlmostEqual(self.window.elementNormalizeMin.value(), new_minimum)

    def test_transformation_minimum_accepts_zero_below_data_range(self):
        ref = self.select_element()
        element = self.window.project_data.element_settings[ref]
        self.assertGreater(element.dataRange[0], 0)

        self.window.elementNormalizeMin.setValue(0)

        self.assertEqual(element.trfRange[0], 0)
        self.assertEqual(self.window.elementNormalizeMin.value(), 0)
        self.assertEqual(self.window.elementHistogramPlot.limits[0], 0)

        self.window.elementNormalizer.setCurrentIndex(Normalizers.LOG.value)
        self.window.elementNormalizeMin.setValue(0)
        self.assertEqual(element.trfRange[0], 0)
        self.assertEqual(self.window.elementHistogramPlot.limits[0], 0)

    def test_composed_image_and_hover_use_canvas_coordinates(self):
        ref = self.select_element()
        element = self.window.project_data.element_settings[ref]
        image = ImageSettings("Composed")
        image.layout = Layouts.MERGED
        image.scalebar = Scalebars.NONE
        image.panelLabels = False
        image.elementLabels = False
        image.elements[0] = element.copy()
        self.window.project_data.images[1] = image
        self.window.imageList.addImage(1, image)
        self.window.imageList.setCurrentRow(0)
        self.app.processEvents()

        description = self.window.elementPlot.composition_description
        shown = next(
            primitive.array
            for primitive in reversed(description.primitives)
            if isinstance(primitive, ColoredRasterPrimitive)
        )
        self.assertEqual(shown.ndim, 2)
        mapping = self.window.image_controller.composer.coord_mapping
        with patch.object(QtWidgets.QToolTip, "showText") as show_text:
            self.window.elementPlot.pixelHovered.emit((mapping.x, mapping.y))
        show_text.assert_called_once()
        tooltip = show_text.call_args.args[1]
        self.assertIn("Pos (0, 0)", tooltip)
        self.assertIn(f"{self.data[0, 0]:.4g}", tooltip)

    def test_layout_and_element_changes_reset_composed_image_zoom(self):
        ref = self.select_element()
        sample, channel = self.window.project_data.channel_for_ref(ref)
        image = ImageSettings(
            "Composed", sample_id=sample.sample_id, sample_source_ids=sample.asset_ids
        )
        image.layout = Layouts.MERGED
        image.scalebar = Scalebars.NONE
        image.panelLabels = False
        image.elementLabels = False
        image.setElement(0, self.window.project_data.element_settings[ref], channel.key)
        self.window.project_data.images[1] = image
        self.window.imageList.addImage(1, image)
        self.window.imageElementBoxes[0].combo.addItem("Fe", ref)
        self.window.image_controller.show_image(1)
        self.window.image_controller.update_composed_image(reset_view=True)
        self.app.processEvents()
        self.assertTrue(self.window.imageElementBoxes[0].edit.isEnabled())
        self.assertFalse(self.window.imageElementBoxes[1].edit.isEnabled())

        canvas = self.window.elementPlot
        canvas._zoom(0.5)
        with patch.object(
            self.window.image_controller.composer,
            "display_composed_image",
            wraps=self.window.image_controller.composer.display_composed_image,
        ) as render:
            self.window.composeLayoutCB.setCurrentIndex(Layouts.IL.value)
            self.app.processEvents()
        render.assert_called_once()
        self.assertTrue(canvas.view_box.viewRect().contains(canvas.view_box.full_image_rect))

        canvas._zoom(0.5)
        with patch.object(
            self.window.image_controller.composer,
            "display_composed_image",
            wraps=self.window.image_controller.composer.display_composed_image,
        ) as render:
            self.window.imageElementBoxes[0].combo.setCurrentIndex(0)
            self.app.processEvents()
        render.assert_called_once()
        self.assertIsNone(canvas.image_item.image)
        self.assertFalse(self.window.imageElementBoxes[0].edit.isEnabled())

        combo = self.window.imageElementBoxes[0].combo
        combo.setCurrentIndex(combo.findData(ref))
        self.app.processEvents()
        self.assertTrue(canvas.view_box.viewRect().contains(canvas.view_box.full_image_rect))

    def test_image_element_override_is_explicit_and_reversible(self):
        ref = self.select_element()
        sample, channel = self.window.project_data.channel_for_ref(ref)
        global_settings = self.window.project_data.element_settings[ref]
        image = ImageSettings(
            "Composed", sample_id=sample.sample_id, sample_source_ids=sample.asset_ids
        )
        image.setElement(0, global_settings, channel.key)
        self.window.project_data.images[1] = image
        self.window.imageList.addImage(1, image)
        self.window.imageElementBoxes[0].combo.addItem("Fe", ref)
        self.window.image_controller.show_image(1)
        self.window.image_controller.update_composed_image()
        composed = self.window.elementPlot.composition_description

        self.window.imageElementBoxes[0].edit.click()
        self.assertEqual(self.window.imageElementBoxes[0].edit.text(), "Adjust")
        self.assertIs(self.window.image_controller.current_image, image)
        self.assertIsNotNone(self.window.elementPlot.composition_description)
        self.assertEqual(self.window.elementPlot.composition_description.size, composed.size)
        self.assertFalse(self.window.elementSettingsPanel.isHidden())
        self.assertFalse(self.window.showSingleElementButton.isHidden())
        self.assertFalse(self.window.showSingleElementButton.isChecked())
        self.assertIs(image.elements[0], global_settings)
        self.assertEqual(self.window.imageChannelNameLabel.text(), "Fe:")
        self.assertEqual(self.window.imageSettingsScopeCombo.currentText(), "Element map settings")
        scene_item_ids = [id(item) for item in self.window.elementPlot._composition_items]
        sample_gamma = global_settings.gamma + 0.25
        with patch.object(
            self.window.image_controller.composer,
            "display_composed_image",
            wraps=self.window.image_controller.composer.display_composed_image,
        ) as render:
            self.window.gammaValue.setValue(sample_gamma)
        render.assert_called_once()
        self.assertEqual(global_settings.gamma, sample_gamma)
        self.assertEqual(
            [id(item) for item in self.window.elementPlot._composition_items], scene_item_ids
        )

        self.window.showSingleElementButton.click()
        self.assertEqual(self.window.elementPlot.image_item.image.ndim, 2)
        self.assertIs(self.window.image_controller.current_image, image)
        self.window.showSingleElementButton.click()
        self.assertIsNotNone(self.window.elementPlot.composition_description)

        self.window.imageSettingsScopeCombo.setCurrentIndex(1)
        self.assertIsNot(image.elements[0], global_settings)
        self.assertIn(0, image.element_overrides)
        self.assertEqual(
            self.window.imageSettingsScopeCombo.currentText(), "Image-specific settings"
        )

        self.window.gammaValue.setValue(global_settings.gamma + 0.5)
        self.assertNotEqual(image.elements[0].gamma, global_settings.gamma)

        self.window.imageSettingsScopeCombo.setCurrentIndex(0)
        self.assertIs(image.elements[0], global_settings)
        self.assertNotIn(0, image.element_overrides)

        self.window.showSingleElementButton.click()
        self.assertEqual(self.window.elementPlot.image_item.image.ndim, 2)
        self.window.imageHeaderBox.edit.click()
        self.assertIsNone(self.window.element_controller.current_element)
        self.assertTrue(self.window.elementSettingsPanel.isHidden())
        self.assertIsNotNone(self.window.elementPlot.composition_description)
        self.assertTrue(self.window.showSingleElementButton.isChecked())


if __name__ == "__main__":
    unittest.main()
