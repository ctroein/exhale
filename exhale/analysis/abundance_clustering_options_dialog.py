"""Project-wide cutoff grid with sample/element overrides and background Auto estimates."""

from qtpy import QtCore, QtWidgets

from ..data.projectdata import ClusteringParameters, ClusteringSettings
from ..tooltips import ABUNDANCE_CLUSTERING_OPTIONS_DIALOG, apply_tooltips
from ..widgets import ContentDoubleSpinBox
from .abundance_clustering_options_dialog_ui import Ui_AbundanceClusteringOptionsDialog
from .clustering_abundance import (
    MAX_ESTIMATED_MULTIPLE,
    MIN_ESTIMATED_MULTIPLE,
    estimate_cutoff,
    validate_options,
)


class CutoffCell(QtWidgets.QWidget):
    """Choose Auto or an explicit multiple for one available sample/element pair."""

    changed = QtCore.Signal()
    activated = QtCore.Signal()

    def __init__(self, manual, fallback, parent=None):
        super().__init__(parent)
        self.auto = QtWidgets.QCheckBox()
        self.auto.setToolTip("Auto cutoff")
        self.auto.setAccessibleName("Auto cutoff")
        self.multiple = ContentDoubleSpinBox()
        self.multiple.setRange(0, 1000)
        self.multiple.setSingleStep(0.5)
        self.multiple.setValue(fallback if manual is None else manual)
        self.auto.setChecked(manual is None)
        self.multiple.setEnabled(manual is not None)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.addWidget(self.auto)
        layout.addWidget(self.multiple)
        self.auto.toggled.connect(self._auto_changed)
        self.multiple.valueChanged.connect(self._value_changed)
        self.multiple.installEventFilter(self)
        self.auto.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.Type.FocusIn:
            self.activated.emit()
        return super().eventFilter(watched, event)

    def _auto_changed(self):
        self.multiple.setEnabled(not self.auto.isChecked())
        self.activated.emit()
        self.changed.emit()

    def _value_changed(self):
        if not self.auto.isChecked():
            self.changed.emit()

    def show_estimate(self, multiple):
        if self.auto.isChecked():
            with QtCore.QSignalBlocker(self.multiple):
                self.multiple.setValue(multiple)


class CutoffEstimateWorker(QtCore.QThread):
    """Read captured maps and deliver estimates without touching widgets or project options."""

    estimated = QtCore.Signal(object, str, str, object, str)

    def __init__(self, token, inputs, minimum, parent):
        super().__init__(parent)
        self.token, self.inputs, self.minimum = token, inputs, minimum

    def run(self):
        for sample_id, key, source in self.inputs:
            if self.isInterruptionRequested():
                return
            estimate, error = None, ""
            try:
                if source is None:
                    raise RuntimeError("Source unavailable.")
                estimate = estimate_cutoff(source.array(), self.minimum)
            except (OSError, RuntimeError, ValueError, KeyError) as exc:
                error = str(exc)
            if self.isInterruptionRequested():
                return
            self.estimated.emit(self.token, sample_id, key, estimate, error)


class AbundanceClusteringOptionsDialog(QtWidgets.QDialog, Ui_AbundanceClusteringOptionsDialog):
    """Edit project configuration while retaining result parameters as historical snapshots."""

    settingsChanged = QtCore.Signal()

    def __init__(self, parent=None, *, method_id):
        super().__init__(parent)
        self.setupUi(self)
        for button in self.buttonBox.buttons():
            button.setAutoDefault(False)
            button.setDefault(False)
        self.method_id = method_id
        self._settings = ClusteringSettings()
        self._sample_id = None
        self._project = None
        self._cells = {}
        self._inputs = {}
        self._estimates = {}
        self._errors = {}
        self._signature = None
        self._worker = None
        self._token = object()
        self._loading = False
        self._units = ""
        self.thresholdTable.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        self.thresholdTable.currentCellChanged.connect(self._show_details)
        self.restoreAuto.clicked.connect(self._restore_all_auto)
        for control in (self.minClusterSize, self.linkRadius, self.cutoffScale, self.prominence):
            control.valueChanged.connect(self._controls_changed)
        apply_tooltips(self, ABUNDANCE_CLUSTERING_OPTIONS_DIALOG)
        self._load_controls()
        self.resize(1280, 760)

    def set_method(self, method_id):
        self.method_id = method_id
        self.settingsLayout.setRowVisible(self.prominence, method_id == "tomato")

    def _load_controls(self):
        self._loading = True
        options = validate_options(self._settings.abundance, tomato=True)
        self.minClusterSize.setValue(options["min_cluster_size"])
        self.linkRadius.setValue(options["radius"])
        self.cutoffScale.setValue(options["cutoff_scale"])
        self.prominence.setValue(options["prominence"])
        self.set_method(self.method_id)
        self._loading = False

    def _controls_changed(self):
        if self._loading:
            return
        minimum = self._settings.abundance["min_cluster_size"]
        self._settings.abundance.update(
            min_cluster_size=self.minClusterSize.value(),
            radius=self.linkRadius.value(),
            cutoff_scale=self.cutoffScale.value(),
            prominence=self.prominence.value(),
            auto_cutoff=True,
        )
        if minimum != self.minClusterSize.value():
            self._invalidate_estimates()
        self._refresh_values()
        self.settingsChanged.emit()

    def set_context(self, project, sample):
        """Populate all enabled sample/element pairs and focus the inspected sample."""
        self._project = project
        self._settings = project.clustering_settings
        self._sample_id = None if sample is None else sample.sample_id
        self._units = project.abundance_units
        self._load_controls()
        samples = sorted(
            project.samples.values(), key=lambda item: (item.name.casefold(), item.sample_id)
        )
        channels = {
            item.sample_id: item.effective_channels(project.project_channels) for item in samples
        }
        keys = sorted({key for maps in channels.values() for key in maps}, key=str.casefold)
        inputs = {
            (item.sample_id, key): item.channels[key].data_source
            for item in samples
            for key in channels[item.sample_id]
        }
        signature = (
            id(project),
            tuple((pair, id(source)) for pair, source in inputs.items()),
            self.minClusterSize.value(),
        )
        changed = signature != self._signature
        if changed:
            self.stop_estimates()
            self._estimates.clear()
            self._errors.clear()
            self._signature = signature
        self._inputs = inputs
        self._cells.clear()
        with QtCore.QSignalBlocker(self.thresholdTable):
            self.thresholdTable.clear()
            self.thresholdTable.setRowCount(len(samples))
            self.thresholdTable.setColumnCount(len(keys))
            self.thresholdTable.setVerticalHeaderLabels([item.name for item in samples])
            self.thresholdTable.setHorizontalHeaderLabels(keys)
            for row, item in enumerate(samples):
                for column, key in enumerate(keys):
                    if key not in channels[item.sample_id]:
                        empty = QtWidgets.QTableWidgetItem()
                        empty.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)
                        self.thresholdTable.setItem(row, column, empty)
                        continue
                    pair = item.sample_id, key
                    manual = self._settings.cutoffs.get(item.sample_id, {}).get(key)
                    cell = CutoffCell(manual, self.cutoffScale.value())
                    cell.changed.connect(lambda pair=pair: self._cell_changed(pair))
                    cell.activated.connect(
                        lambda row=row, column=column: self.thresholdTable.setCurrentCell(
                            row, column
                        )
                    )
                    self._cells[pair] = cell
                    self.thresholdTable.setCellWidget(row, column, cell)
            self.thresholdTable.resizeColumnsToContents()
            self.thresholdTable.resizeRowsToContents()
        if samples and keys:
            row = next(
                (i for i, item in enumerate(samples) if item.sample_id == self._sample_id), 0
            )
            self.thresholdTable.setCurrentCell(row, 0)
        self._refresh_values()
        self._start_estimates()

    def _restore_all_auto(self):
        """Clear project-wide manual cutoffs and show the cached Auto estimates."""
        self._settings.cutoffs.clear()
        for cell in self._cells.values():
            with QtCore.QSignalBlocker(cell.auto):
                cell.auto.setChecked(True)
            cell.multiple.setEnabled(False)
        self._refresh_values()
        self.settingsChanged.emit()

    def _cell_changed(self, pair):
        cell = self._cells[pair]
        overrides = self._settings.cutoffs.setdefault(pair[0], {})
        if cell.auto.isChecked():
            overrides.pop(pair[1], None)
            if not overrides:
                self._settings.cutoffs.pop(pair[0], None)
        else:
            overrides[pair[1]] = cell.multiple.value()
        self._refresh_values()
        self.settingsChanged.emit()

    def _invalidate_estimates(self):
        self.stop_estimates()
        self._estimates.clear()
        self._errors.clear()
        self._signature = None
        self._start_estimates()

    def _refresh_values(self):
        self.restoreAuto.setEnabled(bool(self._settings.cutoffs))
        for pair, cell in self._cells.items():
            estimate = self._estimates.get(pair)
            value = (
                estimate.multiple
                if estimate is not None and estimate.multiple is not None
                else self.cutoffScale.value()
            )
            cell.show_estimate(value)
        self._show_details()

    def _show_details(self, *_args):
        current = self.thresholdTable.cellWidget(
            self.thresholdTable.currentRow(), self.thresholdTable.currentColumn()
        )
        pair = next((pair for pair, cell in self._cells.items() if cell is current), None)
        if pair is None:
            self.cutoffDetails.clear()
            return
        cell = self._cells[pair]
        estimate = self._estimates.get(pair)
        if pair in self._errors:
            text = self._errors[pair]
        elif pair not in self._estimates:
            text = "Calculating Auto cutoff…"
        elif estimate is None:
            text = (
                f"Insufficient supported contrast. Using fallback {self.cutoffScale.value():g} s."
            )
        else:
            rows, columns = estimate.window
            multiple = (
                estimate.multiple if estimate.multiple is not None else self.cutoffScale.value()
            )
            text = (
                f"Auto: {multiple:.4g} s; cutoff {estimate.baseline + multiple * estimate.scale:.5g} {self._units}\n"
                f"B (median) = {estimate.baseline:.5g}; H (highest {columns} × {rows} window mean) = {estimate.bright:.5g}; s = {estimate.scale:.5g} {self._units}\n"
                f"Contrast fraction = {estimate.fraction:g}; contrast cutoff = {estimate.contrast_cutoff:.5g}; bounds = {MIN_ESTIMATED_MULTIPLE:g}–{MAX_ESTIMATED_MULTIPLE:g} s"
            )
            text += (
                f"; unbounded multiple = {estimate.uncapped_multiple:.5g} s"
                if estimate.multiple is not None
                else f"\ns = 0. Using fallback {self.cutoffScale.value():g} s."
            )
        if not cell.auto.isChecked():
            text += f"\nManual override: {cell.multiple.value():g} s."
        if text != self.cutoffDetails.toPlainText():
            self.cutoffDetails.setPlainText(text)

    def _start_estimates(self):
        if not self.isVisible() or (self._worker is not None and self._worker.isRunning()):
            return
        inputs = [
            (pair[0], pair[1], source)
            for pair, source in self._inputs.items()
            if pair not in self._estimates and pair not in self._errors
        ]
        if not inputs:
            return
        self.stop_estimates()
        worker = CutoffEstimateWorker(self._token, inputs, self.minClusterSize.value(), self)
        worker.estimated.connect(self._estimated)
        self._worker = worker
        worker.start()

    def _estimated(self, token, sample_id, key, estimate, error):
        if token is not self._token:
            return
        pair = sample_id, key
        if error:
            self._errors[pair] = error
        else:
            self._estimates[pair] = estimate
        self._refresh_values()

    def stop_estimates(self):
        """Join map readers before their project or input sources can be released."""
        self._token = object()
        if self._worker is not None:
            self._worker.requestInterruption()
            self._worker.wait()
            self._worker.deleteLater()
            self._worker = None

    def showEvent(self, event):
        super().showEvent(event)
        self._start_estimates()

    def hideEvent(self, event):
        self.stop_estimates()
        super().hideEvent(event)

    def parameters(self):
        """Snapshot the inspected sample; batch callers capture each sample separately."""
        parameters = self._settings.parameters(self._sample_id, self.method_id)
        return ClusteringParameters(
            method_options=validate_options(
                parameters.method_options, tomato=self.method_id == "tomato"
            )
        )

    def set_parameters(self, parameters):
        """Load explicitly requested settings into the configured sample's options."""
        options = validate_options(parameters.method_options, tomato=True)
        self._settings.abundance.update(
            {
                key: value
                for key, value in options.items()
                if key not in ("cutoff_scales", "thresholds")
            }
        )
        if self._sample_id is not None:
            self._settings.cutoffs[self._sample_id] = options["cutoff_scales"]
        self._load_controls()
