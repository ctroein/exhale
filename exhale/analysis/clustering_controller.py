"""Method-based clustering queues and a two-overlay, single-element viewer."""

from copy import copy, deepcopy
from dataclasses import replace
from time import strftime

from qtpy import QtCore, QtWidgets

from .. import icons
from ..data.clustering import DEFAULT_CLUSTERING_METHOD, clustering_job
from ..data.projectdata import SegmentationLayerSettings
from ..data.source_refs import SourceUnavailableError
from ..project.projectmanager import EXPORT_DIRECTORY_SETTING
from ..tooltips import CLUSTERING_BLENDING
from .clustering_abundance import abundance_statistics
from .clusteringbatch import ClusteringBatchWorker
from .clusteringmethods import CLUSTERING_METHODS, clustering_method
from .layerwidgets import LayerColorEditor


class ClusteringController(QtCore.QObject):
    """Publish independent sample/method results while allowing completed-data inspection."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.naparihelper = None
        self.worker = self.thread = None
        self._shown_result = None
        self._view_key = None
        self._generation = 0
        self._preview_settings = {}
        self._display_settings = None
        self._pending = None
        self._live = None
        self._live_failed = None
        self._cutoff_timer = QtCore.QTimer(self)
        self._cutoff_timer.setSingleShot(True)
        self._cutoff_timer.setInterval(250)
        self._cutoff_timer.timeout.connect(self._start_pending)
        self._dialogs = {}
        self._configuring_options = False
        for method in CLUSTERING_METHODS:
            window.clusteringMethodCombo.addItem(method.name, method.method_id)
            window.clusteringAnalysisMethod.addItem(method.name, method.method_id)
            if method.method_id == DEFAULT_CLUSTERING_METHOD:
                dialog = method.create_options(window)
                dialog.buttonBox.rejected.connect(dialog.hide)
                dialog.clusterMinK.valueChanged.connect(self._options_changed)
                dialog.clusterMaxK.valueChanged.connect(self._options_changed)
                self._dialogs[method.method_id] = dialog
        self.dialog = self._dialogs.get(self.run_method_id())
        self.color_editor = LayerColorEditor(parent=window.clusteringColorHost)
        window.clusteringColorLayout.addWidget(self.color_editor.color_button)
        self.color_editor.changed.connect(self._presentation_changed)
        self.map_color_editor = LayerColorEditor(parent=window.clusteringMapColorHost)
        window.clusteringMapColorLayout.addWidget(self.map_color_editor.color_button)
        self.map_color_editor.changed.connect(self._presentation_changed)
        window.clusteringNapariWidget.installEventFilter(self)
        window.clusteringSampleComboBox.currentIndexChanged.connect(self.sample_changed)
        window.clusteringMethodCombo.currentIndexChanged.connect(self.method_changed)
        window.clusteringAnalysisMethod.currentIndexChanged.connect(self._analysis_method_changed)
        window.clusteringElementCombo.currentIndexChanged.connect(self._selection_changed)
        window.clusteringAuto.toggled.connect(self._queue_cutoff)
        window.clusteringCutoff.valueChanged.connect(self._queue_cutoff)
        window.clusteringMapVisible.toggled.connect(self._visibility_changed)
        window.clusteringClustersVisible.toggled.connect(self._visibility_changed)
        window.clusteringOpacity.valueChanged.connect(self._opacity_changed)
        window.clusteringBlending.clicked.connect(self._blending_changed)
        window.clusteringOptions.clicked.connect(self.show_options)
        window.clusteringRemove.clicked.connect(self.remove_result)
        window.clusteringRun.clicked.connect(self.run)
        window.clusteringBatch.clicked.connect(self.run_batch)
        window.clusteringAbort.clicked.connect(self.abort)
        window.clusteringExport.clicked.connect(self.export_results)
        window.clusteringSaveView.clicked.connect(self.save_current_view)
        window.clusteringFit.clicked.connect(self.fit_view)
        window.channelsChanged.connect(self.refresh_samples)
        window.tabWidget.currentChanged.connect(self._tab_changed)
        self.set_busy(False)

    def _analysis_method_changed(self):
        project = self.window.project_data
        project.analysis_clustering_method = self.window.clusteringAnalysisMethod.currentData()
        self.window.project_state_manager.project_changed()
        self.window.clusteringResultsChanged.emit()
        self._selection_changed()

    def _configure_options(self):
        """Load editable project configuration, independently of the result being viewed."""
        self._configuring_options = True
        try:
            method_id = self.run_method_id()
            if method_id == DEFAULT_CLUSTERING_METHOD:
                clustering_method(method_id).restore_options(
                    self.dialog, self.window.project_data.clustering_settings.intensity
                )
        finally:
            self._configuring_options = False

    def _options_changed(self):
        if self._configuring_options:
            return
        if self.run_method_id() == DEFAULT_CLUSTERING_METHOD:
            try:
                parameters = clustering_method(self.run_method_id()).parameters(self.dialog)
            except ValueError:
                return
            settings = self.window.project_data.clustering_settings
            if settings.intensity != parameters:
                settings.intensity = parameters
                self._clear_method_results(self.run_method_id())
                self.window.clusteringResultsChanged.emit()
        self.window.project_state_manager.project_changed()
        self.show_result()

    def show_options(self):
        if self.dialog is not None:
            self._configure_options()
            self.dialog.show()
            self.dialog.raise_()
            return
        method = self.run_method_id()
        project = self.window.project_data
        settings = project.clustering_settings
        draft = copy(project)
        draft.clustering_settings = deepcopy(settings)
        draft.clustering_settings.cutoffs = {
            sample_id: settings.parameters(sample_id, method).method_options["cutoff_scales"]
            for sample_id in project.samples
        }
        original = deepcopy(draft.clustering_settings.cutoffs)
        draft.clustering_settings.abundance["min_cluster_size"] = settings.minimum_sizes.get(
            method, settings.abundance["min_cluster_size"]
        )
        dialog = clustering_method(method).create_options(self.window)
        for control in (dialog.linkRadius, dialog.cutoffScale, dialog.prominence):
            dialog.settingsLayout.setRowVisible(control, False)
        dialog.buttonBox.setStandardButtons(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        dialog.buttonBox.button(QtWidgets.QDialogButtonBox.Ok).setText("Apply")
        dialog.buttonBox.accepted.connect(dialog.accept)
        dialog.buttonBox.rejected.connect(dialog.reject)
        dialog.setWindowTitle(f"{clustering_method(method).name} options")
        dialog.set_context(draft, self._sample())
        accepted = dialog.exec() == QtWidgets.QDialog.Accepted
        dialog.stop_estimates()
        dialog.deleteLater()
        if accepted:
            edited = draft.clustering_settings.cutoffs
            for sample_id in original.keys() | edited.keys():
                before, after = original.get(sample_id, {}), edited.get(sample_id, {})
                for key in before.keys() | after.keys():
                    if before.get(key) != after.get(key):
                        settings.method_cutoffs.setdefault(method, {}).setdefault(sample_id, {})[
                            key
                        ] = after.get(key)
            minimum = draft.clustering_settings.abundance["min_cluster_size"]
            if minimum != settings.parameters(None, method).method_options["min_cluster_size"]:
                settings.minimum_sizes[method] = minimum
            self._options_changed()
            self._selection_changed()

    def _method_results(self, method=None):
        method = method or self.current_method_id()
        return [
            results[method]
            for results in self.window.project_data.clustering_results.values()
            if method in results
        ]

    def _clear_method_results(self, method=None):
        results = self.window.project_data.clustering_results
        for result in self._method_results(method):
            self._preview_settings[(result.sample_id, result.method_id)] = deepcopy(
                result.layer_settings
            )
            results[result.sample_id].pop(result.method_id)
            if not results[result.sample_id]:
                del results[result.sample_id]

    def remove_result(self):
        count = len(self._method_results())
        if not count or self.worker is not None:
            return
        method = self.window.clusteringAnalysisMethod.currentText()
        if (
            QtWidgets.QMessageBox.question(
                self.window,
                "Clear clustering results",
                f"Clear {method} results from all {count} samples with results?",
            )
            != QtWidgets.QMessageBox.Yes
        ):
            return
        self._clear_method_results()
        self.window.project_state_manager.project_changed()
        self.window.clusteringResultsChanged.emit()
        self.show_result()

    def current_method_id(self):
        return self.window.clusteringAnalysisMethod.currentData()

    def run_method_id(self):
        return self.window.clusteringMethodCombo.currentData()

    def _sample(self):
        return self.window.project_data.samples.get(
            self.window.clusteringSampleComboBox.currentData()
        )

    def _result(self):
        return self.window.project_data.clustering_result(
            self.window.clusteringSampleComboBox.currentData(), self.current_method_id()
        )

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
        if self.naparihelper is None:
            from .. import appearance
            from .naparihelper import NapariHelper

            self.naparihelper = NapariHelper(
                "dark" if appearance.is_dark() else "light",
                self.window.project_data.abundance_units,
            )
            self.naparihelper.set_info_widget(self.window.clusteringInfo)
            layout = QtWidgets.QVBoxLayout(self.window.clusteringNapariWidget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self.naparihelper.qtwidget)
            self._place_view_buttons()
        self.show_result()

    def refresh_samples(self):
        """Restore project method and retain independent sample/element selections."""
        selector = self.window.clusteringSampleComboBox
        selected = selector.currentData()
        method = self.window.clusteringMethodCombo
        with QtCore.QSignalBlocker(method):
            index = method.findData(self.window.project_data.clustering_method)
            method.setCurrentIndex(max(0, index))
        self.dialog = self._dialogs.get(self.run_method_id())
        analysis = self.window.clusteringAnalysisMethod
        with QtCore.QSignalBlocker(analysis):
            analysis.setCurrentIndex(
                max(0, analysis.findData(self.window.project_data.analysis_clustering_method))
            )
        with QtCore.QSignalBlocker(selector):
            selector.clear()
            for sample in self.window.project_data.samples.values():
                selector.addItem(sample.name, sample.sample_id)
            selector.setCurrentIndex(
                max(0, selector.findData(selected)) if selector.count() else -1
            )
        self.sample_changed()

    def method_changed(self):
        self.window.project_data.clustering_method = self.run_method_id()
        if self.dialog is not None:
            self.dialog.hide()
        self.dialog = self._dialogs.get(self.run_method_id())
        self._configure_options()
        self._update_cutoff()
        self.window.project_state_manager.project_changed()

    def sample_changed(self):
        """Select enabled elements and restore this sample/method's saved options."""
        sample = self._sample()
        combo = self.window.clusteringElementCombo
        previous = combo.currentData()
        channels = (
            []
            if sample is None
            else sorted(
                sample.effective_channels(self.window.project_data.project_channels).values(),
                key=lambda channel: (channel.name.casefold(), channel.key.casefold()),
            )
        )
        with QtCore.QSignalBlocker(combo):
            combo.clear()
            for channel in channels:
                combo.addItem(channel.name, channel.ref)
            combo.setCurrentIndex(max(0, combo.findData(previous)) if channels else -1)
        self._configure_options()
        self._selection_changed()

    def _selection_changed(self, *_unused):
        self._update_cutoff(reset=True)
        self.show_result()

    def show_result(self, *_unused):
        """Reuse two pooled overlays; element changes leave camera position unchanged."""
        self.window.clusteringRemove.setEnabled(
            self.worker is None and bool(self._method_results())
        )
        self._update_cutoff()
        if (
            self.naparihelper is None
            or self.window.tabWidget.currentWidget() is not self.window.clusteringTab
        ):
            return
        sample = self._sample()
        result = self._result()
        ref = self.window.clusteringElementCombo.currentData()
        helper = self.naparihelper
        helper.abundance_units = self.window.project_data.abundance_units
        if sample is None or ref is None:
            helper.set_sample(None)
            self._shown_result = result
            self.color_editor.bind(helper, None)
            self.map_color_editor.bind(helper, None)
            self._sync_display_controls()
            return
        channel = None
        if result is not None and ref in result.element_refs:
            channel = tuple(result.xrf_sample.elements.values())[result.element_refs.index(ref)]
        try:
            settings = self.window.element_controller.ensure_settings(ref)
            data = settings.transformedData()
        except (SourceUnavailableError, KeyError, RuntimeError, ValueError):
            data = None if channel is None else channel.raw
        if data is None:
            helper.set_sample(None)
            self.window.clusteringInfo.setPlainText("The selected element map is unavailable.")
        else:
            from ..xrf_refcopy.xrf_element_channel import ElementChannel
            from ..xrf_refcopy.xrf_sample_class import XRFSample

            display = XRFSample(sample.name) if result is None else copy(result.xrf_sample)
            name = self.window.clusteringElementCombo.currentText()
            display.elements = {name: channel or ElementChannel(name, data)}
            display.nuclei = display.tissue = None
            key = (sample.sample_id, self.current_method_id(), ref)
            if key != self._view_key:
                self.color_editor.bind(helper, None)
                self.map_color_editor.bind(helper, None)
            helper.set_sample(
                display,
                (data,),
                (str(ref),),
                fit=self._view_key is None or self._view_key[0] != sample.sample_id,
            )
            for layer in helper.user_layers():
                layer.visible = True
                if layer.metadata.get("exhale_role") == "element_clusters":
                    layer.opacity = 0.6
                    layer.editable = False
                    helper.set_label_presentation(layer, helper.LABEL_CATEGORICAL, (1, 0, 0, 1), 0)
                elif layer.metadata.get("exhale_role") == "element_map":
                    helper.set_image_color(layer, (0, 1, 0, 1))
            state = (
                result.layer_settings if result is not None else self._preview_settings.get(key[:2])
            )
            if self._display_settings is None:
                self._display_settings = SegmentationLayerSettings()
                if state is not None:
                    for layer in helper.user_layers():
                        saved = state.layers.get(
                            layer.metadata["exhale_role"],
                            state.layers.get(helper.layer_identity(layer)),
                        )
                        if saved is not None:
                            self._display_settings.layers[layer.metadata["exhale_role"]] = saved
            helper.apply_layer_settings(
                SegmentationLayerSettings(
                    layers={
                        helper.layer_identity(layer): self._display_settings.layers[role]
                        for layer in helper.user_layers()
                        if (role := layer.metadata.get("exhale_role"))
                        in self._display_settings.layers
                    }
                )
            )
            self._view_key = key
            count = 0 if channel is None or channel.cluster_df is None else len(channel.cluster_df)
            changed = (
                result is not None
                and result.parameters
                != self.window.project_data.clustering_settings.parameters(
                    sample.sample_id, self.current_method_id()
                )
            )
            self.window.clusteringInfo.setPlainText(
                "Not clustered"
                if channel is None
                else f"Clusters: {count}"
                + ("\nSettings changed; rerun to update." if changed else "")
            )
        self._shown_result = result
        cluster_layer = next(
            (
                layer
                for layer in helper.user_layers()
                if layer.metadata.get("exhale_role") == "element_clusters"
            ),
            None,
        )
        self.color_editor.bind(helper, cluster_layer)
        self.map_color_editor.bind(helper, self._map_layer())
        self._sync_display_controls()

    def _map_layer(self):
        return (
            next(
                (
                    layer
                    for layer in self.naparihelper.user_layers()
                    if layer.metadata.get("exhale_role") == "element_map"
                ),
                None,
            )
            if self.naparihelper
            else None
        )

    def _sync_display_controls(self):
        window = self.window
        for checkbox, layer in (
            (window.clusteringMapVisible, self._map_layer()),
            (window.clusteringClustersVisible, self.color_editor.layer),
        ):
            with QtCore.QSignalBlocker(checkbox):
                checkbox.setChecked(layer is not None and self.naparihelper.layer_visible(layer))
            checkbox.setEnabled(layer is not None)
        with QtCore.QSignalBlocker(window.clusteringOpacity):
            layer = self.color_editor.layer
            window.clusteringOpacity.setValue(60 if layer is None else round(layer.opacity * 100))
        window.clusteringOpacity.setEnabled(layer is not None)
        additive = (
            layer is not None
            and self.naparihelper.layer_blending(layer) == self.naparihelper.BLENDING_ADD
        )
        window.clusteringBlending.setEnabled(layer is not None)
        window.clusteringBlending.setChecked(additive)
        window.clusteringBlending.set_icon_name(
            icons.IconName.LAYERS_ADD if additive else icons.IconName.LAYERS
        )
        window.clusteringBlending.setToolTip(CLUSTERING_BLENDING["add" if additive else "normal"])
        window.clusteringExport.setEnabled(self._result() is not None)
        window.clusteringSaveView.setEnabled(self._map_layer() is not None or layer is not None)

    def _visibility_changed(self):
        if self.naparihelper is None:
            return
        for checkbox, layer in (
            (self.window.clusteringMapVisible, self._map_layer()),
            (self.window.clusteringClustersVisible, self.color_editor.layer),
        ):
            if layer is not None:
                self.naparihelper.set_layer_visible(layer, checkbox.isChecked())
        self._presentation_changed()

    def _blending_changed(self):
        """Toggle cluster compositing without changing the map presentation."""
        layer = self.color_editor.layer
        if layer is None:
            return
        helper = self.naparihelper
        mode = (
            helper.BLENDING_NORMAL
            if helper.layer_blending(layer) == helper.BLENDING_ADD
            else helper.BLENDING_ADD
        )
        helper.set_layer_blending(layer, mode)
        helper.set_layer_visible(layer, True)
        self._presentation_changed()

    def _opacity_changed(self, percent):
        if self.color_editor.layer is not None:
            self.naparihelper.set_layer_opacity(self.color_editor.layer, percent)
            self._presentation_changed()

    def _presentation_changed(self):
        if self.naparihelper is None or self._view_key is None:
            return
        captured = self.naparihelper.layer_settings()
        state = SegmentationLayerSettings(
            layers={
                layer.metadata["exhale_role"]: captured.layers[
                    self.naparihelper.layer_identity(layer)
                ]
                for layer in self.naparihelper.user_layers()
            }
        )
        if self._display_settings is None:
            self._display_settings = SegmentationLayerSettings()
        self._display_settings.layers.update(state.layers)
        state = self._display_settings
        result = self._result()
        owner = (
            result.layer_settings
            if result is not None
            else self._preview_settings.setdefault(self._view_key[:2], SegmentationLayerSettings())
        )
        owner.layers = dict(state.layers)
        owner.order = state.order
        self._sync_display_controls()
        if result is not None:
            self.window.project_state_manager.project_changed()

    def set_busy(self, busy):
        if self.dialog is not None:
            self.dialog.setEnabled(not busy)
        self._update_cutoff()
        for widget in (
            self.window.clusteringRun,
            self.window.clusteringBatch,
            self.window.clusteringMethodCombo,
            self.window.clusteringOptions,
        ):
            widget.setEnabled(not busy)
        self.window.clusteringAbort.setEnabled(busy)
        self.window.clusteringRemove.setEnabled(not busy and bool(self._method_results()))
        bar = self.window.clusteringProgress
        bar.setTextVisible(True)
        if busy:
            bar.setRange(0, 1)
            bar.setValue(0)
            bar.setFormat("Starting…")
        elif bar.value() < 0:
            bar.setValue(0)
            bar.setFormat("Ready")

    def _append_status(self, text):
        self.window.clusteringStatus.appendPlainText(strftime("[%T] ") + text)

    def run(self):
        """Cluster all enabled maps of the selected sample."""
        sample = self._sample()
        if sample is None:
            self.window.show_error("Select a sample first.")
            return
        job = clustering_job(self.window.project_data, sample)
        if not job.refs:
            self.window.show_error("Enable at least one sample element first.")
            return
        self.start((job,))

    def _map_selection(self):
        return (
            self.current_method_id(),
            self.window.clusteringSampleComboBox.currentData(),
            self.window.clusteringElementCombo.currentData(),
        )

    def _update_cutoff(self, *, reset=False):
        window = self.window
        method, sample_id, ref = self._map_selection()
        abundance = method != DEFAULT_CLUSTERING_METHOD
        sample = self._sample()
        valid = abundance and sample is not None and ref is not None
        for widget in (
            window.clusteringCutoffLabel,
            window.clusteringAuto,
            window.clusteringCutoff,
            window.clusteringCutoffStatus,
        ):
            widget.setVisible(abundance)
        intensity = self.run_method_id() == DEFAULT_CLUSTERING_METHOD
        window.clusteringRun.setVisible(intensity)
        can_edit = valid and (self.worker is None or self._live is not None)
        window.clusteringAuto.setEnabled(can_edit)
        if not valid:
            window.clusteringCutoff.setEnabled(False)
            window.clusteringCutoffStatus.clear()
            return
        selection = method, sample_id, ref
        settings = window.project_data.clustering_settings
        parameters = settings.parameters(sample_id, method)
        options = parameters.method_options
        key = next(channel.key for channel in sample.channels.values() if channel.ref == ref)
        result = self._result()
        status = "No result"
        multiple = options.get("cutoff_scales", {}).get(key)
        automatic = multiple is None and key not in options.get("thresholds", {})
        shown = -0.01 if multiple is None else multiple
        queued = next(
            (
                entry
                for entry in (self._pending, self._live)
                if entry is not None and entry[0] == selection
            ),
            None,
        )
        if result is not None and ref in result.element_refs:
            status = "" if self._map_matches(result, parameters, ref, key) else "Out of date"
            if reset and multiple is None:
                channel = tuple(result.xrf_sample.elements.values())[result.element_refs.index(ref)]
                thresholds = channel.intensity_thresholds
                stats = (
                    abundance_statistics(channel.raw)
                    if thresholds is not None and len(thresholds)
                    else None
                )
                if stats is not None and stats[1] > 0:
                    shown = max(0, (thresholds[0] - stats[0]) / stats[1])
        if not automatic and multiple is None and status != "No result":
            status = "Saved with an absolute cutoff" + (f" · {status}" if status else "")
        if queued is not None:
            status = "Updating…"
            automatic = queued[1] is None
            if not automatic:
                shown = queued[1]
        elif self._live_failed == selection:
            status = "Update failed"
        if reset:
            with (
                QtCore.QSignalBlocker(window.clusteringAuto),
                QtCore.QSignalBlocker(window.clusteringCutoff),
            ):
                window.clusteringAuto.setChecked(automatic)
                window.clusteringCutoff.setValue(shown)
        window.clusteringCutoff.setEnabled(can_edit and not window.clusteringAuto.isChecked())
        window.clusteringCutoffStatus.setText(status)

    def _map_matches(self, result, parameters, ref, key):
        if result is None or ref not in result.element_refs:
            return False
        stored = result.parameters.method_options
        return stored.get("map_defaults", {}).get(
            key, self._global_options(result.parameters)
        ) == self._global_options(parameters) and all(
            stored.get(field, {}).get(key) == parameters.method_options.get(field, {}).get(key)
            for field in ("thresholds", "cutoff_scales")
        )

    @staticmethod
    def _global_options(parameters):
        return {
            key: value
            for key, value in parameters.method_options.items()
            if key not in ("thresholds", "cutoff_scales", "map_defaults")
        }

    def _queue_cutoff(self, *_unused):
        selection = self._map_selection()
        if selection[2] is None:
            return
        window = self.window
        value = (
            None if window.clusteringAuto.isChecked() else max(0, window.clusteringCutoff.value())
        )
        self._pending = (selection, value)
        self._live_failed = None
        self._cutoff_timer.start()
        self._update_cutoff()

    def _start_pending(self):
        if self.worker is not None or self._pending is None:
            return
        request, self._pending = self._pending, None
        (method, sample_id, ref), value = request
        project = self.window.project_data
        sample = project.samples.get(sample_id)
        if sample is None:
            self._update_cutoff(reset=True)
            return
        job = clustering_job(project, sample)
        if ref not in job.refs:
            self._update_cutoff(reset=True)
            return
        index = job.refs.index(ref)
        key = job.keys[index]
        self._live = request
        self.start(
            (replace(job, refs=(ref,), keys=(key,), names=(job.names[index],)),),
            method=method,
            cutoff_edit=(key, value),
        )
        if self.worker is None:
            self._live = None
            self._live_failed = request[0]
            self._update_cutoff(reset=True)

    def run_batch(self):
        """Run missing and stale maps for the selected run method."""
        method = self.run_method_id()
        if method != DEFAULT_CLUSTERING_METHOD:
            project = self.window.project_data
            jobs = []
            for sample in project.samples.values():
                job = clustering_job(project, sample)
                result = project.clustering_result(job.sample_id, method)
                parameters = project.clustering_settings.parameters(job.sample_id, method)
                missing = [
                    (ref, name, key)
                    for ref, name, key in zip(job.refs, job.names, job.keys, strict=True)
                    if not self._map_matches(result, parameters, ref, key)
                ]
                if missing:
                    refs, names, keys = zip(*missing, strict=True)
                    jobs.append(replace(job, refs=refs, names=names, keys=keys))
            if jobs:
                self.start(jobs, method=method)
            else:
                self._append_status("All enabled maps are up to date.")
            return
        from .clustering_batch_dialog import ClusteringBatchDialog

        dialog = ClusteringBatchDialog(
            self.window.project_data,
            clustering_method(self.run_method_id()),
            self.window.clusteringSampleComboBox.currentData(),
            self.window,
        )
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            self.start(dialog.jobs())

    def start(self, jobs, *, method=None, cutoff_edit=None):
        """Capture queue inputs and publish each finished sample without changing selection."""
        if not jobs:
            return
        if (
            self.worker is not None
            or self.window.analysis_controller.worker is not None
            or self.window.analysis_controller.batch.active
        ):
            self.window.show_error("Another analysis is running.")
            return
        if not self.window.project_manager.require_project_directory(
            "Element clusters are stored in the project directory."
        ):
            return
        project = self.window.project_data
        method = method or self.run_method_id()
        if method == DEFAULT_CLUSTERING_METHOD:
            try:
                clustering_method(method).parameters(self._dialogs[method])
            except ValueError as error:
                self.window.show_error("Cannot start clustering", str(error))
                return
        generation = self._generation
        settings = project.clustering_settings
        sample_parameters = {
            job.sample_id: settings.parameters(job.sample_id, method) for job in jobs
        }
        if cutoff_edit is not None:
            key, cutoff = cutoff_edit
            options = sample_parameters[jobs[0].sample_id].method_options
            options["cutoff_scales"].pop(key, None)
            options.get("thresholds", {}).pop(key, None)
            if cutoff is not None:
                options["cutoff_scales"][key] = cutoff
        previous_results = {}
        if method != DEFAULT_CLUSTERING_METHOD:
            for job in jobs:
                previous = project.clustering_result(job.sample_id, method)
                if previous is not None and set(previous.element_refs) <= {
                    channel.ref for channel in project.samples[job.sample_id].channels.values()
                }:
                    previous_results[job.sample_id] = previous
        worker = ClusteringBatchWorker(
            jobs,
            project.sources,
            method,
            settings.intensity,
            self.window.project_dir,
            sample_parameters=sample_parameters,
            previous_results=previous_results,
        )
        thread = QtCore.QThread(self.window)
        worker.moveToThread(thread)
        failures = []

        def publish(result):
            if generation != self._generation or project is not self.window.project_data:
                return
            sample = project.samples.get(result.sample_id)
            if sample is None or not set(result.element_refs) <= {
                c.ref for c in sample.channels.values()
            }:
                return
            previous = project.clustering_result(result.sample_id, result.method_id)
            state = (
                previous.layer_settings
                if previous is not None
                else self._preview_settings.get(
                    (result.sample_id, result.method_id), SegmentationLayerSettings()
                )
            )
            result.layer_settings = deepcopy(state)
            if cutoff_edit is not None:
                key, cutoff = cutoff_edit
                manual = settings.method_cutoffs.setdefault(method, {}).setdefault(
                    result.sample_id, {}
                )
                manual[key] = cutoff
            project.set_clustering_result(result)
            self.window.project_state_manager.project_changed()
            self.window.clusteringResultsChanged.emit()
            if (
                self.window.clusteringSampleComboBox.currentData() == result.sample_id
                and self.current_method_id() == result.method_id
            ):
                self.show_result()

        def started(index, job):
            if generation == self._generation:
                self.window.clusteringProgress.setFormat(
                    f"{job.sample_name}: {index + 1} of {len(jobs)}"
                )

        def sample_failed(job, details):
            if generation == self._generation:
                failures.append(f"{job.sample_name}: {details}")
                self._append_status(failures[-1])

        def failed(details):
            if generation == self._generation and details:
                failures.append(details)

        def finished():
            if generation != self._generation:
                return
            self.worker = self.thread = None
            if self._live is not None:
                if failures or worker._abort:
                    self._live_failed = self._live[0]
                self._live = None
            self.set_busy(False)
            self._update_cutoff(reset=True)
            self.window.clusteringProgress.setFormat(
                "Stopped" if worker._abort else "Finished with errors" if failures else "Done"
            )
            if failures and cutoff_edit is None:
                self.window.show_error("Element clustering failed", "\n\n".join(failures))
            if self._pending is not None and not self._cutoff_timer.isActive():
                self._start_pending()

        worker.progress.connect(
            lambda message: self._append_status(message) if generation == self._generation else None
        )

        def work_progress(completed, total, message):
            if generation == self._generation:
                bar = self.window.clusteringProgress
                bar.setRange(0, total)
                bar.setValue(completed)
                bar.setFormat(message + " — %p%")

        worker.work_progress.connect(work_progress)
        worker.sample_started.connect(started)
        worker.sample_finished.connect(publish)
        worker.sample_failed.connect(sample_failed)
        worker.failed.connect(failed)
        worker.finished.connect(thread.quit, QtCore.Qt.DirectConnection)
        worker.failed.connect(thread.quit, QtCore.Qt.DirectConnection)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(finished)
        thread.finished.connect(thread.deleteLater)
        thread.started.connect(worker.run)
        self.worker, self.thread = worker, thread
        self.window.clusteringStatus.clear()
        self.set_busy(True)
        thread.start()

    def abort(self):
        self._pending = None
        self._cutoff_timer.stop()
        if self.worker is not None:
            self.worker.abort()

    def shutdown(self):
        """Stop the queue and invalidate pending callbacks before releasing source data."""
        self._cutoff_timer.stop()
        self._pending = self._live = self._live_failed = None
        for dialog in set(self._dialogs.values()):
            if hasattr(dialog, "stop_estimates"):
                dialog.stop_estimates()
            dialog.close()
        if self.worker is not None:
            self._generation += 1
            self.worker.abort()
            self.thread.wait()
            self.worker = self.thread = None

    def clear_project(self):
        """Clear transient choices and pooled display state without publishing late work."""
        self._generation += 1
        self.shutdown()
        self.worker = self.thread = None
        self._shown_result = self._view_key = None
        self._preview_settings.clear()
        self._display_settings = None
        self.map_color_editor.bind(self.naparihelper, None)
        self.color_editor.bind(self.naparihelper, None)
        if self.naparihelper is not None:
            self.naparihelper.reset_initial_fit()
            self.naparihelper.set_sample(None)
        self.set_busy(False)
        self.refresh_samples()

    def fit_view(self):
        if self.naparihelper is not None:
            self.naparihelper.viewer.reset_view(margin=0)

    def save_current_view(self):
        if self.naparihelper is None or not self.naparihelper.user_layers():
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
                self.naparihelper.qtwidget.screenshot(path=filename, flash=True)
            except Exception as error:
                self.window.show_error("Saving the current view failed", str(error))

    def export_results(self):
        result = self._result()
        if result is None:
            return
        directory = self.window.project_manager.default_export_directory()
        if directory is None:
            return
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self.window, "Choose export directory", directory
        )
        if directory:
            try:
                result.xrf_sample.export_results(directory)
            except Exception as error:
                self.window.show_error("Export failed", str(error))
