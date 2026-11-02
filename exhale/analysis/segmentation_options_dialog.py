"""Cellpose inference settings with internal per-method preprocessing parameters."""

from qtpy import QtWidgets

from ..data.projectdata import SegmentationParameters
from ..tooltips import SEGMENTATION_OPTIONS_DIALOG, apply_tooltips
from .segmentation_options_dialog_ui import Ui_SegmentationOptionsDialog


class SegmentationOptionsDialog(QtWidgets.QDialog, Ui_SegmentationOptionsDialog):
    """Edit Cellpose inference options without exposing downstream region processing."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.method_id = "stardist"
        self._clip_percentiles = {"stardist": None, "cellpose": 99.9}
        self.buttonBox.rejected.connect(self.hide)
        apply_tooltips(self, SEGMENTATION_OPTIONS_DIALOG)

    def set_method(self, method_id: str) -> None:
        """Select parameters for a method and close options when none are exposed."""
        if method_id not in self._clip_percentiles:
            raise ValueError(f"Unknown segmentation method {method_id!r}")
        self.method_id = method_id
        if method_id != "cellpose":
            self.hide()

    def parameters(self) -> SegmentationParameters:
        """Snapshot controls for the next run and its persisted result."""
        options = {}
        if self.method_id == "cellpose":
            options = {
                "min_size": self.cellposeMinSize.value(),
                "flow_threshold": self.flowThreshold.value(),
                "cellprob_threshold": self.cellprobThreshold.value(),
            }
        return SegmentationParameters(
            clip_percentile=self._clip_percentiles[self.method_id],
            method_options=options,
        )

    def set_parameters(self, parameters: SegmentationParameters) -> None:
        """Restore the parameters that produced the displayed sample/method result."""
        self._clip_percentiles[self.method_id] = parameters.clip_percentile
        if self.method_id == "cellpose":
            options = parameters.method_options
            self.cellposeMinSize.setValue(options.get("min_size", 20))
            self.flowThreshold.setValue(options.get("flow_threshold", 0.4))
            self.cellprobThreshold.setValue(options.get("cellprob_threshold", 0.0))
