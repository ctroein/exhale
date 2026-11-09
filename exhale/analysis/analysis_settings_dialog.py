"""Options dialog for the intensity-partition clustering method."""

from qtpy import QtWidgets

from .analysis_settings_dialog_ui import Ui_AnalysisSettingsDialog


class AnalysisSettingsDialog(QtWidgets.QDialog, Ui_AnalysisSettingsDialog):
    """Edit the range of intensity-class counts considered for each element."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
