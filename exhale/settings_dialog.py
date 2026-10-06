"""Application settings dialog."""

from qtpy import QtCore, QtWidgets

from . import appearance
from .projectstatemanager import PROJECT_AUTOSAVE_KEY
from .settings_dialog_ui import Ui_SettingsDialog


class SettingsDialog(QtWidgets.QDialog, Ui_SettingsDialog):
    def __init__(self, settings: QtCore.QSettings, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.settings = settings
        scheme = settings.value(appearance.COLOR_SCHEME_KEY, "system")
        if scheme not in appearance.COLOR_SCHEMES:
            scheme = "system"
        self.colourSchemeComboBox.setCurrentIndex(
            appearance.COLOR_SCHEMES.index(scheme))
        self.autosaveProjectCheckBox.setChecked(
            settings.value(PROJECT_AUTOSAVE_KEY, True, type=bool))

    def accept(self):
        scheme = appearance.COLOR_SCHEMES[
            self.colourSchemeComboBox.currentIndex()]
        self.settings.setValue(appearance.COLOR_SCHEME_KEY, scheme)
        self.settings.setValue(
            PROJECT_AUTOSAVE_KEY, self.autosaveProjectCheckBox.isChecked())
        appearance.manager().set_scheme(scheme)
        parent = self.parent()
        if parent is not None and hasattr(parent, "project_state_manager"):
            parent.project_state_manager.autosave_setting_changed()
        super().accept()
