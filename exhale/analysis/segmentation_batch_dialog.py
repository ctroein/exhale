"""Review sample scope and per-sample segmentation channels before starting a batch."""

from qtpy import QtCore, QtWidgets

from .. import icons
from ..data.segmentationbatch import (
    SegmentationBatchJob,
    batch_channels,
    suggested_batch_channel,
)
from .batchselection import configure_batch_selection
from .segmentation_batch_dialog_ui import Ui_SegmentationBatchDialog


class SegmentationBatchDialog(QtWidgets.QDialog, Ui_SegmentationBatchDialog):
    """Keep sample rows stable while explicit selections and channels are edited."""

    def __init__(self, project, method, *, current_sample_id=None, current_ref=None, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.methodInfo.setText(f"Method: {method.name}")
        self.startButton = self.buttonBox.addButton(
            "Start batch", QtWidgets.QDialogButtonBox.AcceptRole
        )
        self.startButton.setIcon(icons.icon(icons.IconName.BATCH))
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self._rows = []
        for sample in sorted(project.samples.values(), key=lambda sample: sample.name.casefold()):
            channels = batch_channels(project, sample)
            item = QtWidgets.QTreeWidgetItem(self.sampleTree, [sample.name, "", ""])
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(
                0,
                QtCore.Qt.Checked
                if sample.sample_id == current_sample_id and channels
                else QtCore.Qt.Unchecked,
            )
            combo = QtWidgets.QComboBox(self.sampleTree)
            combo.addItem("None", None)
            for channel in channels:
                combo.addItem(channel.name, channel.ref)
            selected = suggested_batch_channel(
                project,
                sample,
                method.method_id,
                current_ref=current_ref if sample.sample_id == current_sample_id else None,
            )
            combo.setCurrentIndex(max(0, combo.findData(selected)))
            combo.setEnabled(bool(channels))
            self.sampleTree.setItemWidget(item, 1, combo)
            history = project.segmentation_histories.get(sample.sample_id)
            existing = (
                history is not None and history.latest_for_method(method.method_id) is not None
            )
            self._rows.append((item, combo, sample, existing, bool(channels)))
            if not channels:
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsUserCheckable)
            combo.currentIndexChanged.connect(self._refresh)
        header = self.sampleTree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.sampleTree.itemChanged.connect(self._refresh)
        configure_batch_selection(
            self,
            (
                (item, existing, available)
                for item, _combo, _sample, existing, available in self._rows
            ),
            self._refresh,
        )
        self._refresh()
        metrics = self.fontMetrics()
        self.resize(metrics.averageCharWidth() * 100, metrics.lineSpacing() * 26)

    def jobs(self):
        """Return only explicitly included jobs with a usable channel."""
        return [
            SegmentationBatchJob(sample.sample_id, sample.name, combo.currentData())
            for item, combo, sample, _existing, _available in self._rows
            if item.checkState(0) == QtCore.Qt.Checked and combo.currentData() is not None
        ]

    def _refresh(self, *_unused):
        missing = 0
        with QtCore.QSignalBlocker(self.sampleTree):
            for item, combo, _sample, existing, available in self._rows:
                checked = item.checkState(0) == QtCore.Qt.Checked
                if not available:
                    status = "No usable maps"
                elif combo.currentData() is None:
                    status = "Choose channel"
                else:
                    status = "Already segmented" if existing else "Not segmented"
                item.setText(2, status)
                missing += bool(checked and combo.currentData() is None)
        count = sum(item.checkState(0) == QtCore.Qt.Checked for item, *_rest in self._rows)
        text = f"{count} sample{'s' if count != 1 else ''} selected"
        if missing:
            text += f"; {missing} {'needs' if missing == 1 else 'need'} a channel"
        self.selectionInfo.setText(text)
        self.startButton.setEnabled(count > 0 and not missing)
