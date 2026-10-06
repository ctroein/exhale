"""Controller for image-analysis settings."""

from qtpy import QtWidgets

from .analysis_settings_dialog_ui import Ui_AnalysisSettingsDialog


class AnalysisSettingsDialog(QtWidgets.QDialog, Ui_AnalysisSettingsDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
