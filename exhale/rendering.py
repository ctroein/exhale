"""Select startup rendering and request consent for unavailable image viewers."""

import os
import sys

from qtpy import QtCore, QtWidgets

SOFTWARE_OPENGL_KEY = "rendering/software_opengl"


def software_rendering_supported():
    """Return whether Exhale has a software-rendering setup for this platform."""
    return sys.platform == "win32" or sys.platform.startswith("linux")


def configure_rendering(settings, *, software=False):
    """Apply preferences before QApplication or any OpenGL context is created."""
    if not software_rendering_supported():
        return
    if software or settings.value(SOFTWARE_OPENGL_KEY, False, type=bool):
        os.environ["QT_OPENGL"] = "software"
        QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_UseSoftwareOpenGL)
        if sys.platform.startswith("linux"):
            os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"


class RenderingFailureDialog(QtWidgets.QDialog):
    """Require an explicit choice before continuing without the Napari viewers."""

    def __init__(self, settings, details, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Unable to initialize image viewers")
        layout = QtWidgets.QVBoxLayout(self)
        summary = QtWidgets.QLabel(
            "The image viewers could not be initialized. Segmentation and clustering "
            "are unavailable. The error details can be opened below."
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        self.quit_option = QtWidgets.QRadioButton("Quit Exhale")
        self.continue_option = QtWidgets.QRadioButton(
            "Continue without segmentation and clustering"
        )
        self.software_option = QtWidgets.QRadioButton("Use software rendering")
        choices = (
            (self.quit_option, "Close Exhale without changing settings."),
            (self.continue_option, "Disables these features for this session only."),
            (
                self.software_option,
                "Saves the setting and closes Exhale. Start Exhale again manually.",
            ),
        )
        for option, explanation in choices:
            layout.addWidget(option)
            label = QtWidgets.QLabel(explanation)
            label.setWordWrap(True)
            layout.addWidget(label)
        if os.environ.get("QT_OPENGL") == "software":
            self.software_option.setEnabled(False)
            layout.addWidget(
                QtWidgets.QLabel("Software rendering was already selected and failed.")
            )
        elif not software_rendering_supported():
            self.software_option.setEnabled(False)
            label = QtWidgets.QLabel(
                "Software rendering is not supported by Exhale on this platform."
            )
            label.setWordWrap(True)
            layout.addWidget(label)
        self.details_button = QtWidgets.QPushButton("Show error details")
        self.details_button.setCheckable(True)
        layout.addWidget(self.details_button)
        self.details = QtWidgets.QPlainTextEdit(details)
        self.details.setReadOnly(True)
        self.details.hide()
        layout.addWidget(self.details)
        self.details_button.toggled.connect(self._show_details)
        self.action_button = QtWidgets.QPushButton("Quit")
        self.action_button.setDefault(True)
        layout.addWidget(self.action_button)
        self.action_button.clicked.connect(self.accept)
        for option, _ in choices:
            option.toggled.connect(self._update_action)
        self.quit_option.setChecked(True)
        self.resize(520, self.sizeHint().height())

    def _show_details(self, visible):
        self.details.setVisible(visible)
        self.details_button.setText("Hide error details" if visible else "Show error details")

    def _update_action(self):
        text = "Quit"
        if self.continue_option.isChecked():
            text = "Continue"
        elif self.software_option.isChecked():
            text = "Save and quit"
        self.action_button.setText(text)

    def allow_degraded_session(self):
        """Save only an accepted preference; closing the dialog always means quit."""
        if self.exec() != QtWidgets.QDialog.Accepted:
            return False
        if self.software_option.isChecked():
            self.settings.setValue(SOFTWARE_OPENGL_KEY, True)
            self.settings.sync()
        return self.continue_option.isChecked()
