"""Choose samples for a fixed-method, all-enabled-elements clustering batch."""

from qtpy import QtCore, QtWidgets

from .. import icons
from ..data.clustering import clustering_job
from .batchselection import configure_batch_selection
from .clustering_batch_dialog_ui import Ui_ClusteringBatchDialog


class ClusteringBatchDialog(QtWidgets.QDialog, Ui_ClusteringBatchDialog):
    """Review explicit sample checks, enabled-map counts and existing method results."""

    def __init__(self, project, method, current_sample_id=None, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.methodInfo.setText(method.name)
        self.startButton = self.buttonBox.addButton(
            "Start batch", QtWidgets.QDialogButtonBox.AcceptRole
        )
        self.startButton.setIcon(icons.icon(icons.IconName.BATCH))
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.rows = []
        for sample in sorted(project.samples.values(), key=lambda sample: sample.name.casefold()):
            job = clustering_job(project, sample)
            item = QtWidgets.QTreeWidgetItem(self.sampleTree, [sample.name, str(len(job.refs)), ""])
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(
                0,
                QtCore.Qt.Checked if sample.sample_id == current_sample_id else QtCore.Qt.Unchecked,
            )
            existing = project.clustering_result(sample.sample_id, method.method_id) is not None
            available = bool(job.refs) and all(
                ref.source_id in project.assets and project.assets[ref.source_id].is_available
                for ref in job.refs
            )
            if not available:
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(0, QtCore.Qt.Unchecked)
            self.rows.append((item, job, existing, available))
        header = self.sampleTree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for column in (1, 2):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeToContents)
        self.sampleTree.itemChanged.connect(self.refresh)
        configure_batch_selection(
            self,
            ((item, existing, available) for item, _job, existing, available in self.rows),
            self.refresh,
        )
        self.refresh()
        self.resize(
            self.fontMetrics().averageCharWidth() * 85, self.fontMetrics().lineSpacing() * 24
        )

    def jobs(self):
        return tuple(
            job
            for item, job, _existing, available in self.rows
            if available and item.checkState(0) == QtCore.Qt.Checked
        )

    def refresh(self, *_unused):
        with QtCore.QSignalBlocker(self.sampleTree):
            for item, job, existing, available in self.rows:
                item.setText(
                    2,
                    "No enabled maps"
                    if not job.refs
                    else "Data unavailable"
                    if not available
                    else "Already clustered"
                    if existing
                    else "Not clustered",
                )
        count = len(self.jobs())
        self.selectionInfo.setText(f"{count} sample{'s' if count != 1 else ''} selected")
        self.startButton.setEnabled(count > 0)
