#!/usr/bin/env python3
"""Main Exhale window and integration of project, image, and analysis workflows."""

import os

# import importlib
import re
import traceback

# from typing import Optional
# from collections.abc import Iterable
from functools import partial
from time import strftime

import numpy as np
from qtpy import QtCore, QtGui, QtWidgets
from qtpy.QtCore import Qt

from . import appearance, application_description, application_name, application_title, icons
from .analysis_settings_dialog import AnalysisSettingsDialog
from .analysisworker import AnalysisWorker
from .data.constants import CONCENTRATION_UNITS
from .data.elementsettings import ElementSettings, ElementSettingsDefaults, Normalizers
from .data.imagesettings import Colorschemes, ImageSettings, Layouts, Scalebars
from .data.projectdata import (
    DuplicateChannelError,
    ProjectData,
    SampleChannelState,
    SegmentationParameters,
    SegmentationResult,
    shortest_unique_path_suffixes,
)
from .data.source_refs import ElementRef, open_source
from .exceptiondialog import ExceptionDetailsDialog, ExceptionDialog
from .image_settings_dialog import ImageSettingsDialog
from .imagecomposer import ImageComposer
from .listwidgets import ElementListWidget, ImageElementBox, ImageHeaderBox, ImageListWidget
from .main_window_ui import Ui_MainWindow
from .overridecursor import OverrideCursor
from .project_tab import ProjectTab
from .projectmanager import ProjectManager
from .projectstatemanager import ProjectStateManager
from .runtimeinfo import runtime_environment_html
from .segmentationio import result_relative_path, save_xrf_sample
from .settings_dialog import SettingsDialog
from .widgets import IconToolButton, initialize_splitter_on_show

_LOAD_NAPARI_EARLY = True
ACTIVE_TAB_SETTINGS_KEY = "window/active_tab"
WINDOW_GEOMETRY_SETTINGS_KEY = "window/geometry"


def scale_font(widget: QtWidgets.QWidget, scale: float):
    "Rescale font of widget and its children"
    font = widget.font()
    font.setPointSizeF(font.pointSizeF() * scale)
    widget.setFont(font)


class MainWindow(QtWidgets.QMainWindow, Ui_MainWindow):
    """Own the application shell and coordinate feature-specific controllers."""

    channelsChanged = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QtCore.QSettings("CIPA", application_name)
        self.appearance = appearance.initialize(self.settings)
        self.project_dir = None
        self.project_manager = ProjectManager(self)
        # QApplication.instance().installEventFilter(self) # needed why?
        self.setupUi(self)
        self.setWindowTitle(application_title)

        self._exception_dialog = ExceptionDetailsDialog(self)

        imd = ImageSettingsDialog(self)
        self.image_settings_dialog = imd
        self.composeSettings.clicked.connect(imd.show)
        self.composeSettings.clicked.connect(imd.raise_)
        imd.buttonBox.clicked.connect(imd.hide)

        ad = AnalysisSettingsDialog(self)
        self.analysis_settings_dialog = ad
        self.analysisOptions.clicked.connect(ad.show)
        self.analysisOptions.clicked.connect(ad.raise_)
        ad.buttonBox.clicked.connect(ad.hide)

        # Make all the dialog input widgets available in self since it's
        # only an UI detail that they're offloaded to a dialog.
        self.composeScalebarColor = imd.composeScalebarColor
        self.composeScalebarBg = imd.composeScalebarBg
        self.composeScalebarBgColor = imd.composeScalebarBgColor
        self.composeScalebar = imd.composeScalebar
        self.composeFontsize = imd.composeFontsize
        self.composeDPI = imd.composeDPI
        self.composePanelLabels = imd.composePanelLabels
        self.composeElementLabels = imd.composeElementLabels
        self.composeElementBorders = imd.composeElementBorders
        self.composeElementLabelsColored = imd.composeElementLabelsColored
        self.composePanelLabelColor = imd.composePanelLabelColor
        self.applyProjectImageDefaults = imd.applyProjectDefaults
        self.useAsProjectImageDefaults = imd.useAsProjectDefaults
        self.applyProjectImageDefaults.clicked.connect(self.apply_project_image_defaults)
        self.useAsProjectImageDefaults.clicked.connect(self.use_as_project_image_defaults)
        self.clusterMinK = ad.clusterMinK
        self.clusterMaxK = ad.clusterMaxK
        self.clusterNInit = ad.clusterNInit
        self.nucleiExpansion = ad.nucleiExpansion
        self.nucleiMinArea = ad.nucleiMinArea

        self.reload_icons()
        self.appearance.changed.connect(self.reload_appearance)

        self.actionOpenFile.triggered.connect(self.select_and_open_files)
        self.actionClearFiles.triggered.connect(self.close_all_files)
        self.actionNewProject.triggered.connect(self.project_manager.new_project)
        self.actionOpenProject.triggered.connect(self.project_manager.open_project)
        self.actionSaveProject.triggered.connect(self.project_manager.save_project)
        self.actionSaveProjectAs.triggered.connect(self.project_manager.save_project_as)
        self.actionSettings.triggered.connect(self.show_settings)
        self.actionAbout.triggered.connect(self.showAbout)
        self.actionQuit.triggered.connect(self.close)
        self._skip_next_quit_confirmation = False
        QtWidgets.QShortcut(
            QtGui.QKeySequence("Ctrl+Shift+Q"), self, activated=self.quit_without_confirmation
        )

        self.project_data = ProjectData()
        self._element_settings_failures = {}
        self.currentElement = None  # ElementSettings
        self.imageSettings = {}  # id -> ImageSettings
        self.currentImage = None  # ImageSettings

        self.project_tab = ProjectTab(self)

        self.create_dataTab()
        self._splitter_initializer = initialize_splitter_on_show(
            self.splitter, self.dataTab, (1, 1, 2), self.settings.value("window/splitters/splitter")
        )
        self._project_splitter_initializer = initialize_splitter_on_show(
            self.project_tab.splitter,
            self.projectDataTab,
            (2, 2, 1),
            self.settings.value("window/splitters/project_data"),
        )
        self.create_analysisTab()
        self.tabWidget.setCurrentIndex(0)
        self.project_state_manager = ProjectStateManager(self)
        self.project_state_manager.connect_sources()
        self.project_state_manager.dirtyChanged.connect(lambda _dirty: self.update_window_title())
        self.project_state_manager.mark_saved()
        self.update_window_title()
        geometry = self.settings.value(WINDOW_GEOMETRY_SETTINGS_KEY)
        if isinstance(geometry, QtCore.QByteArray):
            self.restoreGeometry(geometry)

    def update_window_title(self):
        project_name = self.project_dir.name if self.project_dir is not None else "Untitled"
        self.setWindowTitle(f"{application_title} — {project_name}[*]")
        dirty = getattr(self, "project_state_manager", None)
        self.setWindowModified(dirty is not None and dirty.is_dirty)

    def closeEvent(self, ev):
        skip_confirmation = self._skip_next_quit_confirmation
        self._skip_next_quit_confirmation = False
        if not self.project_state_manager.prepare_to_exit(skip_confirmation=skip_confirmation):
            ev.ignore()
            return
        self.image_settings_dialog.close()
        self.analysis_settings_dialog.close()
        if self._analysisWorker is not None:
            self._analysisWorker.abort()
            self._analysisThread.wait()
        if self._splitter_initializer.initialized:
            self.settings.setValue("window/splitters/splitter", self.splitter.saveState())
        if self._project_splitter_initializer.initialized:
            self.settings.setValue(
                "window/splitters/project_data", self.project_tab.splitter.saveState()
            )
        current_tab = self.tabWidget.currentWidget()
        if current_tab is not None:
            self.settings.setValue(ACTIVE_TAB_SETTINGS_KEY, current_tab.objectName())
        self.settings.setValue(WINDOW_GEOMETRY_SETTINGS_KEY, self.saveGeometry())
        ev.accept()

    def _restore_active_tab(self):
        """Restore global workspace state without affecting the project state."""
        object_name = self.settings.value(ACTIVE_TAB_SETTINGS_KEY)
        if not isinstance(object_name, str):
            return
        for index in range(self.tabWidget.count()):
            if self.tabWidget.widget(index).objectName() == object_name:
                self.tabWidget.setCurrentIndex(index)
                return

    def quit_without_confirmation(self):
        """Close immediately without showing the exit question."""
        self._skip_next_quit_confirmation = True
        self.close()

    def reload_icons(self):
        """Reload palette-dependent icons throughout the main window."""
        self.actionOpenFile.setIcon(icons.icon(icons.IconName.OPEN))
        self.actionClearFiles.setIcon(icons.icon(icons.IconName.CLEAR_FILES))
        self.actionOpenProject.setIcon(icons.icon(icons.IconName.PROJECT))
        self.actionSaveProject.setIcon(icons.icon(icons.IconName.SAVE))
        self.actionSaveProjectAs.setIcon(icons.icon(icons.IconName.SAVE_AS))
        self.actionSettings.setIcon(icons.icon(icons.IconName.SETTINGS))
        self.actionAbout.setIcon(icons.icon(icons.IconName.INFO))
        self.actionQuit.setIcon(icons.icon(icons.IconName.QUIT))
        self.addProjectFilesButton.setIcon(icons.icon(icons.IconName.OPEN))
        self.refreshChannelsButton.setIcon(icons.icon(icons.IconName.REFRESH))
        self.addImageButton.set_icon_name(icons.IconName.ADD_IMAGE)
        self.addImageButton.setToolTip("Add image")
        self.deleteImageButton.set_icon_name(icons.IconName.DELETE)
        self.deleteImageButton.setToolTip("Delete image")
        self.showSingleElementButton.set_icon_name(icons.IconName.ELEMENT_ONLY)
        self.composeSave.setIcon(icons.icon(icons.IconName.IMAGE))
        for button in self.findChildren(IconToolButton):
            button.reload_icon()

    def reload_appearance(self):
        """Refresh components that cache palette-derived resources."""
        icons.initialize()
        self.reload_icons()
        self.elementPlot.reload_appearance()
        self.elementHistogramPlot.reload_appearance()
        self.elementList.reload_icons()
        self.imageList.reload_icons()
        self.project_tab.reload_icons()
        self.analysisLayerList.reload_appearance()
        if getattr(self, "naparihelper", None) is not None:
            self.naparihelper.set_theme("dark" if appearance.is_dark() else "light")

    def show_settings(self):
        SettingsDialog(self.settings, self).exec()

    def show_error(self, summary, details=None, title="Error"):
        summary = str(summary)
        if details is None:
            details = summary
        else:
            details = str(details)
            if (
                details != summary
                and not details.startswith(summary + "\n")
                and not details.rstrip().endswith(summary)
            ):
                details = f"{summary}\n\n{details}"
        self._exception_dialog.show_exception(title=title, summary=summary, details=details)

    def show_tiff_read_error(self, filenames, error):
        """Report an expected TIFF input or decoder failure without an internal-error trace."""
        if isinstance(filenames, (str, os.PathLike)):
            filenames = [filenames]
        paths = "\n".join(map(str, filenames))
        if "requires the 'imagecodecs' package" in str(error):
            message = (
                "The TIFF compression requires the optional Python package imagecodecs. "
                "Install imagecodecs in Exhale's Python environment and try again."
            )
        else:
            message = f"Exhale could not read the element maps in the TIFF file.\n\n{error}"
        QtWidgets.QMessageBox.warning(
            self,
            "Cannot read TIFF file",
            f"{message}\n\nFile:\n{paths}",
        )

    def showAbout(self):
        """Show application credits and the detected runtime environment."""
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(f"About {application_name}")
        layout = QtWidgets.QVBoxLayout(dialog)

        heading = QtWidgets.QHBoxLayout()
        logo_height = round(self.fontMetrics().height() * 4)
        pixmap = icons.icon_pixmap(icons.IconName.LOGO, logo_height)
        logo = QtWidgets.QLabel(dialog)
        logo.setPixmap(pixmap)
        logo.setFixedSize(pixmap.size())
        heading.addWidget(logo, 0, QtCore.Qt.AlignVCenter)
        title = QtWidgets.QLabel(
            f'<span style="font-size: xx-large; font-weight: bold">{application_title}</span>',
            dialog,
        )
        title.setTextFormat(QtCore.Qt.RichText)
        heading.addWidget(title, 0, QtCore.Qt.AlignVCenter)
        layout.addLayout(heading)

        information = QtWidgets.QLabel(
            f"""
<p>{application_name} ({application_description}) is part of the<br>
{application_name} project at Lund University and MAX IV,<br>
<a href="https://www.vr.se/english/swecris.html?project=2023-02821_Vinnova#/">
funded by Vinnova</a>.</p>
<p>Copyright © 2023–2026 Carl Troein, Tom Delaire,<br>
Bryan Falcones, Emanuel Larsson and Karina Thånell<br>
Licensed under the MIT License.</p>
<b>Runtime environment</b>{runtime_environment_html()}
""",
            dialog,
        )
        information.setTextFormat(QtCore.Qt.RichText)
        information.setOpenExternalLinks(True)
        information.setWordWrap(False)
        layout.addWidget(information)

        attribution = QtWidgets.QLabel(
            'Icons derived from <a href="https://tabler.io/icons">Tabler Icons</a> '
            "by Paweł Kuna, available under the MIT licence.",
            dialog,
        )
        attribution.setTextFormat(QtCore.Qt.RichText)
        attribution.setOpenExternalLinks(True)
        layout.addWidget(attribution)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok, parent=dialog)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        layout.setSizeConstraint(QtWidgets.QLayout.SetFixedSize)
        dialog.exec()

    def open_file_count(self):
        return sum(1 for fs in self.project_data.sources.values() if fs.is_open)

    def source_alias_for_ref(self, ref: ElementRef):
        asset = self.project_data.assets.get(ref.source_id)
        if asset is not None:
            return self.project_data.samples[asset.sample_id].name
        return ref.source_id

    def element_display_name(self, ref: ElementRef, *, force_alias=False):
        es = self.project_data.element_settings[ref]
        label = es.name
        if force_alias or len(self.project_data.samples) > 1:
            label = f"{label} ({self.source_alias_for_ref(ref)})"
        fs = self.project_data.sources.get(ref.source_id)
        if fs is not None and not fs.is_open:
            label += " [closed]"
        return label

    def element_local_display_name(self, ref):
        source = self.project_data.sources.get(ref.source_id)
        orig = (
            source.default_element_name(ref)
            if source is not None
            else ref.item_id.rsplit("/", 1).pop()
        )
        es = self.project_data.element_settings.get(ref)
        if es is not None and es.name != orig:
            return f"{es.name} ({orig})"
        return orig

    # All about the analysis tab

    def create_analysisTab(self):
        "Prepare data analysis tab with Napari viewer"
        self.naparihelper = None
        self._analysisWorker = None
        self._analysisThread = None
        self._analysis_result_sample_id = None

        def tab_check():
            if self.tabWidget.currentWidget() != self.analysisTab:
                return
            if self.naparihelper is None:
                self.initialize_analysisTab()
            self.analysis_sample_changed()

        self.tabWidget.currentChanged.connect(tab_check)
        if _LOAD_NAPARI_EARLY:
            self.initialize_analysisTab()

    def initialize_analysisTab(self):
        "Initialize the data analysis tab; start Napari viewer etc"
        from .naparihelper import NapariHelper

        self.naparihelper = NapariHelper("dark" if appearance.is_dark() else "light")
        self.analysisLayerList.set_helper(self.naparihelper)
        self.naparihelper.set_info_widget(self.analysisInfo)

        self.analysisSplitter.setSizes([180, 400, 200])
        self.analysisLeftSplitter.setSizes([400, 200])
        self.analysisRightSplitter.setSizes([400, 200])
        hb = QtWidgets.QHBoxLayout()
        hb.setContentsMargins(0, 0, 0, 0)
        hb.addWidget(self.naparihelper.qtwidget, 1)
        self.napariWidget.setLayout(hb)

        scale_font(self.analysisStatus, 0.8)
        self.analysisSampleComboBox.currentIndexChanged.connect(self.analysis_sample_changed)
        self.channelsChanged.connect(self.update_analysis_channels)
        self.update_analysis_channels()
        self.channelsChanged.connect(self.update_analysis_elements)
        self.update_analysis_elements()
        self.analysisRun.pressed.connect(self.run_analysis)

        def abort_run():
            if self._analysisWorker is not None:
                self._analysisWorker.abort()

        self.analysisAbort.pressed.connect(abort_run)
        self.analysisExport.clicked.connect(self.export_analysis_results)
        self.set_analysis_busy(False)

    def current_analysis_sample(self):
        """Return the sample selected on the Segmentation tab."""
        return self.project_data.samples.get(self.analysisSampleComboBox.currentData())

    def analysis_sample_changed(self):
        """Update segmentation inputs for the independently selected sample."""
        sample = self.current_analysis_sample()
        sample_id = None if sample is None else sample.sample_id
        self.update_analysis_channels()
        self.update_analysis_elements()
        result = self.project_data.segmentation_results.get(sample_id)
        if result is None:
            self._clear_segmentation_result_view()
        else:
            self._show_segmentation_result(result)

    def _segmentation_parameters(self):
        return SegmentationParameters(
            nuclei_expansion=self.nucleiExpansion.value(),
            nuclei_min_area=self.nucleiMinArea.value(),
            cluster_min_k=self.clusterMinK.value(),
            cluster_max_k=self.clusterMaxK.value(),
            cluster_n_init=self.clusterNInit.value(),
        )

    def _set_segmentation_parameters(self, parameters):
        controls = (
            (self.nucleiExpansion, parameters.nuclei_expansion),
            (self.nucleiMinArea, parameters.nuclei_min_area),
            (self.clusterMinK, parameters.cluster_min_k),
            (self.clusterMaxK, parameters.cluster_max_k),
            (self.clusterNInit, parameters.cluster_n_init),
        )
        blockers = [QtCore.QSignalBlocker(control) for control, _value in controls]
        for control, value in controls:
            control.setValue(value)
        del blockers

    def _clear_segmentation_result_view(self):
        if self.naparihelper is None:
            return
        self.naparihelper.set_sample(None)
        self._analysis_result_sample_id = None
        self.analysisInfo.clear()
        self.update_layer_controls()
        self.analysisExport.setEnabled(False)

    def _show_segmentation_result(self, result):
        for selector, ref in (
            (self.analysisChNuclei, result.nuclei_ref),
            (self.analysisChTissue, result.tissue_ref),
        ):
            index = self._combo_index_for_data(selector, ref)
            if index >= 0:
                selector.setCurrentIndex(index)

        selected_refs = set(result.element_refs)
        with QtCore.QSignalBlocker(self.analysisElements):
            for row in range(self.analysisElements.count()):
                item = self.analysisElements.item(row)
                ref = item.data(ElementListWidget.ELEMENT_REF_ROLE)
                item.setCheckState(
                    Qt.CheckState.Checked if ref in selected_refs else Qt.CheckState.Unchecked
                )
        self._set_segmentation_parameters(result.parameters)
        if self.naparihelper is None:
            return
        self.naparihelper.set_sample(result.xrf_sample, self._segmentation_element_maps(result))
        self._analysis_result_sample_id = result.sample_id
        self.update_layer_controls()
        self.analysisExport.setEnabled(True)

    def _segmentation_element_maps(self, result):
        """Return current transformed sample maps in segmentation element order."""
        sample = self.project_data.samples[result.sample_id]
        effective_by_ref = {
            channel.ref: channel
            for channel in sample.effective_channels(self.project_data.project_channels).values()
        }
        maps = []
        for ref in result.element_refs:
            channel = effective_by_ref.get(ref)
            settings = None if channel is None else channel.settings
            if settings is None:
                settings = self._ensure_element_settings(ref)
            maps.append(settings.transformedData())
        return tuple(maps)

    def update_analysis_channels(self):
        "Update the nuclei/tissue selectors from the active sample."
        channels = self._effective_analysis_channels()
        for dd in (self.analysisChNuclei, self.analysisChTissue):
            ddref = dd.currentData()
            with QtCore.QSignalBlocker(dd):
                dd.clear()
                dd.addItem("None", None)
                for channel in channels:
                    dd.addItem(channel.name, userData=channel.ref)
                index = self._combo_index_for_data(dd, ddref)
                if index >= 0:
                    dd.setCurrentIndex(index)

    def update_analysis_elements(self):
        "Update the analysis element list from the active sample."
        unchecked_refs = set()
        for row in range(self.analysisElements.count()):
            item = self.analysisElements.item(row)
            if item.checkState() == Qt.CheckState.Unchecked:
                unchecked_refs.add(item.data(ElementListWidget.ELEMENT_REF_ROLE))
        with QtCore.QSignalBlocker(self.analysisElements):
            self.analysisElements.clear()
            for channel in self._effective_analysis_channels():
                self.analysisElements.addChannel(
                    channel.name,
                    channel.key,
                    channel.ref,
                    Qt.CheckState.Unchecked
                    if channel.ref in unchecked_refs
                    else Qt.CheckState.Checked,
                )

    def _effective_analysis_channels(self):
        sample = self.current_analysis_sample()
        if sample is None:
            return []
        return sorted(
            (
                channel
                for channel in sample.effective_channels(
                    self.project_data.project_channels
                ).values()
                if channel.ref in self.project_data.element_settings
            ),
            key=lambda channel: (channel.name.casefold(), channel.key.casefold()),
        )

    def _analysis_element_settings(self, refs):
        effective = {channel.ref: channel for channel in self._effective_analysis_channels()}
        settings = []
        for ref in refs:
            channel = effective.get(ref)
            if channel is None:
                raise ValueError("The selected analysis channel is no longer available")
            asset = self.project_data.assets.get(ref.source_id)
            if asset is None or not asset.is_available:
                raise RuntimeError(
                    f"Channel {channel.name!r} is unavailable because {ref.source_id!r} is not open"
                )
            settings.append(self._ensure_element_settings(ref))
        return settings

    def update_layer_controls(self):
        "Update the layer list in the analysis tab"
        self.analysisLayerList.rebuild()

    def set_analysis_busy(self, busy):
        self.analysisRun.setEnabled(not busy)
        self.analysisSampleComboBox.setEnabled(not busy)
        self.analysisChNuclei.setEnabled(not busy)
        self.analysisChTissue.setEnabled(not busy)
        self.analysisElements.setEnabled(not busy)
        self.analysisOptions.setEnabled(not busy)
        self.analysisProgress.setRange(0, 0 if busy else 1)
        self.clusterMinK.setEnabled(not busy)
        self.clusterMaxK.setEnabled(not busy)
        self.clusterNInit.setEnabled(not busy)
        self.nucleiExpansion.setEnabled(not busy)
        self.nucleiMinArea.setEnabled(not busy)
        self.analysisExport.setEnabled(
            not busy and self.naparihelper is not None and self.naparihelper.sample is not None
        )
        self.analysisAbort.setEnabled(busy)

    def run_analysis(self):
        """Validate the selected sample and start its background segmentation."""

        if self._analysisWorker is not None:
            raise RuntimeError("Analysis worker already running")
        if self.project_dir is None:
            QtWidgets.QMessageBox.information(
                self,
                "Save project before segmentation",
                "Segmentation results are stored in the project directory. "
                "Save the project before running segmentation.",
            )
            return

        def append_status(msg):
            self.analysisStatus.appendPlainText(strftime("[%T] ") + msg)
            self.analysisStatus.ensureCursorVisible()

        self.analysisStatus.clear()
        append_status("Initializing")

        sample = self.current_analysis_sample()
        if sample is None:
            self.show_error("Select a sample first.")
            return
        analysis_sample_id = sample.sample_id

        dds = (self.analysisChNuclei, self.analysisChTissue)
        ddrefs = [dd.currentData() for dd in dds]
        if None in ddrefs:
            self.show_error("Select channels for nuclei and tissue first.")
            return

        # if ddrefs[0] == ddrefs[1]:
        #     self.show_error("Nuclei and tissue channels must differ.")
        #     return
        element_refs = [
            it.data(ElementListWidget.ELEMENT_REF_ROLE)
            for it in (
                self.analysisElements.item(row) for row in range(self.analysisElements.count())
            )
            if it.checkState() == Qt.CheckState.Checked
        ]
        parameters = self._segmentation_parameters()

        try:
            nuclei_settings, tissue_settings = self._analysis_element_settings(ddrefs)
            element_settings = self._analysis_element_settings(element_refs)
        except (KeyError, RuntimeError, ValueError) as exc:
            self.show_error("Cannot start analysis", str(exc))
            return

        thread = QtCore.QThread(self)
        worker = AnalysisWorker(
            nuclei_settings,
            tissue_settings,
            element_settings,
            sample_name=sample.name,
            nuclei_expansion_px=parameters.nuclei_expansion,
            nuclei_min_area=parameters.nuclei_min_area,
            cluster_min_k=parameters.cluster_min_k,
            cluster_max_k=parameters.cluster_max_k,
            cluster_n_init=parameters.cluster_n_init,
        )
        worker.moveToThread(thread)
        worker.progress.connect(append_status)

        def worker_cleanup():
            self._analysisWorker.deleteLater()
            self._analysisWorker = None
            self._analysisThread.quit()
            self._analysisThread = None
            self.set_analysis_busy(False)

        @QtCore.Slot()
        def on_finished(xrf_sample):
            append_status("Saving results")
            result = SegmentationResult(
                sample_id=analysis_sample_id,
                nuclei_ref=ddrefs[0],
                tissue_ref=ddrefs[1],
                element_refs=tuple(element_refs),
                parameters=parameters,
                xrf_sample=xrf_sample,
            )
            try:
                save_xrf_sample(
                    xrf_sample,
                    self.project_dir / result_relative_path(analysis_sample_id),
                )
            except Exception as exc:
                append_status("Failed to save results")
                self.show_error("Saving segmentation results failed", str(exc))
                worker_cleanup()
                return
            self.project_data.segmentation_results[analysis_sample_id] = result
            self.project_state_manager.project_changed()
            append_status("Rendering results")
            self._show_segmentation_result(result)
            worker_cleanup()
            append_status("Done")

        @QtCore.Slot()
        def on_failed(details):
            if details == "":
                append_status("Interrupted")
            else:
                append_status("Failed")
                self.show_error("Analysis failed", details)
            worker_cleanup()

        self.set_analysis_busy(True)
        worker.finished.connect(on_finished)
        worker.failed.connect(on_failed)
        thread.started.connect(worker.run)
        # thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._analysisWorker = worker
        self._analysisThread = thread
        thread.start()

    def export_analysis_results(self):
        """Export the currently displayed analysis tables to a chosen directory."""

        sample = self.naparihelper.sample
        if sample is None:
            return
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Choose export directory",
            str(self.project_dir / "exports")
            if self.project_dir is not None
            else self.settings.value("AnalysisExportDir", ""),
        )
        if not directory:
            return
        self.settings.setValue("AnalysisExportDir", directory)

        try:
            out = sample.export_results(directory)
        except Exception as e:
            self.show_error("Export failed", str(e))
            return
        QtWidgets.QMessageBox.information(
            self, "Export complete", f"Analysis results exported to:\n{out}"
        )

    # All about the data/elements/images tab

    def current_sample(self):
        sample_id = self.loadedFileComboBox.currentData()
        return self.project_data.samples.get(sample_id)

    def _ensure_element_settings(self, ref):
        if ref in self.project_data.element_settings:
            return self.project_data.element_settings[ref]
        source = self.project_data.sources[ref.source_id]
        if not source.is_open:
            raise RuntimeError("Attempting to access closed file " + ref.source_id)
        _sample, channel = self.project_data.channel_for_ref(ref)
        settings = ElementSettings(
            ref=ref,
            name=channel.name,
            data=channel.data_source,
            defaults=self.project_data.element_defaults,
        )
        self.project_data.set_element_settings(ref, settings)
        return settings

    def _effective_channels_changed(self):
        changed_images = set()
        for image_id, image in self.imageSettings.items():
            sample = self.project_data.samples.get(image.sample_id)
            available_keys = (
                ()
                if sample is None
                else sample.effective_channels(self.project_data.project_channels)
            )
            if image.reconcileChannels(available_keys):
                changed_images.add(image_id)

        failures = []
        for ref in self.project_data.effective_refs():
            if ref in self._element_settings_failures:
                continue
            try:
                self._ensure_element_settings(ref)
            except Exception as exc:
                self._element_settings_failures[ref] = str(exc)
                failures.append((ref, exc))
        self.channelsChanged.emit()
        current_item = self.imageList.currentItem()
        current_image_id = (
            None if current_item is None else current_item.data(ImageListWidget.IMG_NUM_ROLE)
        )
        if current_image_id in changed_images:
            self.showComposedImage(current_image_id)
            self.updateComposedImage(reset_view=True)
        if failures:
            error = next(
                (exc for _ref, exc in failures if "requires the 'imagecodecs' package" in str(exc)),
                failures[0][1],
            )
            self.show_tiff_read_error(sorted({ref.source_id for ref, _exc in failures}), error)

    @staticmethod
    def _channel_list_label(key, name):
        return key if name == key else f"{name} [{key}]"

    @staticmethod
    def _combo_index_for_data(combo, target):
        """Find Python object data without relying on QVariant identity semantics."""
        return next(
            (index for index in range(combo.count()) if combo.itemData(index) == target),
            -1,
        )

    def refresh_sample_selector(self, selected=None):
        if selected is None:
            selected = self.loadedFileComboBox.currentData()
        samples = list(self.project_data.samples.values())
        paths = [
            self.project_data.assets[sample.asset_ids[0]].path
            for sample in samples
            if sample.asset_ids
        ]
        suffixes = shortest_unique_path_suffixes(paths) if paths else {}
        name_counts = {}
        for sample in samples:
            name_counts[sample.name] = name_counts.get(sample.name, 0) + 1

        entries = []
        for sample in samples:
            label = sample.name
            if name_counts[label] > 1 and sample.asset_ids:
                path = self.project_data.assets[sample.asset_ids[0]].path
                label = f"{label} — {suffixes[path]}"
            entries.append((label, sample.sample_id))

        analysis_selected = self.analysisSampleComboBox.currentData()
        if analysis_selected not in self.project_data.samples:
            analysis_selected = selected
        for combo, combo_selected in (
            (self.loadedFileComboBox, selected),
            (self.analysisSampleComboBox, analysis_selected),
        ):
            with QtCore.QSignalBlocker(combo):
                combo.clear()
                for label, sample_id in entries:
                    combo.addItem(label, sample_id)
                index = combo.findData(combo_selected)
                combo.setCurrentIndex(index if index >= 0 else (0 if samples else -1))
        if hasattr(self, "project_tab"):
            self.project_tab.refresh(selected)
        self.loadedFileChanged()
        if getattr(self, "naparihelper", None) is not None:
            self.analysis_sample_changed()

    def loadedFileChanged(self):
        "Update the project or sample channels shown in the UI."
        sample = self.current_sample()
        self.label.setText("Sample elements")
        self.addImageButton.setEnabled(sample is not None)
        self._refresh_image_list(None if sample is None else sample.sample_id)

        self.currentElement = None
        self.setElementControlsEnabled(False)
        with QtCore.QSignalBlocker(self.elementList):
            self.elementList.clear()
            if sample is None:
                keys = {key for item in self.project_data.samples.values() for key in item.channels}
                keys = sorted(keys, key=str.casefold)
                for key in keys:
                    project_channel = self.project_data.project_channels.get(key)
                    available = next(
                        item.channels[key]
                        for item in self.project_data.samples.values()
                        if key in item.channels
                    )
                    name = project_channel.name if project_channel is not None else available.name
                    self.elementList.addChannel(
                        self._channel_list_label(key, name),
                        key,
                        available.ref,
                        Qt.CheckState.Checked
                        if project_channel is not None
                        else Qt.CheckState.Unchecked,
                    )
                self.channelsChanged.emit()
                return

            keys = sorted(
                sample.channels,
                key=lambda key: (key not in self.project_data.project_channels, key.casefold()),
            )
            has_project_elements = any(key in self.project_data.project_channels for key in keys)
            divider_added = False
            for key in keys:
                channel = sample.channels[key]
                state = self.project_data.sample_channel_state(sample.sample_id, key)
                deferred = key not in sample.channel_overrides
                if state == SampleChannelState.INHERIT:
                    name = self.project_data.project_channels[key].name
                elif state == SampleChannelState.OVERRIDE:
                    override = sample.channel_overrides[key]
                    name = override.name or channel.name
                else:
                    name = channel.name
                self.elementList.addSampleChannel(
                    self._channel_list_label(key, name),
                    key,
                    channel.ref,
                    state,
                    deferred=deferred,
                    project_enabled=key in self.project_data.project_channels,
                    group_divider=(
                        has_project_elements
                        and key not in self.project_data.project_channels
                        and not divider_added
                    ),
                )
                if key not in self.project_data.project_channels:
                    divider_added = True
        self.channelsChanged.emit()

    def refresh_current_channel_states(self):
        "Update sample checkbox states without rebuilding the list."
        sample = self.current_sample()
        if sample is None:
            return
        with QtCore.QSignalBlocker(self.elementList):
            for row in range(self.elementList.count()):
                item = self.elementList.item(row)
                key = item.data(ElementListWidget.CHANNEL_KEY_ROLE)
                state = self.project_data.sample_channel_state(sample.sample_id, key)
                ElementListWidget.updateSampleChannel(
                    item,
                    state,
                    deferred=key not in sample.channel_overrides,
                    project_enabled=key in self.project_data.project_channels,
                )

    def _cycle_sample_element_state(self, item):
        sample = self.current_sample()
        if sample is None:
            return
        key = item.data(ElementListWidget.CHANNEL_KEY_ROLE)
        ref = item.data(ElementListWidget.ELEMENT_REF_ROLE)
        if key not in sample.channel_overrides:
            settings = self._ensure_element_settings(ref)
            self.project_data.override_sample_channel(sample.sample_id, key, settings=settings)
        elif sample.channel_overrides[key] is not None:
            self.project_data.skip_sample_channel(sample.sample_id, key)
        else:
            self.project_data.revert_sample_channel(sample.sample_id, key)
        self._effective_channels_changed()
        self.refresh_current_channel_states()
        self.project_tab.refresh_sample_maps()
        self.project_tab._refresh_map_counts()
        self.project_state_manager.project_changed()

    def _skip_sample_element(self, item):
        sample = self.current_sample()
        if sample is None:
            return
        key = item.data(ElementListWidget.CHANNEL_KEY_ROLE)
        self.project_data.skip_sample_channel(sample.sample_id, key)
        self._effective_channels_changed()
        self.refresh_current_channel_states()
        self.project_tab.refresh_sample_maps()
        self.project_tab._refresh_map_counts()
        self.project_state_manager.project_changed()

    def setImageControlsEnabled(self, enabled: bool):
        "Enable/disable inputs that are relevant to composing an image"
        for o in [
            self.composeLayoutCB,
            self.composeColors,
            self.composeSave,
            self.composeSettings,
            self.composeScalebar,
            self.composeScalebarColor,
            self.composeScalebarBg,
            self.composeScalebarBgColor,
            self.composeElementBorders,
            self.applyProjectImageDefaults,
            self.useAsProjectImageDefaults,
        ]:
            o.setEnabled(enabled)
        self.imageHeaderBox.setWidgetsEnabled(enabled)
        for box in self.imageElementBoxes:
            box.setWidgetsEnabled(enabled)
        self._update_image_show_buttons()

    def _update_image_show_buttons(self):
        if not hasattr(self, "imageElementBoxes"):
            return
        active_slots = set() if self.currentImage is None else set(self.currentImage.elements)
        controls_enabled = self.composeLayoutCB.isEnabled()
        for slot, box in enumerate(self.imageElementBoxes):
            box.edit.setEnabled(controls_enabled and slot in active_slots)

    def setElementControlsEnabled(self, enabled: bool):
        "Show element settings only while an element is being edited."
        was_visible = not self.elementSettingsPanel.isHidden()
        if was_visible == enabled:
            return
        splitter_sizes = self.splitter.sizes()
        self.elementSettingsPanel.setVisible(enabled)

        def finish_layout_change():
            if sum(splitter_sizes) > 0:
                self.splitter.setSizes(splitter_sizes)
            self.elementPlot.fit_image()

        # Wait until the panel visibility has changed the canvas geometry.
        timer = QtCore.QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(finish_layout_change)
        timer.timeout.connect(timer.deleteLater)
        timer.start(0)

    def updateElementNormalizer(self):
        "Hide/show gamma correction and update histogram logscaleness"
        es = self.currentElement
        bins = 256
        if es.normalizer == Normalizers.LOG:
            bins = np.geomspace(es.minPositive, es.dataRange[1], bins + 1)
            histogram_range = None
        else:
            histogram_range = (min(0, es.dataRange[0]), es.dataRange[1])
        hist, edges = np.histogram(es.data, bins=bins, range=histogram_range)
        self.elementHistogramPlot.set_histogram(
            hist, edges, logarithmic=es.normalizer == Normalizers.LOG
        )
        isgamma = es.normalizer == Normalizers.GAMMA
        self.gammaValue.setHidden(not isgamma)

    def updateElementPlot(self):
        "Update the visible image after an element transformation changes."
        if self.currentElement is not None:
            if self.currentImage is not None:
                self.updateComposedImage()
            else:
                self._display_current_element()

    def _display_current_element(self, *, reset_view=False):
        "Display the selected element without changing its editing context."
        if self.currentElement is None:
            return
        self.imageComposer.coord_mapping = None
        self.elementPlot.set_image(self.currentElement.transformedData(), reset_view=reset_view)

    def showCurrentElement(self):
        "Enable and update the input fields with currentElement data"
        es = self.currentElement
        self.setElementControlsEnabled(True)
        slot = self.imageElementButtonGroup.checkedId() if self.currentImage is not None else -1
        is_image_element = self.currentImage is not None and slot >= 0
        is_override = is_image_element and slot in self.currentImage.element_overrides
        self.imageChannelNameLabel.setVisible(is_image_element)
        self.imageSettingsScopeCombo.setVisible(is_image_element)
        self.showSingleElementButton.setVisible(is_image_element)
        if is_image_element:
            key = self.currentImage.channel_keys[slot]
            project_channel = self.project_data.project_channels.get(key)
            name = project_channel.name if project_channel is not None else self.currentElement.name
            self.imageChannelNameLabel.setText(f"{name}:")
            with QtCore.QSignalBlocker(self.imageSettingsScopeCombo):
                self.imageSettingsScopeCombo.setCurrentIndex(1 if is_override else 0)
        with QtCore.QSignalBlocker(self.elementNormalizer):
            self.elementNormalizer.setCurrentIndex(es.normalizer.value)
        with QtCore.QSignalBlocker(self.elementName):
            self.elementName.setText(es.name)
        with QtCore.QSignalBlocker(self.gammaValue):
            self.gammaValue.setValue(es.gamma)
        lower_bound = 0 if es.normalizer == Normalizers.LOG else min(0, es.dataRange[0])
        for mm in range(2):
            with QtCore.QSignalBlocker(self.elementNormalizeRange[mm]):
                self.elementNormalizeRange[mm].setRange(lower_bound, es.dataRange[1])
                self.elementNormalizeRange[mm].setValue(es.trfRange[mm])

        self.updateElementNormalizer()
        self.elementHistogramPlot.set_limits(*es.trfRange)
        if self.currentImage is None or self.showSingleElementButton.isChecked():
            self._display_current_element(reset_view=True)

    def editElement(self, elementref):
        "Big UI update when an element is selected for editing"
        # The element should already have settings at this point
        es = self.project_data.element_settings[elementref]
        self.currentElement = es
        self.currentImage = None
        with QtCore.QSignalBlocker(self.imageList):
            self.imageList.setCurrentRow(-1)
        self.setImageControlsEnabled(False)
        self.showCurrentElement()

    def storeImageSettings(self, im: ImageSettings):
        "Copy settings from UI to object"
        im.setColorscheme(Colorschemes(self.composeColors.currentIndex()))
        im.setLayout(Layouts(self.composeLayoutCB.currentIndex()))
        im.setScalebar(Scalebars(self.composeScalebar.currentIndex()))
        im.setScalebarColors(
            self.composeScalebarColor.color(),
            self.composeScalebarBgColor.color(),
            0.5 if self.composeScalebarBg.isChecked() else None,
        )
        im.setFontsize(self.composeFontsize.value())
        im.setDPI(self.composeDPI.value())
        im.setLabels(self.composePanelLabels.isChecked(), self.composeElementLabels.isChecked())
        im.setPanelLabelColor(self.composePanelLabelColor.color())
        im.setElementBorders(self.composeElementBorders.isChecked())
        im.setElementLabelsColored(self.composeElementLabelsColored.isChecked())

    def apply_project_image_defaults(self):
        """Apply the project's presentation defaults to the current image."""
        if self.currentImage is None:
            return
        self.currentImage.applyPresentationFrom(self.project_data.image_defaults)
        item = self.imageList.currentItem()
        if item is not None:
            self.showComposedImage(item.data(ImageListWidget.IMG_NUM_ROLE))
            self.updateComposedImage(reset_view=True)
        self.project_state_manager.project_changed()

    def use_as_project_image_defaults(self):
        """Store the current image's presentation as the project defaults."""
        if self.currentImage is None:
            return
        self.project_data.image_defaults.applyPresentationFrom(self.currentImage)
        self.project_state_manager.project_changed()

    def _refresh_image_list(self, sample_id, selected_image_id=None):
        "Show only images belonging to the selected data sample."
        if selected_image_id is None:
            item = self.imageList.currentItem()
            if item is not None:
                selected_image_id = item.data(ImageListWidget.IMG_NUM_ROLE)

        self.currentImage = None
        with QtCore.QSignalBlocker(self.imageList):
            self.imageList.clear()
            for num, image in sorted(self.imageSettings.items()):
                if image.sample_id == sample_id and sample_id is not None:
                    self.imageList.addImage(num, image)
            row = next(
                (
                    row
                    for row in range(self.imageList.count())
                    if self.imageList.item(row).data(ImageListWidget.IMG_NUM_ROLE)
                    == selected_image_id
                ),
                0 if self.imageList.count() else -1,
            )
            self.imageList.setCurrentRow(row)

        if self.imageList.currentItem() is not None:
            image_id = self.imageList.currentItem().data(ImageListWidget.IMG_NUM_ROLE)
            self.showComposedImage(image_id)
            self.updateComposedImage(reset_view=True)
        else:
            self.setImageControlsEnabled(False)
            self.elementPlot.clear_image()

    def createImage(self, name=None):
        "Add the named composed image to the list of images (and display it?)"
        sample = self.current_sample()
        if sample is None:
            return
        num = max(self.imageSettings.keys()) + 1 if self.imageSettings else 1
        im = self.project_data.image_defaults.copyForSample(
            "New image" if name is None else name, sample.sample_id, sample.asset_ids
        )
        self.imageSettings[num] = im
        self.imageList.addImage(num, im)

    def _sample_element_for_image_slot(self, image, slot):
        "Return the sample settings selected by an image slot."
        sample = self.project_data.samples[image.sample_id]
        key = image.channel_keys[slot]
        channel = sample.channels[key]
        return self._ensure_element_settings(channel.ref)

    def updateComposedImage(self, reset_view=False):
        "Recompute and replace/draw the composed image"
        if im := self.currentImage:
            if self.currentElement is not None and self.showSingleElementButton.isChecked():
                self._display_current_element(reset_view=reset_view)
                return
            try:
                self.imageComposer.display_composed_image(
                    self.elementPlot, im, reset_view=reset_view
                )
            except (OSError, RuntimeError) as exc:
                self.elementPlot.clear_image()
                self.show_error("Cannot compose image", str(exc))

    def updatePickerColors(self):
        "Update the image element color pickers from the current image"
        for i, c in enumerate(self.currentImage.colors()):
            box = self.imageElementBoxes[i]
            with QtCore.QSignalBlocker(box):
                box.setColor(c)

    def showComposedImage(self, imgnum):
        "Update what composed image is shown"
        im = self.imageSettings[imgnum]
        self.currentImage = im
        self.currentElement = None
        self._clear_image_show_buttons()
        self.elementList.setCurrentRow(-1)
        self.setImageControlsEnabled(True)
        self.setElementControlsEnabled(False)

        with QtCore.QSignalBlocker(self.composeLayoutCB):
            self.composeLayoutCB.setCurrentIndex(im.layout.value)
        with QtCore.QSignalBlocker(self.composeColors):
            self.composeColors.setCurrentIndex(im.colorscheme.value)
        with QtCore.QSignalBlocker(self.composeScalebar):
            self.composeScalebar.setCurrentIndex(im.scalebar.value)
        with QtCore.QSignalBlocker(self.composeScalebarColor):
            self.composeScalebarColor.setColor(im.scalebarColor)
        with QtCore.QSignalBlocker(self.composeScalebarBgColor):
            self.composeScalebarBgColor.setColor(im.scalebarBgColor)
        with QtCore.QSignalBlocker(self.composeScalebarBg):
            self.composeScalebarBg.setChecked(im.scalebarBgAlpha is not None)
        with QtCore.QSignalBlocker(self.composeFontsize):
            self.composeFontsize.setValue(im.fontsize)
        with QtCore.QSignalBlocker(self.composeDPI):
            self.composeDPI.setValue(im.dpi)
        with QtCore.QSignalBlocker(self.composePanelLabels):
            self.composePanelLabels.setChecked(im.panelLabels)
        with QtCore.QSignalBlocker(self.composeElementLabels):
            self.composeElementLabels.setChecked(im.elementLabels)
        with QtCore.QSignalBlocker(self.composePanelLabelColor):
            self.composePanelLabelColor.setColor(im.panelLabelColor)
        with QtCore.QSignalBlocker(self.composeElementBorders):
            self.composeElementBorders.setChecked(im.elementBorders)
        with QtCore.QSignalBlocker(self.composeElementLabelsColored):
            self.composeElementLabelsColored.setChecked(im.elementLabelsColored)
        with QtCore.QSignalBlocker(self.imageHeaderBox):
            self.imageHeaderBox.setColor(im.borderColor)
            self.imageHeaderBox.border.setValue(im.borderWidth)
        self.updatePickerColors()

        # Find the corrent index for each dropdown
        for i, box in enumerate(self.imageElementBoxes):
            ix = 0
            if i in im.elements:
                es = im.elements[i]
                # Search through the combo, but we could maintain the
                # Preserve the current list order.
                for j in range(1, box.combo.count()):
                    if box.combo.itemData(j) == es.ref:
                        ix = j
                        break
            with QtCore.QSignalBlocker(box.combo):
                box.combo.setCurrentIndex(ix)
        self._update_image_show_buttons()

    def _clear_image_show_buttons(self):
        if not hasattr(self, "imageElementButtonGroup"):
            return
        self.imageElementButtonGroup.setExclusive(False)
        for button in self.imageElementButtonGroup.buttons():
            button.setChecked(False)
        self.imageElementButtonGroup.setExclusive(True)

    def refresh_element_display_names(self):
        sample = self.current_sample()
        with QtCore.QSignalBlocker(self.elementList):
            for row in range(self.elementList.count()):
                item = self.elementList.item(row)
                key = item.data(ElementListWidget.CHANNEL_KEY_ROLE)
                ref = item.data(ElementListWidget.ELEMENT_REF_ROLE)
                if sample is None:
                    project_channel = self.project_data.project_channels.get(key)
                    name = (
                        project_channel.name
                        if project_channel is not None
                        else self.project_data.channel_for_ref(ref)[1].name
                    )
                else:
                    state = self.project_data.sample_channel_state(sample.sample_id, key)
                    if state == SampleChannelState.INHERIT:
                        name = self.project_data.project_channels[key].name
                    elif state == SampleChannelState.OVERRIDE:
                        override = sample.channel_overrides[key]
                        name = override.name or sample.channels[key].name
                    else:
                        name = sample.channels[key].name
                    item.setText(self._channel_list_label(key, name))
        self.update_analysis_channels()
        self.update_analysis_elements()

        for box in self.imageElementBoxes:
            combo = box.combo
            current = combo.currentData()
            for row in range(1, combo.count()):
                ref = combo.itemData(row)
                if ref in self.project_data.element_settings:
                    combo.setItemText(row, self.project_data.element_settings[ref].name)
            if current is not None:
                ix = self._combo_index_for_data(combo, current)
                if ix >= 0:
                    combo.setCurrentIndex(ix)

    def create_dataTab(self):
        "Set up everything in the elements/images tab"

        self.loadedFileComboBox.currentIndexChanged.connect(self.loadedFileChanged)

        el = self.elementList
        el.itemUnwanted.connect(self._skip_sample_element)
        el.stateToggleRequested.connect(self._cycle_sample_element_state)

        def curr_elem(curr, prev):
            "Current element set; update the view"
            if curr is not None:
                ref = curr.data(ElementListWidget.ELEMENT_REF_ROLE)
                key = curr.data(ElementListWidget.CHANNEL_KEY_ROLE)
                self._ensure_element_settings(ref)
                sample = self.current_sample()
                self._editing_channel_context = (None if sample is None else sample.sample_id, key)
                self.editElement(ref)

        el.currentItemChanged.connect(curr_elem)

        def mark_channel_settings_edited():
            if not self.currentElement:
                return
            if self.currentImage is not None:
                slot = self.imageElementButtonGroup.checkedId()
                if slot < 0 or slot in self.currentImage.element_overrides:
                    return
            context = getattr(self, "_editing_channel_context", None)
            if context is None:
                return
            sample_id, key = context
            became_selected = False
            if sample_id is None:
                channel = self.project_data.project_channels.get(key)
                if channel is None:
                    _sample, local = self.project_data.channel_for_ref(self.currentElement.ref)
                    channel = self.project_data.add_project_channel(
                        key, local.name, self.currentElement
                    )
                    became_selected = True
                else:
                    channel.settings = self.currentElement
            else:
                became_selected = (
                    self.project_data.sample_channel_state(sample_id, key)
                    == SampleChannelState.SKIP
                )
                self.project_data.edit_channel(sample_id, key, settings=self.currentElement)
            if became_selected:
                self.refresh_current_channel_states()
                self._effective_channels_changed()

        def el_name_ch():
            "Current element name was changed"
            if not (es := self.currentElement):
                return
            es.name = self.elementName.text()
            if (
                self.currentImage is not None
                and self.imageElementButtonGroup.checkedId() in self.currentImage.element_overrides
            ):
                self.updateComposedImage()
                return
            context = getattr(self, "_editing_channel_context", None)
            if context is not None:
                sample_id, key = context
                if sample_id is None:
                    if key not in self.project_data.project_channels:
                        self.project_data.add_project_channel(key, es.name, es)
                        self._effective_channels_changed()
                    else:
                        self.project_data.rename_project_channel(key, es.name)
                    for sample in self.project_data.samples.values():
                        channel = sample.channels.get(key)
                        if channel is not None and channel.settings is not None:
                            channel.settings.name = es.name
                else:
                    was_skipped = (
                        self.project_data.sample_channel_state(sample_id, key)
                        == SampleChannelState.SKIP
                    )
                    self.project_data.edit_channel(sample_id, key, name=es.name, settings=es)
                    if was_skipped:
                        self._effective_channels_changed()
            self.refresh_element_display_names()
            if self.currentImage is not None:
                self.updateComposedImage()

        self.elementName.editingFinished.connect(el_name_ch)

        def norm_ch():
            "Normalization type updated"
            if es := self.currentElement:
                es.normalizer = Normalizers(self.elementNormalizer.currentIndex())
                mark_channel_settings_edited()
                self.updateElementNormalizer()
                self.updateElementPlot()

        for t in Normalizers:
            self.elementNormalizer.addItem(t.description)
        self.elementNormalizer.currentIndexChanged.connect(norm_ch)

        def gamma_ch():
            "Gamma value changed"
            if es := self.currentElement:
                es.gamma = self.gammaValue.value()
                mark_channel_settings_edited()
                self.updateElementPlot()

        self.gammaValue.valueChanged.connect(gamma_ch)

        def trf_range_ch(mm, isperc):
            "Normalization (transformation) range changed"
            if es := self.currentElement:
                es.setMinmax(mm, self.elementNormalizeRange[mm].value())
                mark_channel_settings_edited()
                self.elementNormalizeRange[mm].setValue(es.trfRange[mm])
                self.elementHistogramPlot.set_limits(*es.trfRange)
                self.updateElementPlot()

        self.elementNormalizeRange = [self.elementNormalizeMin, self.elementNormalizeMax]
        for mm in range(2):
            self.elementNormalizeRange[mm].valueChanged.connect(partial(trf_range_ch, mm, False))

        def mm_button(mode):
            if es := self.currentElement:
                es.setMinmaxByMode(mode)
                mark_channel_settings_edited()
                self.elementNormalizeRange[0].setValue(es.trfRange[0])
                self.elementNormalizeRange[1].setValue(es.trfRange[1])
                self.updateElementPlot()

        self.elementSDButton.clicked.connect(partial(mm_button, "sd"))
        self.elementPercButton.clicked.connect(partial(mm_button, "percent"))

        def histogram_limits_changed(minimum, maximum):
            if es := self.currentElement:
                es.trfRange[:] = [minimum, maximum]
                mark_channel_settings_edited()
                for field, value in zip(self.elementNormalizeRange, es.trfRange, strict=True):
                    with QtCore.QSignalBlocker(field):
                        field.setValue(value)
                self.updateElementPlot()

        self.elementHistogramPlot.limitsChanged.connect(histogram_limits_changed)

        def im_element_show(elementnum=-1, reset_view=False):
            "Select image-element settings or show only the composed image."
            if im := self.currentImage:
                if es := im.elements.get(elementnum):
                    self._editing_channel_context = (
                        None
                        if elementnum in im.element_overrides
                        else (im.sample_id, im.channel_keys[elementnum])
                    )
                    self.currentElement = es
                    if elementnum not in im.element_overrides:
                        with QtCore.QSignalBlocker(self.elementList):
                            item = next(
                                (
                                    self.elementList.item(row)
                                    for row in range(self.elementList.count())
                                    if self.elementList.item(row).data(
                                        ElementListWidget.ELEMENT_REF_ROLE
                                    )
                                    == es.ref
                                ),
                                None,
                            )
                            self.elementList.setCurrentItem(item)
                    else:
                        with QtCore.QSignalBlocker(self.elementList):
                            self.elementList.setCurrentRow(-1)
                    self.showCurrentElement()
                else:
                    if self.currentElement:
                        self.currentElement = None
                        self.setElementControlsEnabled(False)
                    self.updateComposedImage(reset_view=reset_view)
                    with QtCore.QSignalBlocker(self.imageElementButtonGroup):
                        self.imageHeaderBox.edit.setChecked(True)

        def im_element_ch(elementnum, index):
            "An image-element dropdown selection changed"
            if im := self.currentImage:
                box = self.imageElementBoxes[elementnum]
                if index == 0:  # Unset?
                    im.setElement(elementnum, None)
                else:
                    ref = box.combo.itemData(index)
                    self._ensure_element_settings(ref)
                    sample, channel = self.project_data.channel_for_ref(ref)
                    if sample.sample_id != im.sample_id:
                        raise ValueError("Image element belongs to a different sample")
                    im.setElement(elementnum, self.project_data.element_settings[ref], channel.key)
                self._update_image_show_buttons()
                im_element_show(-1, reset_view=True)

        def set_image_element_scope(index):
            im = self.currentImage
            slot = self.imageElementButtonGroup.checkedId()
            if im is None or slot < 0 or slot not in im.elements:
                return
            if index == 0 and slot in im.element_overrides:
                im.revertElementOverride(slot, self._sample_element_for_image_slot(im, slot))
            elif index == 1 and slot not in im.element_overrides:
                im.createElementOverride(slot)
            im_element_show(slot)

        self.imageSettingsScopeCombo.currentIndexChanged.connect(set_image_element_scope)
        self.imageChannelNameLabel.hide()
        self.imageSettingsScopeCombo.hide()
        self.showSingleElementButton.hide()

        def toggle_single_element(checked):
            if self.currentImage is None or self.currentElement is None:
                return
            if checked:
                self._display_current_element(reset_view=True)
            else:
                self.updateComposedImage(reset_view=True)

        self.showSingleElementButton.toggled.connect(toggle_single_element)

        def im_color_ch(elementnum, color):
            "An image-element color changed"
            if im := self.currentImage:
                im.setColor(elementnum, color)
                with QtCore.QSignalBlocker(self.composeColors):
                    self.composeColors.setCurrentIndex(im.colorscheme.value)
                self.updateComposedImage()

        def im_border_w_ch(val):
            "Current image border width changed"
            if im := self.currentImage:
                im.setBorderWidth(val)
                self.updateComposedImage()

        def im_border_c_ch(color):
            "Current image border color changed"
            if im := self.currentImage:
                im.setBorderColor(color)
                self.updateComposedImage()

        self.imageElementButtonGroup = QtWidgets.QButtonGroup(self)
        box = ImageHeaderBox()
        self.imageElementBox.addLayout(box)
        self.imageElementButtonGroup.addButton(box.edit, -1)
        box.border.valueChanged.connect(im_border_w_ch)
        box.colorChanged.connect(im_border_c_ch)
        self.imageHeaderBox = box
        self.imageElementBoxes = []
        image_element_grid = QtWidgets.QGridLayout()
        self.imageElementBox.addLayout(image_element_grid)
        for i in range(ImageSettings.MAX_ELEMENTS):
            box = ImageElementBox(Colorschemes(0).colors()[i])
            self.imageElementBoxes.append(box)
            image_element_grid.addLayout(box, i, 0)
            self.imageElementButtonGroup.addButton(box.edit, i)
            box.combo.currentIndexChanged.connect(partial(im_element_ch, i))
            box.colorChanged.connect(partial(im_color_ch, i))
        self.imageElementBox.addWidget(self.imageHeaderBox.edit)

        # Keep the plot pane width independent of the optional settings panel.
        plot_pane = self.splitter.indexOf(self.verticalLayoutWidget)
        self.splitter.setCollapsible(plot_pane, False)
        self.verticalLayoutWidget.setMinimumWidth(self.elementSettingsPanel.sizeHint().width())

        # Disable after all things have been created
        self.setImageControlsEnabled(False)
        self.setElementControlsEnabled(False)

        def edit_image_element():
            "Display/adjust image element or composed image"
            if self.currentImage is None:
                return
            elnum = self.imageElementButtonGroup.checkedId()
            im_element_show(elnum)

        self.imageElementButtonGroup.buttonClicked.connect(edit_image_element)

        def add_img():
            "Add new image"
            self.createImage()

        self.addImageButton.clicked.connect(add_img)

        def del_img():
            "Delete current image"
            it = self.imageList.currentItem()
            if not it:
                return
            num = it.data(ImageListWidget.IMG_NUM_ROLE)
            im = self.imageSettings[num]
            ans = QtWidgets.QMessageBox.question(
                self, "Delete image", f"Do you want to delete image '{im.name}'?"
            )
            if ans == QtWidgets.QMessageBox.StandardButton.Yes:
                self.elementPlot.clear_image()
                del self.imageSettings[num]
                self.currentImage = None
                # Delete last, if new image is selected
                self.imageList.takeItem(self.imageList.row(it))
                # No current image; disable UI components
                # self.setImageControlsEnabled(False)
                # self.elementPlot.clear()

        self.deleteImageButton.clicked.connect(del_img)

        def rename_img(item):
            "Image name modified in list"
            num = item.data(ImageListWidget.IMG_NUM_ROLE)
            if num in self.imageSettings:
                self.imageSettings[num].name = item.text()

        self.imageList.itemChanged.connect(rename_img)

        def layout_ch():
            "Image layout update"
            if im := self.currentImage:
                im.setLayout(Layouts(self.composeLayoutCB.currentIndex()))
                im_element_show(-1, reset_view=True)

        self.composeLayoutCB.currentIndexChanged.connect(layout_ch)
        for t in Layouts:
            self.composeLayoutCB.addItem(t.description)

        def colors_ch():
            "Color scheme update"
            if im := self.currentImage:
                im.setColorscheme(Colorschemes(self.composeColors.currentIndex()))
                im_element_show(-1)
                self.updatePickerColors()

        self.composeColors.currentIndexChanged.connect(colors_ch)
        for c in Colorschemes:
            self.composeColors.addItem(c.description)

        def scalebar_ch():
            "Scalebar settings update"
            if im := self.currentImage:
                self.storeImageSettings(im)
                im_element_show(-1)

        self.composeScalebarColor.colorChanged.connect(scalebar_ch)
        self.composeScalebarBgColor.colorChanged.connect(scalebar_ch)
        self.composeScalebarBg.toggled.connect(scalebar_ch)
        for s in Scalebars:
            self.composeScalebar.addItem(s.description)
        # For now we're lazy here: All settings changes trigger store+redraw
        self.composeScalebar.currentIndexChanged.connect(scalebar_ch)
        self.composeFontsize.valueChanged.connect(scalebar_ch)
        self.composeDPI.valueChanged.connect(scalebar_ch)
        self.composePanelLabels.toggled.connect(scalebar_ch)
        self.composeElementLabels.toggled.connect(scalebar_ch)
        self.composeElementBorders.toggled.connect(scalebar_ch)
        self.composeElementLabelsColored.toggled.connect(scalebar_ch)
        self.composePanelLabelColor.colorChanged.connect(scalebar_ch)

        def sel_img(curr, prev):
            "Active image changed"
            if curr is not None:
                self.showComposedImage(curr.data(ImageListWidget.IMG_NUM_ROLE))
                self.updateComposedImage(reset_view=True)

        self.imageList.currentItemChanged.connect(sel_img)

        self.imageComposer = ImageComposer()

        def mouse_over_plot(canvas_pixel):
            if not (im := self.currentImage) or canvas_pixel is None:
                QtWidgets.QToolTip.hideText()
                return
            ixy = self.imageComposer.map_coordinates(*canvas_pixel)
            if ixy is None:
                QtWidgets.QToolTip.hideText()
                return
            ix, iy = ixy
            info = f"Pos ({ix}, {iy}):\n" + "\n".join(
                [
                    f"{el.name}: {el.data[iy, ix]:.4g} {CONCENTRATION_UNITS}"
                    for el in im.elements.values()
                    if iy < el.data.shape[0] and ix < el.data.shape[1]
                ]
            )
            QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), info, self.elementPlot)

        self.elementPlot.pixelHovered.connect(mouse_over_plot)

        def save_im():
            if not (im := self.currentImage):
                return
            filters = ImageComposer.get_format_filters()
            filename = self.askFileName(
                title="Save composed image",
                filter=";;".join(filters),
                settingname="ImageDir",
                save=True,
                defaultfilename=im.name + ".png",
                directory=(
                    str(self.project_dir / "exports") if self.project_dir is not None else None
                ),
            )
            if filename is not None:
                self.imageComposer.compose(im, filename)

        self.composeSave.clicked.connect(save_im)

        def sync_settings_and_compose():
            "Update element lists and image dropdowns after channel changes."
            sample = self.current_sample()
            available_refs = set()
            if sample is not None:
                available_refs = {
                    channel.ref
                    for channel in sample.effective_channels(
                        self.project_data.project_channels
                    ).values()
                    if channel.ref in self.project_data.element_settings
                }
            ordered_refs = [
                self.elementList.item(row).data(ElementListWidget.ELEMENT_REF_ROLE)
                for row in range(self.elementList.count())
                if self.elementList.item(row).data(ElementListWidget.ELEMENT_REF_ROLE)
                in available_refs
            ]
            for i, box in enumerate(self.imageElementBoxes):
                combo = box.combo
                with QtCore.QSignalBlocker(combo):
                    selected_ref = None
                    if self.currentImage is not None and i in self.currentImage.elements:
                        selected_ref = self.currentImage.elements[i].ref
                    combo.clear()
                    combo.addItem("(none)", userData=None)
                    for ref in ordered_refs:
                        combo.addItem(
                            self.project_data.element_settings[ref].name,
                            userData=ref,
                        )
                    selected_index = self._combo_index_for_data(combo, selected_ref)
                    combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)

        el.model().dataChanged.connect(sync_settings_and_compose)
        self.channelsChanged.connect(sync_settings_and_compose)

        self.initialize_empty_project()
        self.refresh_sample_selector()

    def initialize_empty_project(self):
        """Initialize the image state for a new blank project."""
        self.imageSettings.clear()
        self.imageList.clear()

    def reset_project_defaults(self):
        """Restore the built-in defaults for a newly created project."""
        self.project_data.element_defaults = ElementSettingsDefaults()
        self.project_data.image_defaults = ImageSettings("")

    def select_and_open_files(self):
        "Add HDF5/TIFF files to the project."
        filenames = self.select_file_names("Add files to project")
        if filenames:
            with OverrideCursor():
                self.open_files(filenames)

    def select_file_names(self, title):
        "Return files selected for project or sample import."
        filters = []
        filters.append("Image files (*.h5 *.hdf *.hdf5 *.tif *.tiff)")
        filters.append("HDF5 files (*.h5 *.hdf *.hdf5)")
        filters.append("TIFF files (*.tif *.tiff)")
        filters.append("All files (*)")
        return self.askFileName(
            title=title, filter=";;".join(filters), settingname="OpenDir", multiple=True
        )

    def open_files(self, filenames, *, sample_id=None, asset_ids=None):
        "Open files, grouping a project-level TIFF batch into one sample."
        last_sample_id = None
        tiff_sample_id = sample_id

        for filename in filenames:
            try:
                source = open_source(filename)
            except Exception:
                self.show_error(
                    "The file could not be opened.",
                    f"File: {filename}\n\n{traceback.format_exc()}",
                )
                continue
            if asset_ids is not None and filename in asset_ids:
                source.source_id = asset_ids[filename]
            source_id = source.source_id

            if (
                source_id in self.project_data.sources
                and self.project_data.sources[source_id].is_open
            ):
                source.close()
                print("Warning: opened already opened file", source_id)
                asset = self.project_data.assets[source_id]
                last_sample_id = asset.sample_id
                continue

            try:
                target_sample_id = sample_id
                if target_sample_id is None and source.kind == "tiff":
                    target_sample_id = tiff_sample_id
                existing_sample_ids = set(self.project_data.samples)
                sample = self.project_data.register_source(source, sample_id=target_sample_id)
            except DuplicateChannelError as exc:
                source.close()
                self.show_error(
                    "The file could not be added because the sample already contains "
                    "an element map with the same channel key.",
                    f"File: {filename}\nSample: {exc.sample_name}\n"
                    f"Channel key: {exc.channel_key}\n\n{traceback.format_exc()}",
                )
                continue
            except Exception as exc:
                source.close()
                if source.kind == "tiff":
                    self.show_tiff_read_error(filename, exc)
                else:
                    self.show_error(
                        "The file could not be added to the sample.",
                        f"File: {filename}\n\n{traceback.format_exc()}",
                    )
                continue
            if source.kind == "tiff":
                for channel in sample.channels.values():
                    if channel.ref.source_id != source_id:
                        continue
                    if channel.key not in self.project_data.project_channels:
                        self.project_data.add_project_channel(
                            channel.key, channel.name, channel.settings
                        )
                try:
                    for channel in sample.channels.values():
                        if channel.ref is not None and channel.ref.source_id == source_id:
                            self._ensure_element_settings(channel.ref)
                except Exception as exc:
                    self.project_data.remove_asset(source_id)
                    if sample.sample_id not in existing_sample_ids and not sample.asset_ids:
                        self.project_data.samples.pop(sample.sample_id, None)
                    self.show_tiff_read_error(filename, exc)
                    continue
                if tiff_sample_id is None:
                    tiff_sample_id = sample.sample_id
            last_sample_id = sample.sample_id

        if last_sample_id is not None:
            self._effective_channels_changed()
            self.refresh_sample_selector(last_sample_id)
            if hasattr(self, "project_state_manager"):
                self.project_state_manager.project_changed()

    def rename_image_channel_key(self, asset_id, old_key, new_key):
        "Update stable image channel keys after editing a TIFF key."
        for image in self.imageSettings.values():
            for slot, element in image.elements.items():
                if element.ref.source_id == asset_id and image.channel_keys.get(slot) == old_key:
                    image.channel_keys[slot] = new_key
            for slot, (element, key, overridden) in list(image.suspended_elements.items()):
                if element.ref.source_id == asset_id and key == old_key:
                    image.suspended_elements[slot] = (element, new_key, overridden)

    def remove_project_asset(self, asset_id):
        "Intentionally remove one file and its image references."
        asset = self.project_data.assets[asset_id]
        sample_id = asset.sample_id
        refs = {
            channel.ref
            for channel in self.project_data.samples[sample_id].channels.values()
            if channel.ref is not None and channel.ref.source_id == asset_id
        }
        self.project_data.remove_asset(asset_id)
        for ref in refs:
            self._element_settings_failures.pop(ref, None)
        for image in self.imageSettings.values():
            for slot in [slot for slot, element in image.elements.items() if element.ref in refs]:
                image.setElement(slot, None)
            for slot, (element, _key, _overridden) in list(image.suspended_elements.items()):
                if element.ref in refs:
                    del image.suspended_elements[slot]
            image.sample_source_ids = tuple(
                value for value in image.sample_source_ids if value != asset_id
            )
        self._after_project_data_removed(sample_id)

    def remove_project_sample(self, sample_id):
        "Intentionally remove a sample, its files, and its images."
        refs = {
            channel.ref
            for channel in self.project_data.samples[sample_id].channels.values()
            if channel.ref is not None
        }
        self.project_data.remove_sample(sample_id)
        for ref in refs:
            self._element_settings_failures.pop(ref, None)
        self.imageSettings = {
            image_id: image
            for image_id, image in self.imageSettings.items()
            if image.sample_id != sample_id
        }
        self._after_project_data_removed(None)

    def replace_project_asset_path(self, asset_id, filename):
        "Relocate one file while retaining its project identity."
        try:
            with OverrideCursor():
                self.project_data.replace_asset_path(asset_id, filename)
        except Exception as exc:
            self.show_error("Replacing file failed", str(exc))
            return False
        for ref in list(self._element_settings_failures):
            if ref.source_id == asset_id:
                self._element_settings_failures.pop(ref)
        self._effective_channels_changed()
        self.project_data.update_external_data_root(self.project_dir)
        self.refresh_sample_selector(self.project_data.assets[asset_id].sample_id)
        if self.currentImage is not None:
            self.updateComposedImage()
        self.project_state_manager.project_changed()
        return True

    def replace_external_data_root(self, directory):
        "Relocate files together beneath a replacement data directory."
        with OverrideCursor():
            failures = self.project_data.replace_external_data_root(directory)
        if failures:
            details = "\n".join(f"{asset_id}: {error}" for asset_id, error in failures.items())
            self.show_error("Replacing data directory failed", details)
        self.project_data.update_external_data_root(self.project_dir)
        self.refresh_sample_selector(self.loadedFileComboBox.currentData())
        self.project_tab.refresh()
        if self.currentImage is not None:
            self.updateComposedImage()
        if len(failures) < len(self.project_data.assets):
            self.project_state_manager.project_changed()

    def _after_project_data_removed(self, selected_sample_id):
        self._effective_channels_changed()
        self.refresh_sample_selector(selected_sample_id)
        self.project_tab.refresh(selected_sample_id)
        if hasattr(self, "project_state_manager"):
            self.project_state_manager.project_changed()

    def close_all_files(self):
        for source_id in list(self.project_data.sources):
            self.close_source(source_id)

    def close_source(self, source_id):
        source = self.project_data.sources.get(source_id)
        if source is None or not source.is_open:
            return
        current_id = self.loadedFileComboBox.currentData()
        source.close()

        selected = current_id
        asset = self.project_data.assets.get(source_id)
        if asset is not None and current_id == asset.sample_id:
            sample = self.project_data.samples[current_id]
            if not any(self.project_data.assets[value].is_available for value in sample.asset_ids):
                selected = next(
                    (
                        item.sample_id
                        for item in self.project_data.samples.values()
                        if any(
                            self.project_data.assets[value].is_available for value in item.asset_ids
                        )
                    ),
                    None,
                )
        self.refresh_sample_selector(selected)
        self.refresh_element_display_names()
        self.project_tab.refresh(selected)
        if hasattr(self, "project_state_manager"):
            self.project_state_manager.project_changed()

    def post_setup(self, project_dir, files):
        "Called after setting up UI to start loading data etc"
        ExceptionDialog.install(self)
        if project_dir is not None:
            self.project_manager.load_project_dir(project_dir)
        else:
            self.project_state_manager.recover_unsaved_project()
        if files is not None and files:
            self.open_files(files)
        self._restore_active_tab()

    def clear_project(self):
        # Close open files first
        self.close_all_files()

        # Clear model/state
        self.project_data.clear()
        self._element_settings_failures.clear()
        self.imageSettings.clear()
        self.currentElement = None
        self.currentImage = None

        # Clear UI
        self.loadedFileComboBox.clear()
        self.analysisSampleComboBox.clear()
        self.elementList.clear()
        self.analysisElements.clear()
        self.imageList.clear()

        self.elementPlot.clear_image()
        self.elementHistogramPlot.clear_histogram()

        # Reset image-analysis / napari state if wanted
        if self.naparihelper is not None:
            self.naparihelper.set_sample(None)

        # Let any dependent widgets rebuild
        self.channelsChanged.emit()

    def refresh_project_ui(self):
        self.refresh_sample_selector()
        # Rebuild any dependent controls
        self.channelsChanged.emit()

        # Show something sensible
        if self.imageList.count() > 0:
            self.imageList.setCurrentRow(0)
        elif self.elementList.count() > 0:
            self.elementList.setCurrentRow(0)
        else:
            self.setImageControlsEnabled(False)
            self.setElementControlsEnabled(False)

    def askFileName(
        self,
        title,
        filter=None,
        settingname=None,
        save=False,
        multiple=False,
        settingdefault=None,
        directory=None,
        defaultfilename=None,
    ):
        "Show a file dialog and select one or more files"
        setting = (
            self.settings.value(settingname, settingdefault) if settingname is not None else None
        )
        if directory is None:
            directory = setting if type(setting) is str else None
        dialog = QtWidgets.QFileDialog(
            parent=self, caption=title, directory=directory, filter=filter
        )
        if defaultfilename is not None:
            dialog.selectFile(defaultfilename)
        dialog.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
        if save:
            dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptSave)

            def fix_ext(filt):
                exts = re.findall(r"\.[a-z]*", filt)
                f = dialog.selectedFiles()[0]
                if f and exts:
                    fb, fe = os.path.splitext(f)
                    if fe not in exts:
                        dialog.selectFile(fb + exts[0])

            dialog.filterSelected.connect(fix_ext)
        elif multiple:
            dialog.setFileMode(QtWidgets.QFileDialog.ExistingFiles)
        else:
            dialog.setFileMode(QtWidgets.QFileDialog.ExistingFile)
        dialog.exec()
        files = dialog.selectedFiles()
        if not dialog.result() or not files:
            return None
        if save:
            exts = re.findall(r"\.[a-z]*", dialog.selectedNameFilter())
            for i, f in enumerate(files):
                fb, fe = os.path.splitext(f)
                if fe not in exts:
                    files[i] = fb + exts[0]
        if settingname is not None:
            self.settings.setValue(settingname, os.path.dirname(files[0]))
        return files if multiple else files[0]
