"""Application settings dialog."""

from qtpy import QtCore, QtWidgets

from . import appearance
from .project.projectstatemanager import PROJECT_AUTOSAVE_KEY, PROJECT_SAVE_ON_EXIT_KEY
from .settings_dialog_ui import Ui_SettingsDialog
from .tooltips import SETTINGS_DIALOG, apply_tooltips


class SettingsDialog(QtWidgets.QDialog, Ui_SettingsDialog):
    """Edit persistent application-wide preferences stored in ``QSettings``."""

    def __init__(self, settings: QtCore.QSettings, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.settings = settings
        scheme = settings.value(appearance.COLOR_SCHEME_KEY, "system")
        if scheme not in appearance.COLOR_SCHEMES:
            scheme = "system"
        self.colourSchemeComboBox.setCurrentIndex(appearance.COLOR_SCHEMES.index(scheme))
        self.autosaveProjectCheckBox.setChecked(
            settings.value(PROJECT_AUTOSAVE_KEY, True, type=bool)
        )
        self.saveProjectOnExitCheckBox.setChecked(
            settings.value(PROJECT_SAVE_ON_EXIT_KEY, True, type=bool)
        )
        apply_tooltips(self, SETTINGS_DIALOG)

    def accept(self):
        scheme = appearance.COLOR_SCHEMES[self.colourSchemeComboBox.currentIndex()]
        self.settings.setValue(appearance.COLOR_SCHEME_KEY, scheme)
        self.settings.setValue(PROJECT_AUTOSAVE_KEY, self.autosaveProjectCheckBox.isChecked())
        self.settings.setValue(PROJECT_SAVE_ON_EXIT_KEY, self.saveProjectOnExitCheckBox.isChecked())
        appearance.manager().set_scheme(scheme)
        parent = self.parent()
        if parent is not None and hasattr(parent, "project_state_manager"):
            parent.project_state_manager.autosave_setting_changed()
        super().accept()
