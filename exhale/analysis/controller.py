"""Controller for segmentation inputs, execution, display, and export."""

from __future__ import annotations

import json
from copy import deepcopy
from time import strftime

from qtpy import QtCore, QtGui, QtWidgets
from qtpy.QtCore import Qt

from .. import appearance, icons
from ..data.projectdata import (
    SegmentationLayerSettings,
    SegmentationParameters,
    SegmentationResult,
)
from ..data.source_refs import SourceUnavailableError
from ..imaging.listwidgets import ElementListWidget
from ..project.projectmanager import EXPORT_DIRECTORY_SETTING
from ..tooltips import ANALYSIS_SETTINGS_DIALOG, apply_tooltips
from ..widgets import IconCheckDelegate
from .analysis_settings_dialog import AnalysisSettingsDialog
from .segmentationio import result_relative_path, save_xrf_sample
from .segmentationmethods import SEGMENTATION_METHODS, segmentation_method

LOAD_NAPARI_EARLY = True


def _scale_font(widget: QtWidgets.QWidget, scale: float) -> None:
    font = widget.font()
    font.setPointSizeF(font.pointSizeF() * scale)
    widget.setFont(font)


class AnalysisController(QtCore.QObject):
    """Own the Segmentation tab's state and behavior."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.naparihelper = None
        self.worker = None
        self.thread = None
        self._result_sample_id = None
        self._result_method_id = None
        self._element_signatures = {}
        self._view_fitted_on_show = False
        window.napariWidget.installEventFilter(self)
        for method in SEGMENTATION_METHODS:
            window.analysisPipelineComboBox.addItem(method.name, method.method_id)
            reason = method.unavailable_reason()
            if reason is not None:
                item = window.analysisPipelineComboBox.model().item(
                    window.analysisPipelineComboBox.count() - 1
                )
                item.setEnabled(False)
                item.setToolTip(reason)
        window.analysisElements.enable_multi_check_selection()
        window.analysisElements.setItemDelegate(IconCheckDelegate(window.analysisElements))

        dialog = AnalysisSettingsDialog(window)
        self.settings_dialog = dialog
        self.cluster_min_k = dialog.clusterMinK
        self.cluster_max_k = dialog.clusterMaxK
        self.nuclei_expansion = dialog.nucleiExpansion
        self.nuclei_min_area = dialog.nucleiMinArea
        apply_tooltips(dialog, ANALYSIS_SETTINGS_DIALOG)
        window.analysisOptions.clicked.connect(self._show_method_options)
        dialog.buttonBox.clicked.connect(dialog.hide)

    def current_method_id(self) -> str | None:
        return self.window.analysisPipelineComboBox.currentData()

    def _show_method_options(self) -> None:
        if self.current_method_id() == "stardist":
            self.settings_dialog.show()
            self.settings_dialog.raise_()

    def eventFilter(self, watched, event):
        if watched is self.window.napariWidget and event.type() in (
            QtCore.QEvent.Type.Resize,
            QtCore.QEvent.Type.Show,
        ):
            self._place_view_buttons()
        return super().eventFilter(watched, event)

    def _place_view_buttons(self) -> None:
        """Keep the view controls inside the Napari area's upper-right corner."""
        margin = 6
        spacing = 4
        right = self.window.napariWidget.width() - margin
        for button in (self.window.analysisFit, self.window.analysisSaveView):
            button.adjustSize()
            right -= button.width()
            button.move(right, margin)
            button.raise_()
            right -= spacing

    def setup(self, *, initialize_view: bool = LOAD_NAPARI_EARLY) -> None:
        """Connect the tab and optionally initialize Napari eagerly."""

        def tab_check():
            if self.window.tabWidget.currentWidget() != self.window.analysisTab:
                return
            if self.naparihelper is None:
                self.initialize_view()
            self._select_default_nuclei_channel()
            self.refresh_result_view()
            if not self._view_fitted_on_show:
                QtCore.QTimer.singleShot(0, self._fit_view_on_first_show)

        self.window.tabWidget.currentChanged.connect(tab_check)
        if initialize_view:
            self.initialize_view()

    def shutdown(self) -> None:
        """Close auxiliary UI and stop an active worker before application exit."""
        self.settings_dialog.close()
        if self.worker is not None:
            self.worker.abort()
            self.thread.wait()

    def _fit_view_on_first_show(self) -> None:
        if (
            not self._view_fitted_on_show
            and self.window.tabWidget.currentWidget() == self.window.analysisTab
            and self.naparihelper is not None
            and self.naparihelper.sample is not None
        ):
            self.fit_view()
            self._view_fitted_on_show = True

    def fit_view(self, *_unused) -> None:
        """Fit the segmentation layers to the full available canvas."""
        if self.naparihelper is not None:
            self.naparihelper.viewer.reset_view(margin=0)

    def initialize_view(self) -> None:
        """Create the embedded Napari viewer and connect analysis controls."""
        from .naparihelper import NapariHelper

        window = self.window
        self.naparihelper = NapariHelper(
            "dark" if appearance.is_dark() else "light",
            self.window.project_data.abundance_units,
        )
        window.analysisLayerList.set_helper(self.naparihelper)
        window.analysisLayerList.presentationChanged.connect(self._layer_settings_changed)
        self.naparihelper.set_info_widget(window.analysisInfo)

        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.naparihelper.qtwidget, 1)
        window.napariWidget.setLayout(layout)
        self._place_view_buttons()

        _scale_font(window.analysisStatus, 0.8)
        window.analysisSampleComboBox.currentIndexChanged.connect(self.sample_changed)
        window.analysisPipelineComboBox.currentIndexChanged.connect(self.method_changed)
        window.channelsChanged.connect(self.update_channels)
        window.channelsChanged.connect(self.update_elements)
        self.update_channels()
        self.update_elements()
        window.analysisRun.pressed.connect(self.run)
        window.analysisAbort.pressed.connect(self.abort)
        window.analysisExport.clicked.connect(self.export_results)
        window.analysisSaveView.clicked.connect(self.save_current_view)
        window.analysisFit.clicked.connect(self.fit_view)
        self.set_busy(False)

    def abort(self) -> None:
        if self.worker is not None:
            self.worker.abort()

    def current_sample(self):
        """Return the sample selected on the Segmentation tab."""
        sample_id = self.window.analysisSampleComboBox.currentData()
        return self.window.project_data.samples.get(sample_id)

    def refresh_samples(self, entries, fallback_sample_id=None) -> None:
        """Refresh the independently selected analysis sample."""
        selector = self.window.analysisSampleComboBox
        selected = selector.currentData()
        if selected not in self.window.project_data.samples:
            selected = fallback_sample_id
        with QtCore.QSignalBlocker(selector):
            selector.clear()
            for label, sample_id in entries:
                selector.addItem(label, sample_id)
            index = selector.findData(selected)
            selector.setCurrentIndex(index if index >= 0 else (0 if entries else -1))
        if self.naparihelper is not None:
            self.sample_changed()

    def sample_changed(self) -> None:
        """Update segmentation inputs for the independently selected sample."""
        sample = self.current_sample()
        sample_id = None if sample is None else sample.sample_id
        self.update_channels()
        self.update_elements()
        result = self.window.project_data.segmentation_result(sample_id, self.current_method_id())
        if result is None:
            self.clear_result_view()
        else:
            self.show_result(result)

    def method_changed(self) -> None:
        """Show the selected method's stored result for the current sample."""
        self.sample_changed()

    def refresh_result_view(self) -> None:
        """Refresh only changed element maps when the displayed result is unchanged."""
        sample = self.current_sample()
        sample_id = None if sample is None else sample.sample_id
        method_id = self.current_method_id()
        result = self.window.project_data.segmentation_result(sample_id, method_id)
        if (
            result is None
            or self.naparihelper is None
            or self._result_sample_id != sample_id
            or self._result_method_id != method_id
            or self.naparihelper.sample is not result.xrf_sample
        ):
            self.sample_changed()
            return

        settings = self._segmentation_element_settings(result)
        changed_maps = {}
        for name, ref, element_settings in zip(
            result.xrf_sample.elements, result.element_refs, settings, strict=True
        ):
            signature = self._element_transform_signature(element_settings)
            if self._element_signatures.get(ref) != signature:
                changed_maps[name] = element_settings.transformedData()
                self._element_signatures[ref] = signature
        if changed_maps:
            self.naparihelper.update_element_maps(changed_maps)

    def segmentation_parameters(self) -> SegmentationParameters:
        return SegmentationParameters(
            nuclei_expansion=self.nuclei_expansion.value(),
            nuclei_min_area=self.nuclei_min_area.value(),
            cluster_min_k=self.cluster_min_k.value(),
            cluster_max_k=self.cluster_max_k.value(),
        )

    def _set_segmentation_parameters(self, parameters: SegmentationParameters) -> None:
        controls = (
            (self.nuclei_expansion, parameters.nuclei_expansion),
            (self.nuclei_min_area, parameters.nuclei_min_area),
            (self.cluster_min_k, parameters.cluster_min_k),
            (self.cluster_max_k, parameters.cluster_max_k),
        )
        blockers = [QtCore.QSignalBlocker(control) for control, _value in controls]
        for control, value in controls:
            control.setValue(value)
        del blockers

    def clear_result_view(self) -> None:
        if self.naparihelper is None:
            return
        self.naparihelper.set_sample(None)
        self._result_sample_id = None
        self._result_method_id = None
        self._element_signatures = {}
        self.window.analysisInfo.clear()
        self.update_layer_controls()
        self.window.analysisExport.setEnabled(False)
        self.window.analysisSaveView.setEnabled(False)

    def show_result(self, result: SegmentationResult) -> None:
        window = self.window
        for selector, ref in (
            (window.analysisChNuclei, result.nuclei_ref),
            (window.analysisChTissue, result.tissue_ref),
        ):
            index = self._combo_index_for_data(selector, ref)
            if index >= 0:
                selector.setCurrentIndex(index)

        selected_refs = set(result.element_refs)
        with QtCore.QSignalBlocker(window.analysisElements):
            for row in range(window.analysisElements.count()):
                item = window.analysisElements.item(row)
                ref = item.data(ElementListWidget.ELEMENT_REF_ROLE)
                item.setCheckState(
                    Qt.CheckState.Checked if ref in selected_refs else Qt.CheckState.Unchecked
                )
        self._set_segmentation_parameters(result.parameters)
        if self.naparihelper is None:
            return
        settings = self._segmentation_element_settings(result)
        self.naparihelper.set_sample(
            result.xrf_sample,
            tuple(element_settings.transformedData() for element_settings in settings),
            tuple(self._element_layer_id(ref) for ref in result.element_refs),
        )
        self.naparihelper.apply_layer_settings(result.layer_settings)
        self._result_sample_id = result.sample_id
        self._result_method_id = result.method_id
        self._element_signatures = {
            ref: self._element_transform_signature(element_settings)
            for ref, element_settings in zip(result.element_refs, settings, strict=True)
        }
        self.update_layer_controls()
        window.analysisExport.setEnabled(True)
        window.analysisSaveView.setEnabled(True)

    @staticmethod
    def _element_layer_id(ref) -> str:
        return json.dumps(ref.to_json(), sort_keys=True, separators=(",", ":"))

    def _layer_settings_changed(self) -> None:
        """Store the current viewer presentation in its sample/method result."""
        if self.naparihelper is None:
            return
        result = self.window.project_data.segmentation_result(
            self._result_sample_id, self._result_method_id
        )
        if result is None or self.naparihelper.sample is not result.xrf_sample:
            return
        settings = self.naparihelper.layer_settings()
        if settings == result.layer_settings:
            return
        result.layer_settings = settings
        self.window.project_state_manager.project_changed()

    def _segmentation_element_settings(self, result: SegmentationResult):
        project_data = self.window.project_data
        sample = project_data.samples[result.sample_id]
        effective_by_ref = {
            channel.ref: channel
            for channel in sample.effective_channels(project_data.project_channels).values()
        }
        settings_by_ref = []
        for ref in result.element_refs:
            channel = effective_by_ref.get(ref)
            settings = None if channel is None else channel.settings
            if settings is None:
                settings = self.window.element_controller.ensure_settings(ref)
            settings_by_ref.append(settings)
        return tuple(settings_by_ref)

    @staticmethod
    def _element_transform_signature(settings):
        return settings.normalizer, settings.gamma, tuple(settings.trfRange)

    @staticmethod
    def _combo_index_for_data(combo, target) -> int:
        for index in range(combo.count()):
            if combo.itemData(index) == target:
                return index
        return -1

    def update_channels(self) -> None:
        """Update the nuclei/tissue selectors from the active sample."""
        channels = self._effective_channels()
        for selector in (self.window.analysisChNuclei, self.window.analysisChTissue):
            selected_ref = selector.currentData()
            with QtCore.QSignalBlocker(selector):
                selector.clear()
                selector.addItem("None", None)
                for channel in channels:
                    selector.addItem(channel.name, userData=channel.ref)
                index = self._combo_index_for_data(selector, selected_ref)
                if index >= 0:
                    selector.setCurrentIndex(index)
        self._select_default_nuclei_channel(channels)

    def _select_default_nuclei_channel(self, channels=None) -> None:
        selector = self.window.analysisChNuclei
        if selector.currentData() is not None:
            return
        if channels is None:
            channels = self._effective_channels()
        index = next(
            (
                row
                for row, channel in enumerate(channels, start=1)
                if channel.key == "P" or channel.key.startswith("P_")
            ),
            -1,
        )
        if index >= 0:
            selector.setCurrentIndex(index)

    def update_elements(self) -> None:
        """Update the analysis element list from the active sample."""
        element_list = self.window.analysisElements
        unchecked_refs = {
            element_list.item(row).data(ElementListWidget.ELEMENT_REF_ROLE)
            for row in range(element_list.count())
            if element_list.item(row).checkState() == Qt.CheckState.Unchecked
        }
        with QtCore.QSignalBlocker(element_list):
            element_list.clear()
            for channel in self._effective_channels():
                element_list.addChannel(
                    channel.name,
                    channel.key,
                    channel.ref,
                    Qt.CheckState.Unchecked
                    if channel.ref in unchecked_refs
                    else Qt.CheckState.Checked,
                    element_icon=False,
                )

    def _effective_channels(self):
        sample = self.current_sample()
        if sample is None:
            return []
        project_data = self.window.project_data
        return sorted(
            (
                channel
                for channel in sample.effective_channels(project_data.project_channels).values()
                if channel.ref in project_data.element_settings
            ),
            key=lambda channel: (channel.name.casefold(), channel.key.casefold()),
        )

    def element_settings(self, refs):
        effective = {channel.ref: channel for channel in self._effective_channels()}
        settings = []
        for ref in refs:
            channel = effective.get(ref)
            if channel is None:
                raise ValueError("The selected analysis channel is no longer available")
            asset = self.window.project_data.assets.get(ref.source_id)
            if asset is None or not asset.is_available:
                source = self.window.project_data.sources.get(ref.source_id)
                if source is not None:
                    raise SourceUnavailableError(source)
                raise RuntimeError(f"Channel {channel.name!r} has no data file")
            settings.append(self.window.element_controller.ensure_settings(ref))
        return settings

    def update_layer_controls(self) -> None:
        self.window.analysisLayerList.rebuild()

    def set_busy(self, busy: bool) -> None:
        window = self.window
        for widget in (
            window.analysisRun,
            window.analysisPipelineComboBox,
            window.analysisSampleComboBox,
            window.analysisChNuclei,
            window.analysisChTissue,
            window.analysisElements,
            window.analysisOptions,
            self.cluster_min_k,
            self.cluster_max_k,
            self.nuclei_expansion,
            self.nuclei_min_area,
        ):
            widget.setEnabled(not busy)
        window.analysisProgress.setRange(0, 0 if busy else 1)
        window.analysisExport.setEnabled(
            not busy and self.naparihelper is not None and self.naparihelper.sample is not None
        )
        window.analysisSaveView.setEnabled(
            not busy and self.naparihelper is not None and self.naparihelper.sample is not None
        )
        window.analysisAbort.setEnabled(busy)

    def _append_status(self, message) -> None:
        self.window.analysisStatus.appendPlainText(strftime("[%T] ") + message)
        self.window.analysisStatus.ensureCursorVisible()

    def run(self) -> None:
        """Validate the selected sample and start its background segmentation."""
        window = self.window
        if self.worker is not None:
            raise RuntimeError("Analysis worker already running")
        if not window.project_manager.require_project_directory(
            "Segmentation results are stored in the project directory."
        ):
            return

        window.analysisStatus.clear()
        self._append_status("Initializing")
        sample = self.current_sample()
        if sample is None:
            window.show_error("Select a sample first.")
            return
        analysis_sample_id = sample.sample_id
        method_id = self.current_method_id()
        if method_id is None:
            window.show_error("Select a segmentation method first.")
            return
        method = segmentation_method(method_id)
        unavailable_reason = method.unavailable_reason()
        if unavailable_reason is not None:
            window.show_error("The selected segmentation method is unavailable", unavailable_reason)
            return
        selectors = (window.analysisChNuclei, window.analysisChTissue)
        selected_refs = [selector.currentData() for selector in selectors]
        if None in selected_refs:
            window.show_error("Select channels for nuclei and tissue first.")
            return
        element_refs = [
            item.data(ElementListWidget.ELEMENT_REF_ROLE)
            for item in (
                window.analysisElements.item(row) for row in range(window.analysisElements.count())
            )
            if item.checkState() == Qt.CheckState.Checked
        ]
        parameters = self.segmentation_parameters()
        try:
            nuclei_settings, tissue_settings = self.element_settings(selected_refs)
            element_settings = self.element_settings(element_refs)
        except SourceUnavailableError as exc:
            window.show_source_unavailable(exc.source_id)
            return
        except (KeyError, RuntimeError, ValueError) as exc:
            window.show_error("Cannot start analysis", str(exc))
            return

        thread = QtCore.QThread(window)
        worker = method.create_worker(
            nuclei_settings,
            tissue_settings,
            element_settings,
            sample_name=sample.name,
            nuclei_expansion_px=parameters.nuclei_expansion,
            nuclei_min_area=parameters.nuclei_min_area,
            cluster_min_k=parameters.cluster_min_k,
            cluster_max_k=parameters.cluster_max_k,
        )
        worker.moveToThread(thread)
        worker.progress.connect(self._append_status)

        def worker_cleanup():
            self.worker.deleteLater()
            self.worker = None
            self.thread.quit()
            self.thread = None
            self.set_busy(False)

        @QtCore.Slot()
        def on_finished(xrf_sample):
            self._append_status("Saving results")
            previous = window.project_data.segmentation_result(analysis_sample_id, method_id)
            result = SegmentationResult(
                sample_id=analysis_sample_id,
                method_id=method_id,
                nuclei_ref=selected_refs[0],
                tissue_ref=selected_refs[1],
                element_refs=tuple(element_refs),
                parameters=parameters,
                xrf_sample=xrf_sample,
                layer_settings=(
                    deepcopy(previous.layer_settings)
                    if previous is not None
                    else SegmentationLayerSettings()
                ),
            )
            try:
                save_xrf_sample(
                    xrf_sample,
                    window.project_dir / result_relative_path(analysis_sample_id, method_id),
                    method_id=method_id,
                )
            except Exception as exc:
                self._append_status("Failed to save results")
                window.show_error("Saving segmentation results failed", str(exc))
                worker_cleanup()
                return
            window.project_data.set_segmentation_result(result)
            window.project_state_manager.project_changed()
            window.segmentationResultsChanged.emit()
            self._append_status("Rendering results")
            self.show_result(result)
            worker_cleanup()
            self._append_status("Done")

        @QtCore.Slot()
        def on_failed(details):
            if details == "":
                self._append_status("Interrupted")
            else:
                self._append_status("Failed")
                window.show_error("Analysis failed", details)
            worker_cleanup()

        self.set_busy(True)
        worker.finished.connect(on_finished)
        worker.failed.connect(on_failed)
        thread.started.connect(worker.run)
        thread.finished.connect(thread.deleteLater)
        self.worker = worker
        self.thread = thread
        thread.start()

    def export_results(self) -> None:
        """Export the currently displayed analysis tables to a chosen directory."""
        if self.naparihelper is None or self.naparihelper.sample is None:
            return
        window = self.window
        default_directory = window.project_manager.default_export_directory()
        if default_directory is None:
            return
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            window,
            "Choose export directory",
            default_directory,
        )
        if not directory:
            return
        window.settings.setValue(EXPORT_DIRECTORY_SETTING, directory)
        try:
            output = self.naparihelper.sample.export_results(directory)
        except Exception as exc:
            window.show_error("Export failed", str(exc))
            return
        message = QtWidgets.QMessageBox(
            QtWidgets.QMessageBox.Icon.Information,
            "Export complete",
            f"Analysis results exported to:\n{output}",
            parent=window,
        )
        open_directory = message.addButton(
            "Open directory", QtWidgets.QMessageBox.ButtonRole.ActionRole
        )
        open_directory.setIcon(icons.icon(icons.IconName.FOLDER))
        message.addButton(QtWidgets.QMessageBox.StandardButton.Ok)
        message.exec()
        if message.clickedButton() is open_directory:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(output)))

    def save_current_view(self) -> None:
        """Save the currently displayed segmentation canvas as a PNG image."""
        if self.naparihelper is None or self.naparihelper.sample is None:
            return
        window = self.window
        directory = window.project_manager.default_export_directory()
        if directory is None:
            return
        filename = window.askFileName(
            "Save current view",
            filter="PNG image (*.png)",
            settingname=EXPORT_DIRECTORY_SETTING,
            save=True,
            directory=directory,
            defaultfilename="segmentation.png",
        )
        if filename is None:
            return
        try:
            self.naparihelper.viewer.screenshot(
                path=filename,
                canvas_only=True,
                flash=True,
            )
        except Exception as exc:
            window.show_error("Saving the current view failed", str(exc))

    def clear_project(self) -> None:
        """Clear controller-owned derived display state for a new project."""
        self.window.analysisSampleComboBox.clear()
        self.window.analysisElements.clear()
        if self.naparihelper is not None:
            self.clear_result_view()
