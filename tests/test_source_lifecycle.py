"""Headless regression tests for file handling.

Run: QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
Napari initialization is skipped; real Qt controls and source readers are used.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import h5py
import numpy as np
from PIL import Image
from qtpy import QtCore, QtWidgets

from exhale import projectio
from exhale.elementsettings import ElementSettings
from exhale.exhalewindow import ExhaleWindow
from exhale.imagesettings import ImageSettings


class SourceLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = np.arange(1, 13, dtype=np.uint16).reshape(3, 4)
        self.h5 = str(Path(self.temp.name) / "elements.h5")
        with h5py.File(self.h5, "w") as f:
            f.attrs["default"] = "entry"
            group = f.create_group("entry/plotselect")
            group.create_dataset("Fe", data=self.data)
            group.create_dataset("Zn", data=self.data * 2)
        self.tiff = str(Path(self.temp.name) / "image.tiff")
        Image.fromarray(self.data).save(self.tiff)
        with patch.object(ExhaleWindow, "create_analysisTab",
                          lambda win: setattr(win, "naparihelper", None)):
            self.win = ExhaleWindow()
        self.addCleanup(self.dispose_window)

    def dispose_window(self):
        self.win.close_all_files()
        self.win.deleteLater()
        self.app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)

    def test_tabs_and_file_actions(self):
        tabs = self.win.tabWidget
        self.assertEqual([tabs.tabText(i) for i in range(tabs.count())],
                         ["Data && Visualization", "Image analysis", "Correlative"])
        self.assertEqual(tabs.currentIndex(), 0)
        tabs.setCurrentWidget(self.win.analysisTab)
        self.assertIs(tabs.currentWidget(), self.win.analysisTab)
        with patch.object(self.win, "askFileName", return_value=[self.h5]):
            self.win.actionOpenFile.trigger()
        self.assertTrue(self.win.fileSettings[self.h5].is_open)
        self.win.actionClearFiles.trigger()
        self.assertFalse(self.win.fileSettings[self.h5].is_open)
        self.assertEqual(self.win.loadedFileComboBox.count(), 0)

    def test_action_icons_have_fallbacks(self):
        for name in ("actionOpenFile", "actionClearFiles", "actionLoadProject",
                     "actionSaveProject", "actionAbout", "actionQuit"):
            with self.subTest(action=name):
                self.assertFalse(getattr(self.win, name).icon().isNull())

    def test_open_close_reopen_hdf5_and_tiff(self):
        self.win.open_files([self.h5, self.tiff])
        self.assertEqual(self.win.loadedFileComboBox.count(), 2)
        self.assertEqual(self.win.elementList.count(), 1)
        for filename, count in ((self.h5, 2), (self.tiff, 1)):
            source = self.win.fileSettings[filename]
            self.assertEqual(len(source.list_elements()), count)
            ref = source.list_elements()[0].ref
            np.testing.assert_array_equal(source.load_array(ref), self.data)
            self.win.close_source(filename)
            self.assertFalse(source.is_open)
            self.assertIsNone(source.handle)
            self.win.close_source(filename)  # repeated close is harmless
            self.win.open_files([filename])
            reopened = self.win.fileSettings[filename]
            self.assertIsNot(reopened, source)
            np.testing.assert_array_equal(reopened.load_array(ref), self.data)
        self.win.close_all_files()
        self.assertEqual(self.win.loadedFileComboBox.count(), 0)
        self.assertTrue(all(not s.is_open for s in self.win.fileSettings.values()))

    def test_close_preserves_materialized_elements_and_image_copies(self):
        self.win.open_files([self.h5])
        source = self.win.fileSettings[self.h5]
        candidate = source.list_elements()[0]
        element = ElementSettings(ref=candidate.ref, data=source.load_array(candidate.ref))
        self.win.elementSettings[candidate.ref] = element
        image = ImageSettings("Retained image")
        image.elements[0] = element.copy()
        self.win.imageSettings[1] = image
        self.win.close_source(self.h5)
        np.testing.assert_array_equal(element.data, self.data)
        np.testing.assert_array_equal(image.elements[0].data, self.data)
        image.elements[0].trfRange[0] = 5
        self.assertNotEqual(element.trfRange[0], 5)
        self.assertIs(self.win.elementSettings[candidate.ref], element)

    def test_refresh_excludes_closed_sources_and_does_not_duplicate(self):
        self.win.open_files([self.h5, self.tiff])
        self.win.close_source(self.tiff)
        for _ in range(2):
            self.win.refresh_project_ui()
            self.assertEqual(self.win.loadedFileComboBox.count(), 1)
            self.assertEqual(self.win.elementList.count(), 2)
            self.assertIs(self.win.loadedFileComboBox.currentData(),
                          self.win.fileSettings[self.h5])

    def test_project_roundtrip_sources_aliases_and_analysis_settings(self):
        self.win.open_files([self.h5, self.tiff])
        self.win.fileSettings[self.h5].alias = "Scan A"
        self.win.fileSettings[self.tiff].alias = "Image B"
        self.win.clusterNInit.setValue(7)
        filename = Path(self.temp.name) / "sources.xhp"
        projectio.save_project(self.win, filename)
        old_sources = list(self.win.fileSettings.values())
        with patch.object(self.win.errorMsg, "showMessage") as error:
            self.win.load_project_file(str(filename))
            error.assert_not_called()
        self.assertTrue(all(not s.is_open for s in old_sources))
        self.assertEqual(self.win.loadedFileComboBox.count(), 2)
        self.assertEqual(self.win.fileSettings[self.h5].alias, "Scan A")
        self.assertEqual(self.win.fileSettings[self.tiff].alias, "Image B")
        self.assertEqual(self.win.clusterNInit.value(), 7)
        self.win.clear_project()
        self.assertFalse(self.win.fileSettings)
        self.assertFalse(self.win.elementSettings)
        self.assertFalse(self.win.imageSettings)
        self.assertEqual(self.win.elementList.count(), 0)

    def test_mixed_project_restores_elements_and_independent_image_settings(self):
        self.win.open_files([self.h5, self.tiff])
        image = ImageSettings("Mixed sources")
        for slot, filename in enumerate((self.h5, self.tiff)):
            source = self.win.fileSettings[filename]
            ref = source.list_elements()[0].ref
            element = ElementSettings(ref=ref, data=source.load_array(ref),
                                      name=f"Element {slot}")
            self.win.elementSettings[ref] = element
            self.win.selectedElements.add(ref)
            image.elements[slot] = element.copy()
            image.elements[slot].name = f"Local {slot}"
            image.elements[slot].trfRange = [2, 9]
        self.win.imageSettings = {1: image}
        path = Path(self.temp.name) / "mixed.xhp"
        projectio.save_project(self.win, path)
        with patch.object(self.win.errorMsg, "showMessage") as error:
            self.win.load_project_file(str(path))
            error.assert_not_called()
        self.assertEqual(len(self.win.selectedElements), 2)
        restored = self.win.imageSettings[1]
        for slot, local in restored.elements.items():
            global_element = self.win.elementSettings[local.ref]
            self.assertEqual(local.name, f"Local {slot}")
            self.assertEqual(global_element.name, f"Element {slot}")
            self.assertIsNot(local, global_element)
            self.assertEqual(local.trfRange, [2, 9])
            original_range = global_element.trfRange.copy()
            local.trfRange[0] = 4
            self.assertEqual(global_element.trfRange, original_range)
            np.testing.assert_array_equal(local.data, self.data)
        self.win.close_all_files()
        for local in restored.elements.values():
            np.testing.assert_array_equal(local.data, self.data)

    def test_duplicate_open_closes_unused_handle(self):
        from exhale.source_refs import open_source
        for filename in (self.h5, self.tiff):
            self.win.open_files([filename])
            original = self.win.fileSettings[filename]
            duplicate = open_source(filename)
            with patch("exhale.exhalewindow.open_source", return_value=duplicate):
                self.win.open_files([filename])
            self.assertFalse(duplicate.is_open)
            self.assertIs(self.win.fileSettings[filename], original)
            self.assertTrue(original.is_open)
        self.assertEqual(self.win.loadedFileComboBox.count(), 2)
