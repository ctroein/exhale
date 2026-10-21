"""Headless regression tests for file handling.

Run: QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
Napari initialization is skipped; real Qt controls and source readers are used.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import h5py
import numpy as np
from PIL import Image
from qtpy import QtCore, QtTest, QtWidgets

from exhale import icons
from exhale.analysis.controller import AnalysisController
from exhale.analysis.correlations import correlation_matrix
from exhale.data.elementsettings import ElementSettings, ElementSettingsDefaults, Normalizers
from exhale.data.imagesettings import ImageSettings, Layouts
from exhale.data.projectdata import (
    SampleChannelState,
    SegmentationParameters,
    SegmentationResult,
)
from exhale.data.source_refs import open_source
from exhale.imaging.listwidgets import ElementListWidget, SampleElementCheckDelegate
from exhale.main_window import ACTIVE_TAB_SETTINGS_KEY, SPLITTER_SETTINGS_PREFIX, MainWindow
from exhale.project import projectio
from exhale.project.projectstatemanager import PROJECT_SAVE_ON_EXIT_KEY
from exhale.widgets import IconCheckDelegate


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
        self.multichannel_tiff = str(Path(self.temp.name) / "rgb-image.tiff")
        rgb_data = np.stack((self.data, self.data * 2, self.data * 3), axis=-1).astype(np.uint8)
        Image.fromarray(rgb_data).save(self.multichannel_tiff)
        with patch.object(AnalysisController, "setup", lambda controller: None):
            self.win = MainWindow()
        self.addCleanup(self.dispose_window)

    def dispose_window(self):
        self.win.source_manager.close_source_handles()
        self.win.deleteLater()
        self.app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)

    def test_tabs_and_file_actions(self):
        tabs = self.win.tabWidget
        self.assertEqual(
            [tabs.tabText(i) for i in range(tabs.count())],
            ["Project data", "Element maps", "Segmentation", "Correlations"],
        )
        self.assertEqual(tabs.currentIndex(), 0)
        tabs.setCurrentWidget(self.win.analysisTab)
        self.assertIs(tabs.currentWidget(), self.win.analysisTab)
        with patch.object(self.win, "askFileName", return_value=[self.h5]):
            self.win.actionOpenFile.trigger()
        self.assertTrue(self.win.project_data.sources[self.h5].is_open)
        self.assertEqual(self.win.loadedFileComboBox.count(), 1)

    def test_element_correlations_reuse_the_session_cache(self):
        self.win.source_manager.open_files([self.h5])
        sample_id = next(iter(self.win.project_data.samples))
        for key in ("Fe", "Zn"):
            self.win.project_data.add_project_channel_from_sample(sample_id, key)

        with patch(
            "exhale.analysis.correlation_controller.correlation_matrix",
            wraps=correlation_matrix,
        ) as calculate:
            self.win.channelsChanged.emit()
            self.assertIsNone(self.win.correlation_controller.element_matrix.result)
            self.win.correlation_controller.calculate_elements()
            result = self.win.correlation_controller.element_matrix.result
            self.win.correlation_controller.calculate_elements()

        self.assertEqual(calculate.call_count, 1)
        self.assertEqual(result.values.shape, (2, 2))
        np.testing.assert_allclose(result.values, np.ones((2, 2)))

        self.win.correlation_controller.copy_table()
        self.assertEqual(
            QtWidgets.QApplication.clipboard().text(),
            "\tFe\tZn\nFe\t1\t1\nZn\t1\t1",
        )

        self.win.correlation_controller._show_pair(0, 1)
        self.assertIs(self.win.correlationModes.currentWidget(), self.win.elementScatterTab)
        self.assertEqual(self.win.elementScatterX.currentData(), "Zn")
        self.assertEqual(self.win.elementScatterY.currentData(), "Fe")

        self.win.correlationModes.setCurrentWidget(self.win.sampleSimilarityTab)
        self.assertIs(self.win.correlation_controller.element_matrix.result, result)

    def test_active_tab_is_restored_from_global_settings_without_dirtying_project(self):
        settings = self.win.settings
        had_value = settings.contains(ACTIVE_TAB_SETTINGS_KEY)
        previous = settings.value(ACTIVE_TAB_SETTINGS_KEY)
        self.addCleanup(
            lambda: (
                settings.setValue(ACTIVE_TAB_SETTINGS_KEY, previous)
                if had_value
                else settings.remove(ACTIVE_TAB_SETTINGS_KEY)
            )
        )
        settings.setValue(ACTIVE_TAB_SETTINGS_KEY, self.win.dataTab.objectName())

        self.win._restore_active_tab()

        self.assertIs(self.win.tabWidget.currentWidget(), self.win.dataTab)
        self.assertFalse(self.win.project_state_manager.is_dirty)

    def test_all_main_window_splitters_are_saved_as_application_state(self):
        settings = self.win.settings
        expected_names = {
            "project_data",
            "splitter",
            "analysis",
            "analysis_left",
            "analysis_right",
            "element_correlations",
            "element_scatter",
            "sample_similarities",
        }
        self.assertEqual(set(self.win._splitter_initializers), expected_names)
        previous = {}
        for name in expected_names:
            key = f"{SPLITTER_SETTINGS_PREFIX}/{name}"
            previous[key] = (settings.contains(key), settings.value(key))

        def restore_settings():
            for initializer in self.win._splitter_initializers.values():
                initializer.initialized = False
            for key, (existed, value) in previous.items():
                if existed:
                    settings.setValue(key, value)
                else:
                    settings.remove(key)

        self.addCleanup(restore_settings)
        for index, initializer in enumerate(self.win._splitter_initializers.values(), start=1):
            initializer.initialized = True
            initializer.splitter.setSizes(
                [index * (pane + 1) * 100 for pane in range(initializer.splitter.count())]
            )

        self.win._save_splitter_states()

        for name, initializer in self.win._splitter_initializers.items():
            key = f"{SPLITTER_SETTINGS_PREFIX}/{name}"
            self.assertEqual(settings.value(key), initializer.splitter.saveState())

    def test_tiff_decoder_dependency_error_is_explained_and_import_is_rolled_back(self):
        error = ValueError("<COMPRESSION.LZW: 5> requires the 'imagecodecs' package")

        with (
            patch("exhale.data.source_refs.LoadedSource.load_array", side_effect=error),
            patch.object(QtWidgets.QMessageBox, "warning") as warning,
            patch.object(
                self.win.project_data,
                "register_source",
                wraps=self.win.project_data.register_source,
            ) as register_source,
        ):
            self.win.source_manager.open_files([self.tiff])

        register_source.assert_called_once()
        self.assertNotIn(self.tiff, self.win.project_data.assets)
        self.assertFalse(self.win.project_data.samples)
        _parent, title, message = warning.call_args.args
        self.assertEqual(title, "Cannot read TIFF file")
        self.assertIn("optional Python package imagecodecs", message)
        self.assertIn(self.tiff, message)
        self.assertNotIn("Traceback", message)

    def test_unreadable_tiff_does_not_block_enabling_hdf5_element(self):
        self.win.source_manager.open_files([self.h5])
        tiff_source = open_source(self.tiff)
        tiff_sample = self.win.project_data.register_source(tiff_source)
        tiff_channel = next(iter(tiff_sample.channels.values()))
        self.win.project_data.add_project_channel(tiff_channel.key, tiff_channel.name)
        tiff_source.load_array = Mock(
            side_effect=ValueError("<COMPRESSION.LZW: 5> requires the 'imagecodecs' package")
        )
        tiff_channel.data_source.release_cache()
        self.win.project_tab.refresh_channels()
        hdf5_item = next(
            self.win.channelList.item(row)
            for row in range(self.win.channelList.count())
            if self.win.channelList.item(row).data(ElementListWidget.CHANNEL_KEY_ROLE) == "Fe"
        )

        with patch.object(QtWidgets.QMessageBox, "warning") as warning:
            hdf5_item.setCheckState(QtCore.Qt.CheckState.Checked)
            self.assertIn("Fe", self.win.project_data.project_channels)
            hdf5_item.setCheckState(QtCore.Qt.CheckState.Unchecked)

        self.assertNotIn("Fe", self.win.project_data.project_channels)
        self.assertTrue(self.win.element_controller.has_settings_failure(tiff_channel.ref))
        warning.assert_called_once()

    def test_image_element_is_suspended_and_restored_with_channel_selection(self):
        self.win.source_manager.open_files([self.h5])
        sample = self.win.element_controller.current_sample()
        channels = sample.channels
        settings = {
            key: self.win.element_controller.ensure_settings(channel.ref)
            for key, channel in channels.items()
        }
        for key, channel in channels.items():
            self.win.project_data.add_project_channel(key, channel.name, settings[key])

        image = ImageSettings(
            "Composed", sample_id=sample.sample_id, sample_source_ids=sample.asset_ids
        )
        image.setElement(0, settings["Fe"], "Fe")
        image.createElementOverride(0).name = "Image iron"
        image.setElement(1, settings["Zn"], "Zn")
        self.win.project_data.images = {1: image}
        self.win.element_controller.effective_channels_changed()

        self.win.project_data.remove_project_channel("Fe")
        self.win.element_controller.effective_channels_changed()

        self.assertNotIn(0, image.elements)
        suspended, key, overridden = image.suspended_elements[0]
        self.assertEqual((suspended.name, key, overridden), ("Image iron", "Fe", True))
        for box in self.win.imageElementBoxes:
            self.assertEqual(
                self.win.image_controller.combo_index_for_data(box.combo, settings["Fe"].ref),
                -1,
            )
        serialized = projectio._imagesettings_to_json(1, image)
        self.assertNotIn("suspended_elements", serialized)
        restored = projectio._imagesettings_from_json(serialized, self.win.project_data)
        self.assertNotIn(0, restored.elements)
        self.assertIs(restored.elements[1], settings["Zn"])
        self.assertFalse(restored.suspended_elements)

        self.win.project_data.add_project_channel("Fe", "Fe", settings["Fe"])
        self.win.element_controller.effective_channels_changed()

        self.assertEqual(image.elements[0].name, "Image iron")
        self.assertIn(0, image.element_overrides)
        self.assertNotIn(0, image.suspended_elements)

        self.win.project_data.remove_project_channel("Fe")
        self.win.element_controller.effective_channels_changed()
        image.setElement(0, settings["Zn"], "Zn")
        self.win.project_data.add_project_channel("Fe", "Fe", settings["Fe"])
        self.win.element_controller.effective_channels_changed()

        self.assertIs(image.elements[0], settings["Zn"])
        self.assertNotIn(0, image.suspended_elements)

    def test_committing_unchanged_sample_path_closes_editor_without_reopening(self):
        self.win.source_manager.open_files([self.h5])
        tree = self.win.sampleTree
        file_item = tree.topLevelItem(0).child(0)
        source = self.win.project_data.assets[self.h5].source
        handle = source.handle

        tree.setCurrentItem(file_item)
        tree.editItem(file_item, 0)
        self.app.processEvents()
        editor = tree.findChild(QtWidgets.QLineEdit)
        self.assertIsNotNone(editor)
        QtTest.QTest.keyClick(editor, QtCore.Qt.Key_Return)
        QtTest.QTest.qWait(10)

        file_item = tree.topLevelItem(0).child(0)
        self.assertEqual(file_item.text(0), Path(self.h5).name)
        self.assertIs(source.handle, handle)

    def test_sample_tree_and_sample_elements_separate_files_from_maps(self):
        self.win.source_manager.open_files([self.h5, self.tiff, self.multichannel_tiff])
        tree = self.win.sampleTree
        hdf5_sample = tree.topLevelItem(0)
        hdf5_file = hdf5_sample.child(0)
        tiff_sample = tree.topLevelItem(1)
        tiff_file = tiff_sample.child(0)
        multichannel_tiff_file = tiff_sample.child(1)

        self.assertFalse(self.win.mapsPane.isHidden())
        self.assertEqual(hdf5_file.childCount(), 0)
        self.assertEqual(tiff_file.childCount(), 0)
        self.assertEqual(tiff_file.text(1), "image")
        self.assertEqual(
            hdf5_file.icon(0).cacheKey(), icons.icon(icons.IconName.FILE_DATA).cacheKey()
        )
        self.assertEqual(
            tiff_file.icon(0).cacheKey(), icons.icon(icons.IconName.ELEMENT).cacheKey()
        )
        self.assertEqual(
            multichannel_tiff_file.icon(0).cacheKey(),
            icons.icon(icons.IconName.FILE_MULTICHANNEL_IMAGE).cacheKey(),
        )

        tree.setCurrentItem(hdf5_sample)
        self.app.processEvents()
        self.assertEqual(self.win.mapsLabel.text(), "Sample elements")
        self.assertEqual(
            {
                self.win.elementMapList.item(row).data(ElementListWidget.CHANNEL_KEY_ROLE)
                for row in range(self.win.elementMapList.count())
            },
            {"Fe", "Zn"},
        )

        map_item = self.win.elementMapList.item(0)
        key = map_item.data(ElementListWidget.CHANNEL_KEY_ROLE)
        sample_id = hdf5_sample.data(0, self.win.project_tab.NODE_ID_ROLE)
        sample = self.win.project_data.samples[sample_id]
        if key not in sample.channel_overrides:
            expected_state = SampleChannelState.OVERRIDE
        elif sample.channel_overrides[key] is not None:
            expected_state = SampleChannelState.SKIP
        else:
            expected_state = (
                SampleChannelState.INHERIT
                if key in self.win.project_data.project_channels
                else SampleChannelState.SKIP
            )
        self.win.elementMapList.setCurrentItem(map_item)
        QtTest.QTest.keyClick(self.win.elementMapList, QtCore.Qt.Key_Space)
        self.assertEqual(
            self.win.project_data.sample_channel_state(sample_id, key),
            expected_state,
        )

    def test_sample_element_state_cycles_only_when_its_indicator_is_clicked(self):
        self.win.source_manager.open_files([self.h5])
        element_list = self.win.elementMapList
        element_list.setCurrentRow(0)
        item = element_list.currentItem()
        sample_id = self.win.project_tab.selected_sample_id()
        key = item.data(ElementListWidget.CHANNEL_KEY_ROLE)
        initial = self.win.project_data.sample_channel_state(sample_id, key)
        delegate = element_list.itemDelegate()
        self.assertIsInstance(delegate, SampleElementCheckDelegate)
        self.assertEqual(item.checkState(), QtCore.Qt.CheckState.PartiallyChecked)
        self.assertTrue(item.icon().isNull())
        index = element_list.indexFromItem(item)
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = element_list.visualRect(index)
        option.widget = element_list
        delegate.initStyleOption(option, index)
        option = delegate._style_option(option, index)

        QtTest.QTest.mouseClick(
            element_list.viewport(),
            QtCore.Qt.MouseButton.LeftButton,
            pos=delegate.indicator_rect(option, index).center(),
        )
        cycled = self.win.project_data.sample_channel_state(sample_id, key)
        self.assertNotEqual(cycled, initial)

        item = element_list.currentItem()
        row_rect = element_list.visualItemRect(item)
        QtTest.QTest.mouseClick(
            element_list.viewport(),
            QtCore.Qt.MouseButton.LeftButton,
            pos=QtCore.QPoint(row_rect.right() - 2, row_rect.center().y()),
        )
        self.assertEqual(self.win.project_data.sample_channel_state(sample_id, key), cycled)

    def test_reloading_icons_does_not_replace_project_files(self):
        self.win.source_manager.open_files([self.h5])

        with patch.object(self.win.source_manager, "replace_project_asset_path") as replace:
            icons.initialize()
            self.win.project_tab.reload_icons()
            self.app.processEvents()

        replace.assert_not_called()

    def test_refresh_preserves_existing_expansion_and_expands_new_samples(self):
        self.win.source_manager.open_files([self.h5])
        tree = self.win.sampleTree
        original_sample_id = tree.topLevelItem(0).data(0, self.win.project_tab.NODE_ID_ROLE)
        tree.topLevelItem(0).setExpanded(True)

        self.win.source_manager.open_files([self.tiff])

        items = {
            tree.topLevelItem(row).data(0, self.win.project_tab.NODE_ID_ROLE): tree.topLevelItem(
                row
            )
            for row in range(tree.topLevelItemCount())
        }
        self.assertTrue(items[original_sample_id].isExpanded())
        new_sample_id = next(sample_id for sample_id in items if sample_id != original_sample_id)
        self.assertTrue(items[new_sample_id].isExpanded())

    def test_space_toggles_all_selected_project_elements(self):
        self.win.source_manager.open_files([self.h5])
        element_list = self.win.project_tab.channelList
        self.assertEqual(
            element_list.selectionMode(),
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection,
        )
        for row in range(element_list.count()):
            element_list.item(row).setSelected(True)
        element_list.setCurrentRow(0, QtCore.QItemSelectionModel.SelectionFlag.NoUpdate)

        QtTest.QTest.keyClick(element_list, QtCore.Qt.Key_Space)
        self.assertEqual(set(self.win.project_data.project_channels), {"Fe", "Zn"})
        self.assertTrue(
            all(
                element_list.item(row).checkState() == QtCore.Qt.CheckState.Checked
                for row in range(element_list.count())
            )
        )

        QtTest.QTest.keyClick(element_list, QtCore.Qt.Key_Space)
        self.assertFalse(self.win.project_data.project_channels)

    def test_project_element_indicator_updates_project_state(self):
        self.win.source_manager.open_files([self.h5])
        element_list = self.win.project_tab.channelList
        item = element_list.item(0)
        delegate = element_list.itemDelegate()
        self.assertIsInstance(delegate, IconCheckDelegate)
        self.assertTrue(item.icon().isNull())

        index = element_list.indexFromItem(item)
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = element_list.visualRect(index)
        option.widget = element_list
        delegate.initStyleOption(option, index)
        QtTest.QTest.mouseClick(
            element_list.viewport(),
            QtCore.Qt.MouseButton.LeftButton,
            pos=delegate.indicator_rect(option, index).center(),
        )

        key = item.data(ElementListWidget.CHANNEL_KEY_ROLE)
        self.assertEqual(item.checkState(), QtCore.Qt.CheckState.Checked)
        self.assertIn(key, self.win.project_data.project_channels)

    def test_action_icons_have_fallbacks(self):
        for name in (
            "actionOpenFile",
            "actionOpenProject",
            "actionSaveProject",
            "actionSaveProjectAs",
            "actionSettings",
            "actionAbout",
            "actionQuit",
        ):
            with self.subTest(action=name):
                self.assertFalse(getattr(self.win, name).icon().isNull())

    def test_clearing_project_closes_sources_without_intermediate_ui_refresh(self):
        self.win.source_manager.open_files([self.h5, self.tiff])
        with patch.object(
            self.win.source_manager,
            "close_source_handles",
            wraps=self.win.source_manager.close_source_handles,
        ) as close_all:
            self.win.clear_project()

        close_all.assert_called_once_with()

    def test_new_hdf5_sample_materializes_inherited_channel_before_refresh(self):
        self.win.source_manager.open_files([self.h5])
        first_sample = next(iter(self.win.project_data.samples.values()))
        channel = first_sample.channels["Fe"]
        settings = self.win.element_controller.ensure_settings(channel.ref)
        self.win.project_data.add_project_channel("Fe", channel.name, settings)
        self.win.element_controller.effective_channels_changed()

        second_h5 = str(Path(self.temp.name) / "second.h5")
        with h5py.File(second_h5, "w") as f:
            f.attrs["default"] = "entry"
            group = f.create_group("entry/plotselect")
            group.create_dataset("Fe", data=self.data)
        self.win.source_manager.open_files([second_h5])

        second_sample = self.win.project_data.samples[
            self.win.project_data.assets[second_h5].sample_id
        ]
        self.assertIn(second_sample.channels["Fe"].ref, self.win.project_data.element_settings)

    def test_duplicate_channel_uses_current_error_dialog_without_partial_addition(self):
        self.win.source_manager.open_files([self.h5])
        sample_id = next(iter(self.win.project_data.samples))
        duplicate_h5 = str(Path(self.temp.name) / "duplicate.h5")
        with h5py.File(duplicate_h5, "w") as f:
            f.attrs["default"] = "entry"
            group = f.create_group("entry/plotselect")
            group.create_dataset("Fe", data=self.data)

        with patch.object(self.win, "show_error") as show_error:
            self.win.source_manager.open_files([duplicate_h5], sample_id=sample_id)

        self.assertNotIn(duplicate_h5, self.win.project_data.assets)
        summary, details = show_error.call_args.args[:2]
        self.assertIn("same channel key", summary)
        self.assertIn("Channel key: Fe", details)
        self.assertIn("DuplicateChannelError", details)

    def test_project_tiff_batch_creates_one_sample(self):
        second = str(Path(self.temp.name) / "sample_Zn.tiff")
        Image.fromarray(self.data).save(second)

        self.win.source_manager.open_files([self.tiff, second])

        self.assertEqual(len(self.win.project_data.samples), 1)
        sample = next(iter(self.win.project_data.samples.values()))
        self.assertEqual(sample.asset_ids, [self.tiff, second])
        self.assertEqual(len(sample.channels), 2)
        self.assertEqual(set(self.win.project_data.project_channels), set(sample.channels))

    def test_tiff_channel_already_in_project_is_used_by_new_sample(self):
        first = str(Path(self.temp.name) / "control_Fe_K.tiff")
        second = str(Path(self.temp.name) / "treated_Fe_K.tiff")
        Image.fromarray(self.data).save(first)
        Image.fromarray(self.data).save(second)

        self.win.source_manager.open_files([first])
        self.win.source_manager.open_files([second])

        second_sample = self.win.project_data.samples[
            self.win.project_data.assets[second].sample_id
        ]
        self.assertIn("Fe_K", self.win.project_data.project_channels)
        self.assertIn(
            "Fe_K", second_sample.effective_channels(self.win.project_data.project_channels)
        )

    def test_project_data_resolution_is_used_for_new_images(self):
        self.win.source_manager.open_files([self.h5])
        self.win.image_controller.create_image()
        self.win.project_tab.resolutionValue.setValue(125)
        self.win.project_tab.resolutionUnits.setCurrentText("µm")

        image_id = self.win.imageList.currentItem().data(self.win.imageList.IMG_NUM_ROLE)
        self.assertEqual(self.win.project_data.images[image_id].resolution, [125, "µm"])

    def test_project_and_sample_channel_states(self):
        other = str(Path(self.temp.name) / "other" / "elements.h5")
        Path(other).parent.mkdir()
        with h5py.File(other, "w") as f:
            f.attrs["default"] = "entry"
            group = f.create_group("entry/plotselect")
            group.create_dataset("Fe", data=self.data)
            group.create_dataset("Zn", data=self.data * 3)
        self.win.source_manager.open_files([self.h5, other])

        project_list = self.win.project_tab.channelList
        project_order = [
            project_list.item(row).data(ElementListWidget.CHANNEL_KEY_ROLE)
            for row in range(project_list.count())
        ]
        fe_item = next(
            project_list.item(row)
            for row in range(project_list.count())
            if project_list.item(row).data(ElementListWidget.CHANNEL_KEY_ROLE) == "Fe"
        )
        project_list.setCurrentItem(fe_item)
        fe_item.setCheckState(QtCore.Qt.CheckState.Checked)

        self.assertIn("Fe", self.win.project_data.project_channels)
        self.assertEqual(len(self.win.project_data.effective_refs()), 2)
        self.assertIs(project_list.currentItem(), fe_item)
        self.assertEqual(
            [
                project_list.item(row).data(ElementListWidget.CHANNEL_KEY_ROLE)
                for row in range(project_list.count())
            ],
            project_order,
        )

        first_sample = self.win.project_data.assets[self.h5].sample_id
        self.win.loadedFileComboBox.setCurrentIndex(
            self.win.loadedFileComboBox.findData(first_sample)
        )
        fe_item = next(
            self.win.elementList.item(row)
            for row in range(self.win.elementList.count())
            if self.win.elementList.item(row).data(ElementListWidget.CHANNEL_KEY_ROLE) == "Fe"
        )
        self.assertEqual(
            fe_item.data(ElementListWidget.SAMPLE_STATE_ROLE),
            SampleChannelState.INHERIT.value,
        )

        self.win.element_controller.cycle_sample_element_state(fe_item)
        self.win.element_controller.cycle_sample_element_state(fe_item)
        self.assertEqual(len(self.win.project_data.effective_refs()), 1)
        self.assertEqual(
            self.win.project_data.sample_channel_state(first_sample, "Fe"), SampleChannelState.SKIP
        )

        fe_item = next(
            self.win.elementList.item(row)
            for row in range(self.win.elementList.count())
            if self.win.elementList.item(row).data(ElementListWidget.CHANNEL_KEY_ROLE) == "Fe"
        )
        self.win.element_controller.cycle_sample_element_state(fe_item)
        self.win.element_controller.cycle_sample_element_state(fe_item)
        self.assertEqual(len(self.win.project_data.effective_refs()), 2)
        self.assertEqual(
            self.win.project_data.sample_channel_state(first_sample, "Fe"),
            SampleChannelState.OVERRIDE,
        )

    def test_analysis_inputs_follow_the_segmentation_sample(self):
        other = str(Path(self.temp.name) / "other.h5")
        with h5py.File(other, "w") as handle:
            handle.attrs["default"] = "entry"
            group = handle.create_group("entry/plotselect")
            group.create_dataset("Cu", data=self.data)
            group.create_dataset("Fe", data=self.data * 2)
        self.win.source_manager.open_files([self.h5, other])
        for key in ("Cu", "Fe", "Zn"):
            sample = next(
                sample
                for sample in self.win.project_data.samples.values()
                if key in sample.channels
            )
            self.win.project_data.add_project_channel_from_sample(sample.sample_id, key)
        self.win.element_controller.effective_channels_changed()

        first_id = self.win.project_data.assets[self.h5].sample_id
        second_id = self.win.project_data.assets[other].sample_id
        self.win.analysisSampleComboBox.setCurrentIndex(
            self.win.analysisSampleComboBox.findData(first_id)
        )
        self.win.analysis_controller.update_channels()
        self.win.analysis_controller.update_elements()
        self.assertEqual(
            {self.win.analysisChNuclei.itemText(row) for row in range(1, 3)},
            {"Fe", "Zn"},
        )
        self.assertEqual(self.win.analysisElements.count(), 2)

        first_ref = self.win.analysisChNuclei.itemData(1)
        self.win.analysisChNuclei.setCurrentIndex(1)
        self.win.loadedFileComboBox.setCurrentIndex(self.win.loadedFileComboBox.findData(second_id))
        self.assertEqual(self.win.analysisSampleComboBox.currentData(), first_id)
        self.assertEqual(self.win.analysisChNuclei.currentData(), first_ref)

        self.win.analysisSampleComboBox.setCurrentIndex(
            self.win.analysisSampleComboBox.findData(second_id)
        )
        self.win.analysis_controller.update_channels()
        self.win.analysis_controller.update_elements()

        refs = {
            self.win.analysisElements.item(row).data(ElementListWidget.ELEMENT_REF_ROLE)
            for row in range(self.win.analysisElements.count())
        }
        self.assertEqual({ref.source_id for ref in refs}, {other})
        self.assertEqual(
            {self.win.analysisChNuclei.itemText(row) for row in range(1, 3)},
            {"Cu", "Fe"},
        )
        self.assertEqual(self.win.analysisChNuclei.currentIndex(), 0)
        self.assertNotIn(first_ref, refs)

    def test_analysis_inputs_are_disabled_while_busy(self):
        self.win.analysis_controller.set_busy(True)
        for widget in (
            self.win.analysisSampleComboBox,
            self.win.analysisChNuclei,
            self.win.analysisChTissue,
            self.win.analysisElements,
            self.win.analysisOptions,
            self.win.analysis_controller.cluster_min_k,
            self.win.analysis_controller.cluster_max_k,
            self.win.analysis_controller.nuclei_expansion,
            self.win.analysis_controller.nuclei_min_area,
        ):
            self.assertFalse(widget.isEnabled())

        self.win.analysis_controller.set_busy(False)
        self.assertTrue(self.win.analysisSampleComboBox.isEnabled())
        self.assertTrue(self.win.analysisElements.isEnabled())

    def test_analysis_elements_use_standard_check_state_with_custom_glyphs(self):
        self.win.source_manager.open_files([self.h5])
        sample_id = self.win.project_data.assets[self.h5].sample_id
        for key in ("Fe", "Zn"):
            self.win.project_data.add_project_channel_from_sample(sample_id, key)
        self.win.element_controller.effective_channels_changed()
        self.win.analysisSampleComboBox.addItem("elements", sample_id)
        self.win.analysis_controller.update_elements()

        element_list = self.win.analysisElements
        item = element_list.item(0)
        delegate = element_list.itemDelegate()
        self.assertIsInstance(delegate, IconCheckDelegate)
        option = QtWidgets.QStyleOptionViewItem()
        index = element_list.indexFromItem(item)
        option.rect = element_list.visualRect(index)
        option.widget = element_list
        delegate.initStyleOption(option, index)
        self.assertTrue(
            option.features & QtWidgets.QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        )
        self.assertEqual(item.checkState(), QtCore.Qt.Checked)
        self.assertTrue(item.icon().isNull())

        QtTest.QTest.mouseClick(
            element_list.viewport(),
            QtCore.Qt.LeftButton,
            pos=delegate.indicator_rect(option, index).center(),
        )

        self.assertEqual(item.checkState(), QtCore.Qt.Unchecked)
        self.assertTrue(item.icon().isNull())

    def test_segmentation_screenshot_saves_the_canvas(self):
        viewer = Mock()
        self.win.analysis_controller.naparihelper = SimpleNamespace(sample=object(), viewer=viewer)
        filename = str(Path(self.temp.name) / "segmentation.png")

        with patch.object(self.win, "askFileName", return_value=filename):
            self.win.analysis_controller.save_screenshot()

        viewer.screenshot.assert_called_once_with(
            path=filename,
            canvas_only=True,
            flash=True,
        )

    def test_analysis_requires_a_saved_project(self):
        self.assertIsNone(self.win.project_dir)
        self.win.analysis_controller.worker = None

        with patch.object(QtWidgets.QMessageBox, "information") as information:
            self.win.analysis_controller.run()

        information.assert_called_once()
        self.assertIn("Save the project", information.call_args.args[2])
        self.assertIsNone(self.win.analysis_controller.worker)

    def test_selecting_sample_restores_its_segmentation_result(self):
        other = str(Path(self.temp.name) / "other.h5")
        with h5py.File(other, "w") as handle:
            handle.attrs["default"] = "entry"
            group = handle.create_group("entry/plotselect")
            group.create_dataset("Cu", data=self.data)
        self.win.source_manager.open_files([self.h5, other])
        for sample in self.win.project_data.samples.values():
            for key in sample.channels:
                self.win.project_data.add_project_channel_from_sample(sample.sample_id, key)
        self.win.element_controller.effective_channels_changed()

        first_id = self.win.project_data.assets[self.h5].sample_id
        second_id = self.win.project_data.assets[other].sample_id
        sample = self.win.project_data.samples[first_id]
        fe_ref = sample.channels["Fe"].ref
        zn_ref = sample.channels["Zn"].ref
        parameters = SegmentationParameters(7, 19, 3, 8)
        xrf_sample = SimpleNamespace(elements={"Zn": object()})
        self.win.project_data.segmentation_results[first_id] = SegmentationResult(
            first_id,
            fe_ref,
            zn_ref,
            (zn_ref,),
            parameters,
            xrf_sample,
        )

        class FakeNapariHelper:
            def __init__(self):
                self.sample = None
                self.element_maps = None
                self.viewer = SimpleNamespace(layers=[])
                self.set_sample_calls = 0
                self.updated_element_maps = []

            def set_sample(self, value, element_maps=None):
                self.sample = value
                self.element_maps = element_maps
                self.set_sample_calls += 1

            def update_element_maps(self, maps):
                self.updated_element_maps.append(maps)

        controller = self.win.analysis_controller
        controller.naparihelper = FakeNapariHelper()
        self.win.analysisSampleComboBox.setCurrentIndex(
            self.win.analysisSampleComboBox.findData(first_id)
        )
        controller.sample_changed()

        self.assertIs(controller.naparihelper.sample, xrf_sample)
        expected_map = self.win.project_data.element_settings[zn_ref].transformedData()
        self.assertEqual(len(controller.naparihelper.element_maps), 1)
        np.testing.assert_array_equal(controller.naparihelper.element_maps[0], expected_map)
        self.assertEqual(self.win.analysisChNuclei.currentData(), fe_ref)
        self.assertEqual(self.win.analysisChTissue.currentData(), zn_ref)
        checked = {
            self.win.analysisElements.item(row).data(ElementListWidget.ELEMENT_REF_ROLE)
            for row in range(self.win.analysisElements.count())
            if self.win.analysisElements.item(row).checkState() == QtCore.Qt.Checked
        }
        self.assertEqual(checked, {zn_ref})
        self.assertEqual(controller.segmentation_parameters(), parameters)

        settings = self.win.project_data.element_settings[zn_ref]
        set_sample_calls = controller.naparihelper.set_sample_calls
        with patch.object(settings, "transformedData", wraps=settings.transformedData) as transform:
            controller.refresh_result_view()
            transform.assert_not_called()
            self.assertEqual(controller.naparihelper.set_sample_calls, set_sample_calls)

            settings.gamma += 0.1
            controller.refresh_result_view()
            transform.assert_called_once_with()
            self.assertEqual(controller.naparihelper.set_sample_calls, set_sample_calls)
            self.assertEqual(len(controller.naparihelper.updated_element_maps), 1)
            self.assertEqual(set(controller.naparihelper.updated_element_maps[0]), {"Zn"})

        self.win.analysisSampleComboBox.setCurrentIndex(
            self.win.analysisSampleComboBox.findData(second_id)
        )
        controller.sample_changed()

        self.assertIsNone(controller.naparihelper.sample)
        self.assertEqual(controller.segmentation_parameters(), parameters)

    def test_project_roundtrip_restores_segmentation_result(self):
        from exhale.xrf_refcopy.xrf_other_channel import NucleiChannel, TissueChannel
        from exhale.xrf_refcopy.xrf_sample_class import XRFSample

        self.win.source_manager.open_files([self.h5])
        sample = next(iter(self.win.project_data.samples.values()))
        for key in sample.channels:
            self.win.project_data.add_project_channel_from_sample(sample.sample_id, key)
        fe_ref = sample.channels["Fe"].ref
        zn_ref = sample.channels["Zn"].ref
        parameters = SegmentationParameters(6, 18, 3, 7)
        xrf_sample = XRFSample(sample.name)
        xrf_sample.nuclei = NucleiChannel(self.data)
        xrf_sample.nuclei.nuclei_labels = np.ones_like(self.data)
        xrf_sample.nuclei.expanded_labels = np.ones_like(self.data)
        xrf_sample.nuclei.membrane_labels = np.zeros_like(self.data)
        xrf_sample.tissue = TissueChannel(self.data)
        xrf_sample.tissue.log_image = self.data.astype(float)
        xrf_sample.tissue.tissue_mask = np.ones_like(self.data, dtype=bool)
        xrf_sample.tissue.tissue_labels = np.ones_like(self.data)
        xrf_sample._processed = True
        xrf_sample._combined = True
        self.win.project_data.segmentation_results[sample.sample_id] = SegmentationResult(
            sample.sample_id,
            fe_ref,
            zn_ref,
            (fe_ref,),
            parameters,
            xrf_sample,
        )
        project_dir = Path(self.temp.name) / "segmentation-project"

        projectio.save_project(self.win.project_data, project_dir / "project.xhp")
        self.win.project_state_manager.mark_saved()
        self.assertTrue(self.win.project_manager.load_project_dir(project_dir))

        restored = self.win.project_data.segmentation_results[sample.sample_id]
        self.assertEqual(restored.parameters, parameters)
        self.assertEqual(restored.nuclei_ref, fe_ref)
        self.assertEqual(restored.element_refs, (fe_ref,))
        np.testing.assert_array_equal(
            restored.xrf_sample.nuclei.nuclei_labels,
            xrf_sample.nuclei.nuclei_labels,
        )

    def test_analysis_rejects_an_unavailable_sample_channel(self):
        self.win.source_manager.open_files([self.h5])
        sample = next(iter(self.win.project_data.samples.values()))
        self.win.project_data.add_project_channel_from_sample(sample.sample_id, "Fe")
        self.win.element_controller.effective_channels_changed()
        ref = sample.channels["Fe"].ref
        self.win.project_data.sources[self.h5].close()

        with self.assertRaisesRegex(RuntimeError, "cannot be opened"):
            self.win.analysis_controller.element_settings([ref])

    def test_images_and_image_map_choices_follow_selected_sample(self):
        other = str(Path(self.temp.name) / "other" / "elements.h5")
        Path(other).parent.mkdir()
        with h5py.File(other, "w") as f:
            f.attrs["default"] = "entry"
            group = f.create_group("entry/plotselect")
            group.create_dataset("Fe", data=self.data)
        self.win.source_manager.open_files([self.h5, other])

        project_list = self.win.project_tab.channelList
        fe_item = next(
            project_list.item(row)
            for row in range(project_list.count())
            if project_list.item(row).data(ElementListWidget.CHANNEL_KEY_ROLE) == "Fe"
        )
        fe_item.setCheckState(QtCore.Qt.CheckState.Checked)

        first_id = self.win.project_data.assets[self.h5].sample_id
        second_id = self.win.project_data.assets[other].sample_id
        for sample_id in (first_id, second_id):
            self.win.loadedFileComboBox.setCurrentIndex(
                self.win.loadedFileComboBox.findData(sample_id)
            )
            self.win.image_controller.create_image()
            self.assertEqual(self.win.imageList.count(), 1)
            image_id = self.win.imageList.currentItem().data(self.win.imageList.IMG_NUM_ROLE)
            image = self.win.project_data.images[image_id]
            self.assertEqual(image.name, "New image")
            self.assertFalse(image.elements)
            refs = {
                self.win.imageElementBoxes[0].combo.itemData(row)
                for row in range(1, self.win.imageElementBoxes[0].combo.count())
            }
            expected_source = self.h5 if sample_id == first_id else other
            self.assertEqual({ref.source_id for ref in refs}, {expected_source})
            self.assertEqual(self.win.imageElementBoxes[0].combo.itemText(1), "Fe")
            self.win.imageElementBoxes[0].combo.setCurrentIndex(1)

        self.win.loadedFileComboBox.setCurrentIndex(self.win.loadedFileComboBox.findData(first_id))
        self.assertEqual(self.win.imageElementBoxes[0].combo.currentData().source_id, self.h5)

        fe_item = next(
            project_list.item(row)
            for row in range(project_list.count())
            if project_list.item(row).data(ElementListWidget.CHANNEL_KEY_ROLE) == "Fe"
        )
        fe_item.setCheckState(QtCore.Qt.CheckState.Unchecked)
        self.win.loadedFileComboBox.setCurrentIndex(self.win.loadedFileComboBox.findData(first_id))
        self.assertIsNone(self.win.imageElementBoxes[0].combo.currentData())
        self.assertEqual(self.win.imageElementBoxes[0].combo.count(), 1)

        fe_item.setCheckState(QtCore.Qt.CheckState.Checked)
        self.win.loadedFileComboBox.setCurrentIndex(self.win.loadedFileComboBox.findData(first_id))
        self.assertEqual(self.win.imageElementBoxes[0].combo.currentData().source_id, self.h5)

    def test_image_element_choices_follow_sample_element_order(self):
        self.win.source_manager.open_files([self.h5])
        sample = next(iter(self.win.project_data.samples.values()))
        self.win.project_data.add_project_channel_from_sample(sample.sample_id, "Zn")
        self.win.project_data.override_sample_channel(sample.sample_id, "Fe")

        self.win.element_controller.effective_channels_changed()

        list_refs = [
            self.win.elementList.item(row).data(ElementListWidget.ELEMENT_REF_ROLE)
            for row in range(self.win.elementList.count())
            if self.win.elementList.item(row).data(ElementListWidget.ELEMENT_REF_ROLE)
            in self.win.project_data.effective_refs()
        ]
        combo = self.win.imageElementBoxes[0].combo
        combo_refs = [combo.itemData(row) for row in range(1, combo.count())]
        self.assertEqual(combo_refs, list_refs)
        self.assertEqual(
            [combo.itemText(row) for row in range(1, combo.count())],
            [self.win.project_data.element_settings[ref].name for ref in list_refs],
        )

    def test_project_channel_name_edit_updates_all_matching_maps(self):
        self.win.source_manager.open_files([self.h5])
        self.win.loadedFileComboBox.setCurrentIndex(0)
        item = next(
            self.win.elementList.item(row)
            for row in range(self.win.elementList.count())
            if self.win.elementList.item(row).data(ElementListWidget.CHANNEL_KEY_ROLE) == "Fe"
        )
        self.win.element_controller.cycle_sample_element_state(item)
        item = next(
            self.win.elementList.item(row)
            for row in range(self.win.elementList.count())
            if self.win.elementList.item(row).data(ElementListWidget.CHANNEL_KEY_ROLE) == "Fe"
        )
        self.win.elementList.setCurrentItem(item)

        self.win.elementName.setText("Iron")
        self.win.elementName.editingFinished.emit()

        self.assertEqual(self.win.project_data.project_channels["Fe"].name, "Iron")
        ref = (
            self.win.project_data.samples[self.win.project_data.assets[self.h5].sample_id]
            .channels["Fe"]
            .ref
        )
        self.assertEqual(self.win.project_data.element_settings[ref].name, "Iron")

    def test_close_preserves_materialized_elements_and_image_copies(self):
        self.win.source_manager.open_files([self.h5])
        source = self.win.project_data.sources[self.h5]
        candidate = source.list_elements()[0]
        element = ElementSettings(ref=candidate.ref, data=source.channel_data(candidate.ref))
        self.win.project_data.element_settings[candidate.ref] = element
        image = ImageSettings("Retained image")
        image.elements[0] = element.copy()
        self.assertIs(image.elements[0].data_source, element.data_source)
        self.win.project_data.images[1] = image
        source.close()
        np.testing.assert_array_equal(element.data, self.data)
        np.testing.assert_array_equal(image.elements[0].data, self.data)
        image.elements[0].trfRange[0] = 5
        self.assertNotEqual(element.trfRange[0], 5)
        self.assertIs(self.win.project_data.element_settings[candidate.ref], element)

    def test_refresh_excludes_closed_sources_and_does_not_duplicate(self):
        self.win.source_manager.open_files([self.h5, self.tiff])
        hdf5_sample_id = self.win.project_data.assets[self.h5].sample_id
        self.win.loadedFileComboBox.setCurrentIndex(
            self.win.loadedFileComboBox.findData(hdf5_sample_id)
        )
        self.win.project_data.sources[self.tiff].close()
        for _ in range(2):
            self.win.refresh_project_ui()
            self.assertEqual(self.win.loadedFileComboBox.count(), 2)
            self.assertEqual(self.win.elementList.count(), 2)
            self.assertEqual(
                self.win.loadedFileComboBox.currentData(),
                hdf5_sample_id,
            )

    def test_project_roundtrip_preserves_source_aliases(self):
        self.win.source_manager.open_files([self.h5, self.tiff])
        self.win.project_data.element_defaults = ElementSettingsDefaults(
            normalizer=Normalizers.SQRT,
            range_mode="percent",
            lower_percentile=8,
            upper_percentile=91,
        )
        self.win.project_data.sources[self.h5].alias = "Scan A"
        self.win.project_data.sources[self.tiff].alias = "Image B"
        project_dir = Path(self.temp.name) / "sources"
        filename = project_dir / "project.xhp"
        projectio.save_project(self.win.project_data, filename)
        self.win.project_state_manager.mark_saved()
        old_sources = list(self.win.project_data.sources.values())
        with patch.object(self.win, "show_error") as error:
            self.assertTrue(self.win.project_manager.load_project_dir(project_dir))
            error.assert_not_called()
        self.assertEqual(self.win.project_dir, project_dir.resolve())
        self.assertTrue(all(not s.is_open for s in old_sources))
        self.assertEqual(self.win.loadedFileComboBox.count(), 2)
        self.assertEqual(self.win.project_data.sources[self.h5].alias, "Scan A")
        self.assertEqual(self.win.project_data.sources[self.tiff].alias, "Image B")
        self.assertEqual(
            self.win.project_data.element_defaults,
            ElementSettingsDefaults(
                normalizer=Normalizers.SQRT,
                range_mode="percent",
                lower_percentile=8,
                upper_percentile=91,
            ),
        )
        self.win.clear_project()
        self.assertFalse(self.win.project_data.sources)
        self.assertFalse(self.win.project_data.element_settings)
        self.assertFalse(self.win.project_data.images)
        self.assertEqual(self.win.elementList.count(), 0)

    def test_failed_atomic_save_preserves_existing_project_file(self):
        project_dir = Path(self.temp.name) / "atomic"
        project_dir.mkdir()
        project_file = project_dir / "project.xhp"
        project_file.write_text("previous state\n", encoding="utf-8")

        with patch("exhale.project.projectio.os.replace", side_effect=OSError("failed")):
            with self.assertRaises(OSError):
                projectio.save_project(self.win.project_data, project_file)

        self.assertEqual(project_file.read_text(encoding="utf-8"), "previous state\n")
        self.assertEqual(list(project_dir.iterdir()), [project_file])

    def test_project_restores_sample_image_and_independent_settings(self):
        self.win.source_manager.open_files([self.h5])
        source = self.win.project_data.sources[self.h5]
        sample_id = self.win.project_data.assets[self.h5].sample_id
        image = ImageSettings("Element image", sample_id=sample_id, sample_source_ids=[self.h5])
        for slot, candidate in enumerate(source.list_elements()):
            ref = candidate.ref
            _sample, channel = self.win.project_data.channel_for_ref(ref)
            element = ElementSettings(ref=ref, data=source.load_array(ref), name=f"Element {slot}")
            self.win.project_data.element_settings[ref] = element
            self.win.project_data.add_project_channel(channel.key, channel.name, element)
            image.setElement(slot, element, channel.key)
            image.createElementOverride(slot)
            image.elements[slot].name = f"Local {slot}"
            image.elements[slot].trfRange = [2, 9]
        self.win.project_data.images = {1: image}
        project_dir = Path(self.temp.name) / "mixed"
        path = project_dir / "project.xhp"
        projectio.save_project(self.win.project_data, path)
        self.win.project_state_manager.mark_saved()
        with patch.object(self.win, "show_error") as error:
            self.assertTrue(self.win.project_manager.load_project_dir(project_dir))
            error.assert_not_called()
        self.assertEqual(len(self.win.project_data.effective_refs()), 2)
        restored = self.win.project_data.images[1]
        self.assertIs(self.win.image_controller.current_image, restored)
        for slot, element in restored.elements.items():
            combo = self.win.imageElementBoxes[slot].combo
            self.assertTrue(
                any(combo.itemData(row) == element.ref for row in range(1, combo.count()))
            )
            self.assertEqual(combo.currentData(), element.ref)
        for slot, local in restored.elements.items():
            global_element = self.win.project_data.element_settings[local.ref]
            self.assertEqual(local.name, f"Local {slot}")
            self.assertEqual(global_element.name, f"Element {slot}")
            self.assertIsNot(local, global_element)
            self.assertEqual(local.trfRange, [2, 9])
            original_range = global_element.trfRange.copy()
            local.trfRange[0] = 4
            self.assertEqual(global_element.trfRange, original_range)
            np.testing.assert_array_equal(local.data, self.data * (slot + 1))
        self.win.source_manager.close_source_handles()
        for slot, local in restored.elements.items():
            np.testing.assert_array_equal(local.data, self.data * (slot + 1))

    def test_missing_project_file_preserves_channels_and_image_references(self):
        self.win.source_manager.open_files([self.h5])
        source = self.win.project_data.sources[self.h5]
        sample = self.win.project_data.samples[self.win.project_data.assets[self.h5].sample_id]
        ref = source.list_elements()[0].ref
        element = ElementSettings(ref=ref, data=source.channel_data(ref))
        self.win.project_data.set_element_settings(ref, element)
        self.win.project_data.add_project_channel("Fe", "Fe", element)
        image = ImageSettings("Missing", sample_id=sample.sample_id, sample_source_ids=[self.h5])
        image.setElement(0, element, sample.channels["Fe"].key)
        self.win.project_data.images = {1: image}
        project_dir = Path(self.temp.name) / "missing"
        projectio.save_project(self.win.project_data, project_dir / "project.xhp")
        self.win.project_state_manager.mark_saved()
        self.win.source_manager.close_source_handles()
        Path(self.h5).unlink()

        with (
            patch.object(self.win, "show_error") as internal_error,
            patch.object(QtWidgets.QMessageBox, "warning") as warning,
        ):
            self.assertTrue(self.win.project_manager.load_project_dir(project_dir))
        internal_error.assert_not_called()
        self.assertIn("could not be opened", warning.call_args.args[2])
        self.assertIn("FileNotFoundError", warning.call_args.args[2])

        asset = self.win.project_data.assets[self.h5]
        self.assertFalse(asset.is_available)
        self.assertIn("FileNotFoundError", asset.source.open_error)
        self.assertIn("Fe", self.win.project_data.samples[asset.sample_id].channels)
        self.assertEqual(self.win.project_data.images[1].elements[0].ref, ref)
        with self.assertRaisesRegex(RuntimeError, "cannot be opened"):
            self.win.project_data.images[1].elements[0].transformedData()

        item = next(
            self.win.elementList.item(row)
            for row in range(self.win.elementList.count())
            if self.win.elementList.item(row).data(ElementListWidget.ELEMENT_REF_ROLE) == ref
        )
        with patch.object(self.win, "show_source_unavailable") as unavailable:
            self.win.elementList.setCurrentItem(item)
        unavailable.assert_called_once_with(self.h5)

    def test_project_roundtrip_preserves_channel_model_and_explicit_overrides(self):
        self.win.source_manager.open_files([self.h5])
        source = self.win.project_data.sources[self.h5]
        sample = self.win.project_data.samples[self.win.project_data.assets[self.h5].sample_id]
        settings = {}
        for candidate in source.list_elements():
            element = ElementSettings(ref=candidate.ref, data=source.channel_data(candidate.ref))
            self.win.project_data.set_element_settings(candidate.ref, element)
            settings[candidate.name] = element
        self.win.project_data.add_project_channel("Fe", "Iron", settings["Fe"])
        self.win.project_data.add_project_channel("Zn", "Zinc", settings["Zn"])
        self.win.project_data.skip_sample_channel(sample.sample_id, "Fe")
        self.win.project_data.override_sample_channel(
            sample.sample_id, "Zn", name="Local zinc", settings=settings["Zn"]
        )
        self.win.project_data.image_defaults.layout = Layouts.IB
        self.win.project_data.image_defaults.fontsize = 17
        empty_sample = self.win.project_data.create_sample("Empty sample")
        image = ImageSettings("Overrides", sample_id=sample.sample_id, sample_source_ids=[self.h5])
        image.setElement(0, settings["Fe"], "Fe")
        image.setElement(1, settings["Zn"], "Zn")
        image.createElementOverride(1).name = "Image zinc"
        self.win.project_data.images = {1: image}
        project_dir = Path(self.temp.name) / "model"
        projectio.save_project(self.win.project_data, project_dir / "project.xhp")
        self.win.project_state_manager.mark_saved()

        self.assertTrue(self.win.project_manager.load_project_dir(project_dir))

        restored = self.win.project_data.samples[sample.sample_id]
        self.assertIsNone(restored.channel_overrides["Fe"])
        self.assertEqual(restored.channel_overrides["Zn"].name, "Local zinc")
        self.assertEqual(self.win.project_data.project_channels["Fe"].name, "Iron")
        self.assertEqual(self.win.project_data.samples[empty_sample.sample_id].name, "Empty sample")
        self.assertEqual(self.win.project_data.image_defaults.layout, Layouts.IB)
        self.assertEqual(self.win.project_data.image_defaults.fontsize, 17)
        restored_image = self.win.project_data.images[1]
        self.assertNotIn(0, restored_image.elements)
        self.assertEqual(restored_image.suspended_elements[0][1], "Fe")
        self.assertIsNot(
            restored_image.elements[1], self.win.project_data.element_settings[settings["Zn"].ref]
        )
        self.assertEqual(restored_image.elements[1].name, "Image zinc")
        self.assertIn(1, restored_image.element_overrides)

        self.assertTrue(self.win.project_manager.save_project())
        self.assertTrue(self.win.project_manager.load_project_dir(project_dir))
        reloaded_image = self.win.project_data.images[1]
        self.assertNotIn(0, reloaded_image.elements)
        self.assertNotIn(0, reloaded_image.suspended_elements)

    def test_project_reader_defaults_optional_fields_and_skips_broken_objects(self):
        self.win.source_manager.open_files([self.h5])
        source = self.win.project_data.sources[self.h5]
        ref = source.list_elements()[0].ref
        element = ElementSettings(ref=ref, data=source.load_array(ref))
        self.win.project_data.element_settings[ref] = element
        sample_id = self.win.project_data.assets[self.h5].sample_id
        _sample, channel = self.win.project_data.channel_for_ref(ref)
        image = ImageSettings("Strict schema", sample_id=sample_id, sample_source_ids=[self.h5])
        image.setElement(0, element.copy(), channel.key)

        empty_image = ImageSettings("Empty", sample_id=sample_id, sample_source_ids=[self.h5])
        restored_empty = projectio._imagesettings_from_json(
            projectio._imagesettings_to_json(2, empty_image), self.win.project_data
        )
        self.assertEqual(restored_empty.sample_id, sample_id)

        image_state = projectio._imagesettings_to_json(1, image)
        image_state["elements"]["0"]["ref"] = {
            "file": ref.source_id,
            "dataset": ref.item_id,
        }
        with self.assertRaises(KeyError):
            projectio._imagesettings_from_json(image_state, self.win.project_data)

        image_state = projectio._imagesettings_to_json(1, image)
        image_state.pop("clip_colors")
        restored = projectio._imagesettings_from_json(image_state, self.win.project_data)
        self.assertTrue(restored.clipColors)
        self.assertFalse(restored.suspended_elements)

        state = projectio.export_project_state(self.win.project_data)
        state["version"] = projectio.PROJECT_VERSION - 1
        state["element_settings"][0]["path"] = state["element_settings"][0].pop("ref")
        state["images"].append({"id": 9, "name": "Broken image", "sample_id": "missing"})
        self.win.clear_project()
        issues = projectio.load_project_state(self.win.project_data, state, open_files=False)
        self.assertTrue(any("element's settings" in issue for issue in issues))
        self.assertTrue(any("Broken image" in issue for issue in issues))

    def test_project_reader_accepts_older_versions_but_rejects_newer_ones(self):
        state = projectio.export_project_state(self.win.project_data)
        state["version"] = projectio.PROJECT_VERSION - 1
        projectio.validate_project_state(state)

        state["version"] = projectio.PROJECT_VERSION + 1
        with self.assertRaisesRegex(ValueError, "newer than supported"):
            projectio.validate_project_state(state)

        state["version"] = projectio.PROJECT_VERSION
        del state["samples"]
        with self.assertRaisesRegex(ValueError, "samples"):
            projectio.validate_project_state(state)

    def test_loading_an_older_usable_project_marks_it_dirty(self):
        self.win.source_manager.open_files([self.h5])
        state = projectio.export_project_state(self.win.project_data)
        state["version"] = projectio.PROJECT_VERSION - 1
        project_dir = Path(self.temp.name) / "older"
        projectio.save_project_state(state, project_dir / "project.xhp")
        self.win.project_state_manager.mark_saved()

        with (
            patch.object(self.win, "show_error") as error,
            patch.object(QtWidgets.QMessageBox, "warning") as warning,
        ):
            self.assertTrue(self.win.project_manager.load_project_dir(project_dir))

        error.assert_not_called()
        warning.assert_not_called()
        self.assertTrue(self.win.project_state_manager.is_dirty)

    def test_dirty_state_tracks_serialized_state_and_can_return_to_clean(self):
        manager = self.win.project_state_manager
        self.assertFalse(manager.is_dirty)

        self.win.source_manager.open_files([self.h5])
        self.assertTrue(manager.compare_now())
        self.assertTrue(self.win.isWindowModified())

        manager.mark_saved()
        self.assertFalse(manager.is_dirty)
        source = self.win.project_data.sources[self.h5]
        original_alias = source.alias
        source.alias = "Changed"
        manager.project_changed()
        self.assertTrue(manager.compare_now())
        source.alias = original_alias
        manager.project_changed()
        self.assertFalse(manager.compare_now())

    def test_dirty_project_replacement_can_be_cancelled_or_discarded(self):
        manager = self.win.project_state_manager
        self.win.source_manager.open_files([self.h5])
        self.assertTrue(manager.compare_now())

        with patch.object(
            QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.Cancel
        ):
            self.assertFalse(manager.prepare_to_leave_project("testing"))
        with patch.object(
            QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.Discard
        ):
            self.assertTrue(manager.prepare_to_leave_project("testing"))
        with (
            patch.object(
                QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.Save
            ),
            patch.object(self.win.project_manager, "save_project", return_value=True) as save,
        ):
            self.assertTrue(manager.prepare_to_leave_project("testing"))
            save.assert_called_once_with()

    def test_dirty_project_is_saved_on_exit_by_default(self):
        manager = self.win.project_state_manager
        self.win.settings.remove(PROJECT_SAVE_ON_EXIT_KEY)
        self.addCleanup(self.win.settings.remove, PROJECT_SAVE_ON_EXIT_KEY)
        self.win.project_dir = Path(self.temp.name) / "saved-project"
        self.win.source_manager.open_files([self.h5])

        with (
            patch.object(self.win.project_manager, "save_project", return_value=True) as save,
            patch.object(QtWidgets.QMessageBox, "question") as question,
        ):
            self.assertTrue(manager.prepare_to_exit())

        save.assert_called_once_with()
        question.assert_not_called()

    def test_unsaved_project_prompts_before_opening_save_as(self):
        manager = self.win.project_state_manager
        self.win.settings.remove(PROJECT_SAVE_ON_EXIT_KEY)
        self.addCleanup(self.win.settings.remove, PROJECT_SAVE_ON_EXIT_KEY)
        self.win.source_manager.open_files([self.h5])

        with (
            patch.object(manager, "_ask_unsaved_exit", return_value="cancel"),
            patch.object(self.win.project_manager, "save_project_as") as save_as,
        ):
            self.assertFalse(manager.prepare_to_exit())
            save_as.assert_not_called()

        with (
            patch.object(manager, "_ask_unsaved_exit", return_value="quit"),
            patch.object(self.win.project_manager, "save_project_as") as save_as,
        ):
            self.assertTrue(manager.prepare_to_exit())
            save_as.assert_not_called()

        with (
            patch.object(manager, "_ask_unsaved_exit", return_value="save_as"),
            patch.object(self.win.project_manager, "save_project_as", return_value=True) as save_as,
        ):
            self.assertTrue(manager.prepare_to_exit())
            save_as.assert_called_once_with()

    def test_quick_quit_does_not_save_dirty_project(self):
        manager = self.win.project_state_manager
        self.win.project_dir = Path(self.temp.name) / "saved-project"
        self.win.source_manager.open_files([self.h5])

        with (
            patch.object(self.win.project_manager, "save_project") as save,
            patch.object(manager, "_ask_unsaved_exit") as question,
        ):
            self.assertTrue(manager.prepare_to_exit(skip_confirmation=True))
        save.assert_not_called()
        question.assert_not_called()

    def test_exit_prompt_remains_available_when_auto_save_is_disabled(self):
        manager = self.win.project_state_manager
        self.win.settings.setValue(PROJECT_SAVE_ON_EXIT_KEY, False)
        self.addCleanup(self.win.settings.remove, PROJECT_SAVE_ON_EXIT_KEY)
        self.win.project_dir = Path(self.temp.name) / "saved-project"
        self.win.source_manager.open_files([self.h5])

        with patch.object(
            QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.Cancel
        ):
            self.assertFalse(manager.prepare_to_exit())

    def test_save_removes_project_autosave(self):
        project_dir = Path(self.temp.name) / "autosave"
        project_dir.mkdir()
        self.win.project_dir = project_dir
        self.win.project_state_manager.mark_saved()
        self.win.source_manager.open_files([self.h5])
        manager = self.win.project_state_manager
        self.assertTrue(manager.compare_now())
        autosave = manager.write_autosave()
        self.assertTrue(autosave.is_file())

        self.assertTrue(self.win.project_manager.save_project())
        self.assertFalse(autosave.exists())
        self.assertFalse(manager.is_dirty)

    def test_returning_to_saved_state_removes_obsolete_autosave(self):
        project_dir = Path(self.temp.name) / "autosave"
        project_dir.mkdir()
        self.win.project_dir = project_dir
        manager = self.win.project_state_manager
        manager.mark_saved()
        saved_layout = self.win.project_data.image_defaults.layout
        changed_layout = next(layout for layout in Layouts if layout != saved_layout)

        self.win.project_data.image_defaults.layout = changed_layout
        self.assertTrue(manager.compare_now())
        autosave = manager.write_autosave()
        self.assertTrue(autosave.is_file())

        self.win.project_data.image_defaults.layout = saved_layout
        self.assertFalse(manager.compare_now())
        self.assertFalse(autosave.exists())

    def test_loading_project_can_recover_autosaved_state(self):
        project_dir = Path(self.temp.name) / "recovery"
        project_dir.mkdir()
        self.win.project_dir = project_dir
        projectio.save_project(self.win.project_data, project_dir / "project.xhp")
        self.win.project_state_manager.mark_saved()

        self.win.source_manager.open_files([self.h5])
        manager = self.win.project_state_manager
        self.assertTrue(manager.compare_now())
        manager.write_autosave()
        manager.mark_saved()

        with patch.object(
            QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.Yes
        ):
            self.assertTrue(self.win.project_manager.load_project_dir(project_dir))
        self.assertIn(self.h5, self.win.project_data.sources)
        self.assertTrue(manager.is_dirty)
        self.assertTrue(self.win.isWindowModified())

    def test_duplicate_open_closes_unused_handle(self):
        from exhale.data.source_refs import open_source

        for filename in (self.h5, self.tiff):
            self.win.source_manager.open_files([filename])
            original = self.win.project_data.sources[filename]
            duplicate = open_source(filename)
            with patch("exhale.project.sourcemanager.open_source", return_value=duplicate):
                self.win.source_manager.open_files([filename])
            self.assertFalse(duplicate.is_open)
            self.assertIs(self.win.project_data.sources[filename], original)
            self.assertTrue(original.is_open)
        self.assertEqual(self.win.loadedFileComboBox.count(), 2)
