"""Review sample scope and per-sample nuclei channels before starting a batch."""

from qtpy import QtCore, QtWidgets

from .. import icons
from ..data.segmentationbatch import (
    SegmentationBatchJob,
    batch_channels,
    suggested_batch_channel,
)
from .segmentation_batch_dialog_ui import Ui_SegmentationBatchDialog


class SegmentationBatchDialog(QtWidgets.QDialog, Ui_SegmentationBatchDialog):
    """Keep sample rows stable while selections, channels and skip policy are edited."""

    def __init__(self, project, method, *, current_sample_id=None, current_ref=None, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.methodInfo.setText(f"Method: {method.name} — using the current options")
        self.startButton = self.buttonBox.addButton(
            "Start batch", QtWidgets.QDialogButtonBox.AcceptRole
        )
        self.startButton.setIcon(icons.icon(icons.IconName.START))
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
        self.skipExisting.toggled.connect(self._refresh)
        self.selectAll.clicked.connect(lambda: self._select(True))
        self.selectNone.clicked.connect(lambda: self._select(False))
        self._refresh()
        metrics = self.fontMetrics()
        self.resize(metrics.averageCharWidth() * 100, metrics.lineSpacing() * 26)

    def _select(self, checked):
        with QtCore.QSignalBlocker(self.sampleTree):
            for item, _combo, _sample, _existing, available in self._rows:
                if available:
                    item.setCheckState(0, QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked)
        self._refresh()

    def jobs(self):
        """Return only explicitly included jobs with a usable channel."""
        return [
            SegmentationBatchJob(sample.sample_id, sample.name, combo.currentData())
            for item, combo, sample, existing, _available in self._rows
            if item.checkState(0) == QtCore.Qt.Checked
            and combo.currentData() is not None
            and not (existing and self.skipExisting.isChecked())
        ]

    def _refresh(self, *_unused):
        missing = 0
        with QtCore.QSignalBlocker(self.sampleTree):
            for item, combo, _sample, existing, available in self._rows:
                skipped = existing and self.skipExisting.isChecked()
                checked = item.checkState(0) == QtCore.Qt.Checked
                if not available:
                    status = "No usable element maps"
                elif skipped:
                    status = "Already segmented — skipped"
                elif combo.currentData() is None:
                    status = "Choose a nuclei channel"
                else:
                    status = "Already segmented" if existing else "Not segmented"
                item.setText(2, status)
                missing += bool(checked and not skipped and combo.currentData() is None)
        count = len(self.jobs())
        text = f"{count} sample{'s' if count != 1 else ''} ready"
        if missing:
            text += f"; {missing} {'needs' if missing == 1 else 'need'} a nuclei channel"
        self.selectionInfo.setText(text)
        self.startButton.setEnabled(count > 0 and not missing)
