"""Application settings dialog."""

import sys
from pathlib import Path

from qtpy import QtCore, QtWidgets

from . import appearance, icons, updates
from .analysis.model_store import MODEL_DIRECTORY_SETTING
from .model_settings import default_model_directory, model_directory
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
        self.modelDirectoryEdit.setText(str(model_directory(settings)))
        self.modelDirectoryBrowse.setIcon(icons.icon(icons.IconName.FOLDER))
        self.modelDirectoryBrowse.clicked.connect(self._choose_model_directory)
        self.updatesGroupBox.setVisible(
            sys.platform.startswith("linux") or sys.platform in ("win32", "darwin")
        )
        self.automaticUpdatesCheckBox.setChecked(
            settings.value(updates.AUTOMATIC_CHECKS_KEY, True, type=bool)
        )
        self.checkUpdatesButton.clicked.connect(self._check_updates)
        controller = getattr(parent, "update_controller", None)
        self.checkUpdatesButton.setEnabled(controller is not None and controller.worker is None)
        if controller is not None:
            controller.checkingChanged.connect(self._checking_changed)
        apply_tooltips(self, SETTINGS_DIALOG)

    def _checking_changed(self, checking):
        self.checkUpdatesButton.setEnabled(not checking)
        self.checkUpdatesButton.setText("Checking…" if checking else "Check now")

    def _check_updates(self):
        self.parent().update_controller.check()

    def _choose_model_directory(self):
        directory = self.modelDirectoryEdit.text().strip() or str(default_model_directory())
        chosen = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Choose model directory", directory
        )
        if chosen:
            self.modelDirectoryEdit.setText(chosen)

    def accept(self):
        value = self.modelDirectoryEdit.text().strip()
        directory = Path(value).expanduser().resolve() if value else default_model_directory()
        if directory.exists() and not directory.is_dir():
            QtWidgets.QMessageBox.warning(
                self, "Invalid model directory", "Choose a directory for the trained models."
            )
            return
        self.settings.setValue(MODEL_DIRECTORY_SETTING, str(directory))
        self.settings.setValue(
            updates.AUTOMATIC_CHECKS_KEY, self.automaticUpdatesCheckBox.isChecked()
        )
        scheme = appearance.COLOR_SCHEMES[self.colourSchemeComboBox.currentIndex()]
        self.settings.setValue(appearance.COLOR_SCHEME_KEY, scheme)
        self.settings.setValue(PROJECT_AUTOSAVE_KEY, self.autosaveProjectCheckBox.isChecked())
        self.settings.setValue(PROJECT_SAVE_ON_EXIT_KEY, self.saveProjectOnExitCheckBox.isChecked())
        appearance.manager().set_scheme(scheme)
        parent = self.parent()
        if parent is not None and hasattr(parent, "project_state_manager"):
            parent.project_state_manager.autosave_setting_changed()
        super().accept()
