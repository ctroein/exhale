"""Method-specific inference settings and internal preprocessing parameters."""

from qtpy import QtWidgets

from ..data.projectdata import SegmentationParameters
from ..tooltips import SEGMENTATION_OPTIONS_DIALOG, apply_tooltips
from .segmentation_backends import stardist_thresholds
from .segmentation_options_dialog_ui import Ui_SegmentationOptionsDialog


class SegmentationOptionsDialog(QtWidgets.QDialog, Ui_SegmentationOptionsDialog):
    """Edit inference options without exposing downstream region processing."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.method_id = "stardist"
        self._stardist_defaults = stardist_thresholds()
        self.probThreshold.setValue(self._stardist_defaults["prob_thresh"])
        self.nmsThreshold.setValue(self._stardist_defaults["nms_thresh"])
        self._clip_percentiles = {"stardist": None, "cellpose": 99.9}
        self.set_method("stardist")
        self.buttonBox.rejected.connect(self.hide)
        apply_tooltips(self, SEGMENTATION_OPTIONS_DIALOG)

    def set_method(self, method_id: str) -> None:
        """Select a method page while preserving the other method’s controls."""
        if method_id not in self._clip_percentiles:
            raise ValueError(f"Unknown segmentation method {method_id!r}")
        self.method_id = method_id
        self.methodOptionsStack.setCurrentWidget(
            self.stardistPage if method_id == "stardist" else self.cellposePage
        )
        self.setWindowTitle("StarDist options" if method_id == "stardist" else "Cellpose options")

    def parameters(self) -> SegmentationParameters:
        """Snapshot controls for the next run and its persisted result."""
        options = {}
        if self.method_id == "stardist":
            for key, spin in (
                ("prob_thresh", self.probThreshold),
                ("nms_thresh", self.nmsThreshold),
            ):
                default = self._stardist_defaults[key]
                value = spin.value()
                # Preserve full model precision when the displayed default is unchanged.
                options[key] = default if value == round(default, spin.decimals()) else value
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
        if self.method_id == "stardist":
            options = parameters.method_options
            self.probThreshold.setValue(
                options.get("prob_thresh", self._stardist_defaults["prob_thresh"])
            )
            self.nmsThreshold.setValue(
                options.get("nms_thresh", self._stardist_defaults["nms_thresh"])
            )
        if self.method_id == "cellpose":
            options = parameters.method_options
            self.cellposeMinSize.setValue(options.get("min_size", 20))
            self.flowThreshold.setValue(options.get("flow_threshold", 0.4))
            self.cellprobThreshold.setValue(options.get("cellprob_threshold", 0.0))
