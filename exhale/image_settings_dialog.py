"""Controller for composed-image settings."""

from qtpy import QtWidgets

from .image_settings_dialog_ui import Ui_ImageSettingsDialog


class ImageSettingsDialog(QtWidgets.QDialog, Ui_ImageSettingsDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
