"""Edit spatial HDBSCAN settings and abundance cutoffs shared by element key in a batch."""

from qtpy import QtCore, QtGui, QtWidgets

from ..data.projectdata import ClusteringParameters
from ..tooltips import HDBSCAN_OPTIONS_DIALOG, apply_tooltips
from .clustering_hdbscan import DEFAULT_MIN_CLUSTER_SIZE, DEFAULT_MIN_SAMPLES, validate_options
from .hdbscan_options_dialog_ui import Ui_HdbscanOptionsDialog


class HdbscanOptionsDialog(QtWidgets.QDialog, Ui_HdbscanOptionsDialog):
    """Retain per-element overrides while the controller changes sample context."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.minClusterSize.setValue(DEFAULT_MIN_CLUSTER_SIZE)
        self.densitySupport.setValue(DEFAULT_MIN_SAMPLES)
        self._thresholds = {}
        self.thresholdTable.verticalHeader().hide()
        header = self.thresholdTable.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        self.thresholdTable.itemChanged.connect(self._automatic_changed)
        apply_tooltips(self, HDBSCAN_OPTIONS_DIALOG)

    def _automatic_changed(self, item):
        if item.column() == 1:
            automatic = item.checkState() == QtCore.Qt.CheckState.Checked
            editor = self.thresholdTable.cellWidget(item.row(), 2)
            editor.setEnabled(not automatic)
            editor.setPlaceholderText("Automatic" if automatic else "Enter cutoff")

    def _draft_thresholds(self):
        """Preserve unfinished manual entries across sample switches."""
        thresholds = dict(self._thresholds)
        for row in range(self.thresholdTable.rowCount()):
            key = self.thresholdTable.item(row, 0).data(QtCore.Qt.UserRole)
            if self.thresholdTable.item(row, 1).checkState() == QtCore.Qt.CheckState.Checked:
                thresholds.pop(key, None)
                continue
            thresholds[key] = self.thresholdTable.cellWidget(row, 2).text()
        return thresholds

    def _read_thresholds(self):
        """Collect manual cutoffs without silently discarding invalid input."""
        thresholds = {}
        for key, text in self._draft_thresholds().items():
            try:
                thresholds[key] = float(text)
            except (ValueError, TypeError) as error:
                raise ValueError(f"Enter a finite abundance cutoff for {key}.") from error
        validate_options({"thresholds": thresholds})
        return thresholds

    def set_context(self, project, sample):
        """Show this sample's enabled elements, retaining overrides for other batch samples."""
        channels = (
            []
            if sample is None
            else sorted(
                sample.effective_channels(project.project_channels).values(),
                key=lambda channel: (channel.name.casefold(), channel.key.casefold()),
            )
        )
        self._thresholds = self._draft_thresholds()
        with QtCore.QSignalBlocker(self.thresholdTable):
            self.thresholdTable.setRowCount(0)
            self.thresholdTable.setRowCount(len(channels))
            for row, channel in enumerate(channels):
                name = (
                    channel.key
                    if channel.name == channel.key
                    else f"{channel.name} [{channel.key}]"
                )
                item = QtWidgets.QTableWidgetItem(name)
                item.setData(QtCore.Qt.UserRole, channel.key)
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                self.thresholdTable.setItem(row, 0, item)
                automatic = QtWidgets.QTableWidgetItem()
                automatic.setFlags(
                    QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsUserCheckable
                )
                manual = channel.key in self._thresholds
                automatic.setCheckState(
                    QtCore.Qt.CheckState.Unchecked if manual else QtCore.Qt.CheckState.Checked
                )
                self.thresholdTable.setItem(row, 1, automatic)
                editor = QtWidgets.QLineEdit()
                validator = QtGui.QDoubleValidator(editor)
                validator.setLocale(QtCore.QLocale.c())
                editor.setValidator(validator)
                editor.setText(str(self._thresholds[channel.key]) if manual else "")
                editor.setEnabled(manual)
                editor.setPlaceholderText("Enter cutoff" if manual else "Automatic")
                self.thresholdTable.setCellWidget(row, 2, editor)
        units = project.abundance_units
        self.thresholdTable.horizontalHeaderItem(2).setText(
            f"Abundance cutoff ({units})" if units else "Abundance cutoff"
        )

    def parameters(self):
        """Snapshot the settings for execution and project persistence."""
        options = {
            "min_cluster_size": self.minClusterSize.value(),
            "min_samples": self.densitySupport.value(),
            "thresholds": self._read_thresholds(),
        }
        validate_options(options)
        return ClusteringParameters(method_options=options)

    def set_parameters(self, parameters):
        """Restore a result's settings, including cutoffs for elements outside this sample."""
        minimum, support, thresholds = validate_options(parameters.method_options)
        self.minClusterSize.setValue(minimum)
        self.densitySupport.setValue(support)
        self._thresholds = thresholds
        # The controller supplies the current sample immediately after restoration.
        self.thresholdTable.setRowCount(0)
