"""Select startup rendering and request consent for unavailable image viewers."""

import json
import os
import subprocess
import sys
from pathlib import Path

from qtpy import QtCore, QtWidgets

from .exceptiondialog import ExceptionDetailsDialog

SOFTWARE_OPENGL_KEY = "rendering/software_opengl"


class RenderingRestartRequested(Exception):
    """Unwind startup before relaunching with the saved rendering preference."""


def can_restart():
    """Require an advertised restart capability when a native launcher owns the process."""
    descriptor = json.loads(os.environ.get("EXHALE_NATIVE_INSTALLATION", "{}"))
    return not descriptor or descriptor.get("restart") == "1"


def restart_application():
    """Hand native restarts to the waiting launcher; relaunch source and uv runs directly."""
    if os.environ.get("EXHALE_NATIVE_INSTALLATION"):
        from .updates import native_installation

        if not can_restart():
            raise RuntimeError("This launcher requires a manual restart.")
        installation = native_installation()
        request = Path(installation["request"])
        temporary = request.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "action": "restart",
                    "token": installation["token"],
                    "environment": installation["environment"],
                }
            ),
            encoding="utf-8",
        )
        temporary.replace(request)
        return
    invoked = Path(sys.argv[0])
    entry = [str(invoked.resolve())] if invoked.name == "run_exhale.py" else ["-m", "exhale"]
    command = [sys.executable, *entry, *sys.argv[1:]]
    if sys.platform == "win32":
        subprocess.Popen(command)
    else:
        os.execv(sys.executable, command)


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


def configure_pyopengl_platform(app):
    """Match PyOpenGL context lookup to Qt before importing Napari or Vispy.

    Napari's NVIDIA workaround can select GLX after Qt has already selected
    native Wayland. At that point changing QT_QPA_PLATFORM cannot change Qt's
    live backend, so establish the matching PyOpenGL default first.
    """
    if not sys.platform.startswith("linux"):
        return
    platform = app.platformName()
    if platform.startswith("wayland"):
        os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    elif platform == "xcb":
        backend = "egl" if os.environ.get("QT_XCB_GL_INTEGRATION") == "xcb_egl" else "glx"
        os.environ.setdefault("PYOPENGL_PLATFORM", backend)


class RenderingFailureDialog(QtWidgets.QDialog):
    """Require an explicit choice before continuing without the Napari viewers."""

    def __init__(self, settings, details, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.error_details = details
        self._details_dialog = None
        self.setWindowTitle("Unable to initialize image viewers")
        layout = QtWidgets.QVBoxLayout(self)
        restart_text = (
            "restart Exhale using software rendering."
            if can_restart()
            else "save software rendering and restart Exhale manually. This launcher cannot restart automatically."
        )
        summary = QtWidgets.QLabel(
            "Exhale could not initialize the Napari viewer used for segmentation and "
            "clustering. You can disable these features for this session, or " + restart_text
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        self.quit_option = QtWidgets.QRadioButton("Quit")
        self.continue_option = QtWidgets.QRadioButton("Disable segmentation and clustering")
        self.software_option = QtWidgets.QRadioButton(
            "Restart with software rendering" if can_restart() else "Switch to software rendering"
        )
        choices = (self.quit_option, self.continue_option, self.software_option)
        for option in choices:
            layout.addWidget(option)
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
        buttons = QtWidgets.QHBoxLayout()
        self.details_button = QtWidgets.QPushButton("Show error details")
        self.details_button.clicked.connect(self._show_details)
        buttons.addWidget(self.details_button)
        buttons.addStretch()
        self.action_button = QtWidgets.QPushButton("Quit")
        self.action_button.setDefault(True)
        buttons.addWidget(self.action_button)
        layout.addLayout(buttons)
        self.action_button.clicked.connect(self.accept)
        for option in choices:
            option.toggled.connect(self._update_action)
        self.quit_option.setChecked(True)
        self.resize(520, self.sizeHint().height())

    def _show_details(self):
        if self._details_dialog is None:
            self._details_dialog = ExceptionDetailsDialog(self)
        self._details_dialog.show_exception(
            title="Napari viewer initialization failed",
            summary="Exhale failed while initializing the viewer for segmentation and clustering.",
            details=self.error_details,
        )

    def _update_action(self):
        text = "Quit"
        if self.continue_option.isChecked():
            text = "Continue"
        elif self.software_option.isChecked():
            text = "Restart" if can_restart() else "Save and quit"
        self.action_button.setText(text)

    def allow_degraded_session(self):
        """Save an accepted preference and request restart; closing the dialog means quit."""
        if self.exec() != QtWidgets.QDialog.Accepted:
            return False
        if self.software_option.isChecked():
            self.settings.setValue(SOFTWARE_OPENGL_KEY, True)
            self.settings.sync()
            if can_restart():
                raise RenderingRestartRequested
        return self.continue_option.isChecked()
