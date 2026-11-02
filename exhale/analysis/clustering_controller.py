"""Independent element-clustering execution, persistence and Napari presentation."""

from copy import deepcopy
from time import strftime

from qtpy import QtCore, QtWidgets

from ..data.projectdata import ClusteringParameters, ClusteringResult
from ..data.source_refs import SourceUnavailableError
from ..imaging.listwidgets import ElementListWidget
from ..project.projectmanager import EXPORT_DIRECTORY_SETTING
from ..tooltips import ANALYSIS_SETTINGS_DIALOG, apply_tooltips
from ..widgets import IconCheckDelegate
from .analysis_settings_dialog import AnalysisSettingsDialog
from .analysisworker import ClusteringWorker
from .segmentationio import clustering_relative_path, save_xrf_sample


class ClusteringController(QtCore.QObject):
    """Own sample-level element clusters independently of segmentation methods."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.naparihelper = None
        self.worker = None
        self.thread = None
        self._shown_result = None
        self._generation = 0
        self._display_settings = ()
        self.dialog = AnalysisSettingsDialog(window)
        apply_tooltips(self.dialog, ANALYSIS_SETTINGS_DIALOG)
        self.dialog.setWindowTitle("Element clustering options")
        for index in range(self.dialog.gridLayout.count()):
            widget = self.dialog.gridLayout.itemAt(index).widget()
            if widget is not None:
                widget.hide()
        self.dialog.buttonBox.clicked.connect(self.dialog.hide)
        window.clusteringNapariWidget.installEventFilter(self)
        window.clusteringElements.enable_multi_check_selection()
        window.clusteringElements.setItemDelegate(IconCheckDelegate(window.clusteringElements))
        window.clusteringSampleComboBox.currentIndexChanged.connect(self.sample_changed)
        window.clusteringOptions.clicked.connect(self.dialog.show)
        window.clusteringRun.clicked.connect(self.run)
        window.clusteringAbort.clicked.connect(self.abort)
        window.clusteringExport.clicked.connect(self.export_results)
        window.clusteringSaveView.clicked.connect(self.save_current_view)
        window.clusteringFit.clicked.connect(self.fit_view)
        window.channelsChanged.connect(self.refresh_samples)
        window.tabWidget.currentChanged.connect(self._tab_changed)
        self.set_busy(False)

    def eventFilter(self, watched, event):
        if watched is self.window.clusteringNapariWidget and event.type() in (
            QtCore.QEvent.Resize,
            QtCore.QEvent.Show,
        ):
            self._place_view_buttons()
        return super().eventFilter(watched, event)

    def _place_view_buttons(self):
        right = self.window.clusteringNapariWidget.width() - 6
        for button in (self.window.clusteringFit, self.window.clusteringSaveView):
            button.adjustSize()
            right -= button.width()
            button.move(right, 6)
            button.raise_()
            right -= 4

    def _tab_changed(self):
        if self.window.tabWidget.currentWidget() is not self.window.clusteringTab:
            return
        initializing_view = self.naparihelper is None
        if initializing_view:
            from .. import appearance
            from .naparihelper import NapariHelper

            self.naparihelper = NapariHelper(
                "dark" if appearance.is_dark() else "light",
                self.window.project_data.abundance_units,
            )
            self.naparihelper.set_info_widget(self.window.clusteringInfo)
            self.window.clusteringLayerList.set_helper(self.naparihelper)
            self.window.clusteringLayerList.presentationChanged.connect(self._presentation_changed)
            layout = QtWidgets.QVBoxLayout(self.window.clusteringNapariWidget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self.naparihelper.qtwidget)
            self._place_view_buttons()
        self.show_result()
        if initializing_view:
            # Fit after the new canvas and restored splitters have their final sizes.
            QtCore.QTimer.singleShot(0, self.fit_view)

    def refresh_samples(self):
        """Preserve the selected sample while rebuilding available inputs."""
        selector = self.window.clusteringSampleComboBox
        selected = selector.currentData()
        with QtCore.QSignalBlocker(selector):
            selector.clear()
            for sample in self.window.project_data.samples.values():
                selector.addItem(sample.name, sample.sample_id)
            index = selector.findData(selected)
            selector.setCurrentIndex(index if index >= 0 else (0 if selector.count() else -1))
        self.sample_changed()

    def sample_changed(self):
        """Restore this sample's clustering inputs and completed result."""
        sample = self.window.project_data.samples.get(
            self.window.clusteringSampleComboBox.currentData()
        )
        result = (
            None
            if sample is None
            else self.window.project_data.clustering_results.get(sample.sample_id)
        )
        items = self.window.clusteringElements
        previous = {
            items.item(i).data(ElementListWidget.ELEMENT_REF_ROLE): items.item(i).checkState()
            for i in range(items.count())
        }
        with QtCore.QSignalBlocker(items):
            items.clear()
            channels = (
                []
                if sample is None
                else sample.effective_channels(self.window.project_data.project_channels).values()
            )
            for channel in sorted(
                channels, key=lambda item: (item.name.casefold(), item.key.casefold())
            ):
                checked = (
                    channel.ref in result.element_refs
                    if result is not None
                    else previous.get(channel.ref, QtCore.Qt.Checked) == QtCore.Qt.Checked
                )
                items.addChannel(
                    channel.name,
                    channel.key,
                    channel.ref,
                    QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked,
                    element_icon=False,
                )
        if result is not None:
            self.dialog.clusterMinK.setValue(result.parameters.min_k)
            self.dialog.clusterMaxK.setValue(result.parameters.max_k)
        self.show_result()

    def show_result(self):
        """Show only element maps and clusters, preserving pooled layer objects."""
        result = self.window.project_data.clustering_results.get(
            self.window.clusteringSampleComboBox.currentData()
        )
        if self.naparihelper is None:
            return
        self.naparihelper.abundance_units = self.window.project_data.abundance_units
        if result is not self._shown_result:
            self._shown_result = result
            if result is None:
                self.naparihelper.set_sample(None)
                self._display_settings = ()
            else:
                display_settings = []
                for ref in result.element_refs:
                    try:
                        display_settings.append(self.window.element_controller.ensure_settings(ref))
                    except (SourceUnavailableError, KeyError, ValueError):
                        display_settings.append(None)
                self._display_settings = tuple(display_settings)
                self.naparihelper.set_sample(
                    result.xrf_sample,
                    tuple(
                        channel.raw if settings is None else settings.transformedData()
                        for channel, settings in zip(
                            result.xrf_sample.elements.values(), self._display_settings, strict=True
                        )
                    ),
                    tuple(str(ref) for ref in result.element_refs),
                )
                self.naparihelper.apply_layer_settings(result.layer_settings)
            self.window.clusteringLayerList.rebuild()
        elif result is not None:
            self.naparihelper.update_element_maps(
                {
                    name: settings.transformedData()
                    for name, settings in zip(
                        result.xrf_sample.elements, self._display_settings, strict=True
                    )
                    if settings is not None
                }
            )
        self.window.clusteringExport.setEnabled(result is not None and self.worker is None)
        self.window.clusteringSaveView.setEnabled(result is not None)

    def _presentation_changed(self):
        if self._shown_result is None:
            return
        state = self.naparihelper.layer_settings()
        if state != self._shown_result.layer_settings:
            self._shown_result.layer_settings = state
            self.window.project_state_manager.project_changed()

    def set_busy(self, busy):
        for widget in (
            self.window.clusteringRun,
            self.window.clusteringSampleComboBox,
            self.window.clusteringElements,
            self.window.clusteringOptions,
            self.dialog.clusterMinK,
            self.dialog.clusterMaxK,
        ):
            widget.setEnabled(not busy)
        self.window.clusteringAbort.setEnabled(busy)
        self.window.clusteringProgress.setRange(0, 0 if busy else 1)
        self.window.clusteringExport.setEnabled(not busy and self._shown_result is not None)
        self.window.clusteringSaveView.setEnabled(not busy and self._shown_result is not None)

    def _append_status(self, text):
        self.window.clusteringStatus.appendPlainText(strftime("[%T] ") + text)

    def run(self):
        """Run only intensity partitioning and element-region extraction."""
        if self.worker is not None or self.window.analysis_controller.worker is not None:
            self.window.show_error("Another analysis is running.")
            return
        if not self.window.project_manager.require_project_directory(
            "Element clusters are stored in the project directory."
        ):
            return
        sample_id = self.window.clusteringSampleComboBox.currentData()
        sample = self.window.project_data.samples.get(sample_id)
        if sample is None:
            self.window.show_error("Select a sample first.")
            return
        refs = tuple(
            item.data(ElementListWidget.ELEMENT_REF_ROLE)
            for item in (
                self.window.clusteringElements.item(i)
                for i in range(self.window.clusteringElements.count())
            )
            if item.checkState() == QtCore.Qt.Checked
        )
        if not refs:
            self.window.show_error("Select at least one element to cluster.")
            return
        try:
            settings = [self.window.element_controller.ensure_settings(ref) for ref in refs]
            for setting in settings:
                _ = setting.data
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            self.window.show_error("Cannot start element clustering", str(error))
            return
        parameters = ClusteringParameters(
            self.dialog.clusterMinK.value(), self.dialog.clusterMaxK.value()
        )
        generation = self._generation
        project_dir = self.window.project_dir
        thread = QtCore.QThread(self.window)
        worker = ClusteringWorker(
            None, None, settings, sample.name, min_k=parameters.min_k, max_k=parameters.max_k
        )
        worker.moveToThread(thread)
        worker.progress.connect(self._append_status)

        def cleanup():
            self.worker = None
            self.thread = None
            self.set_busy(False)

        def finished(xrf_sample):
            try:
                if (
                    generation != self._generation
                    or sample_id not in self.window.project_data.samples
                ):
                    return
                available_refs = {
                    channel.ref
                    for channel in self.window.project_data.samples[sample_id].channels.values()
                }
                if not set(refs) <= available_refs:
                    return
                previous = self.window.project_data.clustering_results.get(sample_id)
                result = ClusteringResult(sample_id, refs, parameters, xrf_sample)
                if previous is not None:
                    result.layer_settings = deepcopy(previous.layer_settings)
                save_xrf_sample(
                    xrf_sample,
                    project_dir / clustering_relative_path(sample_id),
                    method_id="element-clusters",
                )
                self.window.project_data.clustering_results[sample_id] = result
                self.window.project_state_manager.project_changed()
                self.window.clusteringResultsChanged.emit()
                self._append_status("Done")
            except Exception as error:
                self.window.show_error("Element clustering failed", str(error))
            finally:
                cleanup()
                self.show_result()

        def failed(details):
            self._append_status("Interrupted" if not details else "Failed")
            cleanup()
            if details and generation == self._generation:
                self.window.show_error("Element clustering failed", details)

        worker.finished.connect(finished)
        worker.failed.connect(failed)
        worker.finished.connect(thread.quit, QtCore.Qt.DirectConnection)
        worker.failed.connect(thread.quit, QtCore.Qt.DirectConnection)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.started.connect(worker.run)
        self.worker, self.thread = worker, thread
        self.window.clusteringStatus.clear()
        self.set_busy(True)
        thread.start()

    def abort(self):
        if self.worker is not None:
            self.worker.abort()

    def shutdown(self):
        """Request cancellation and wait before destroying worker-owned objects."""
        self.dialog.close()
        if self.worker is not None:
            self.worker.abort()
            self.thread.wait()

    def clear_project(self):
        """Invalidate running work and clear the derived viewer state."""
        self._generation += 1
        self.abort()
        self._shown_result = None
        self._display_settings = ()
        if self.naparihelper is not None:
            self.naparihelper.set_sample(None)
            self.window.clusteringLayerList.rebuild()
        self.refresh_samples()

    def fit_view(self):
        if self.naparihelper is not None:
            self.naparihelper.viewer.reset_view(margin=0)

    def save_current_view(self):
        if self._shown_result is None:
            return
        directory = self.window.project_manager.default_export_directory()
        if directory is None:
            return
        filename = self.window.askFileName(
            "Save current view",
            filter="PNG image (*.png)",
            settingname=EXPORT_DIRECTORY_SETTING,
            save=True,
            directory=directory,
            defaultfilename="element-clusters.png",
        )
        if filename is not None:
            try:
                self.naparihelper.viewer.screenshot(path=filename, canvas_only=True, flash=True)
            except Exception as error:
                self.window.show_error("Saving the current view failed", str(error))

    def export_results(self):
        if self._shown_result is None:
            return
        directory = self.window.project_manager.default_export_directory()
        if directory is None:
            return
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self.window, "Choose export directory", directory
        )
        if directory:
            try:
                self._shown_result.xrf_sample.export_results(directory)
            except Exception as error:
                self.window.show_error("Export failed", str(error))
