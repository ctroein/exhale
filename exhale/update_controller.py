"""Own background release checks and application update confirmation."""

import json
import os
import shutil
import sys
import time
from pathlib import Path

from qtpy import QtCore, QtWidgets

from . import exhale_version, updates


class ReleaseCheck(QtCore.QThread):
    """Check the running installation and PyPI without blocking the interface."""

    completed = QtCore.Signal(object)

    def run(self):
        result = {"installation": None, "reason": "", "version": None, "error": ""}
        try:
            result["installation"] = updates.installation()
        except (ValueError, OSError, KeyError, TypeError) as error:
            result["reason"] = str(error)
        except Exception as error:
            result["reason"] = f"Could not identify this installation: {error}"
        try:
            # Source versions such as 1.4.4-dev do not describe a published installation.
            if not result["installation"] and "dev" in exhale_version:
                result["error"] = "This is a development version. Update it through Git."
            else:
                result["version"] = updates.check_release(exhale_version)
        except Exception as error:
            result["error"] = f"Could not check for updates: {error}"
        self.completed.emit(result)


class UpdateController(QtCore.QObject):
    """Schedule checks, present results, and stage an explicitly requested update."""

    checkingChanged = QtCore.Signal(bool)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.settings = window.settings
        self.worker = None
        self.pending_job = None
        self._closing = False
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(60 * 60 * 1000)
        self.timer.timeout.connect(self.check_if_due)

    @property
    def state_directory(self):
        if sys.platform == "win32":
            return (
                Path(
                    os.environ.get(
                        "LOCALAPPDATA",
                        QtCore.QStandardPaths.writableLocation(
                            QtCore.QStandardPaths.AppLocalDataLocation
                        ),
                    )
                )
                / "Exhale"
                / "updates"
            )
        return (
            Path(QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.GenericDataLocation))
            / "Exhale"
            / "updates"
        )

    def start(self):
        """Enable periodic checks for normal supported desktop GUI launches."""
        if sys.platform.startswith("linux") or sys.platform in ("win32", "darwin"):
            self._show_previous_result()
            self.timer.start()
            self.check_if_due()

    def check_if_due(self):
        if not self.settings.value(updates.AUTOMATIC_CHECKS_KEY, True, type=bool):
            return
        last = self.settings.value(updates.LAST_CHECK_KEY, 0, type=float)
        if time.time() - last >= updates.CHECK_INTERVAL:
            self.check(manual=False)

    def check(self, *, manual=True):
        if self._closing or self.worker is not None:
            return
        self._manual = manual
        self.settings.setValue(updates.LAST_CHECK_KEY, time.time())
        self.worker = ReleaseCheck(self)
        self.worker.completed.connect(self._checked)
        self.worker.finished.connect(self._finished)
        self.checkingChanged.emit(True)
        self.worker.start()

    @QtCore.Slot()
    def _finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self.checkingChanged.emit(False)

    @QtCore.Slot(object)
    def _checked(self, result):
        if self._closing:
            return
        if result["error"]:
            if self._manual:
                QtWidgets.QMessageBox.information(self.window, "Exhale updates", result["error"])
            return
        version = result["version"]
        if not version:
            if self._manual:
                QtWidgets.QMessageBox.information(
                    self.window,
                    "Exhale updates",
                    "No newer stable release supports this Python version.",
                )
            return
        if not self._manual and version == self.settings.value(updates.NOTIFIED_VERSION_KEY, ""):
            return
        self.settings.setValue(updates.NOTIFIED_VERSION_KEY, version)
        message = QtWidgets.QMessageBox(self.window)
        message.setWindowTitle("Exhale update available")
        message.setText(f"Exhale {version} is available. You are running {exhale_version}.")
        installation = result["installation"]
        native = installation and installation.get("kind")
        details = (
            "You can also update by downloading a newer installer from "
            "https://github.com/ctroein/exhale/releases."
            if native or sys.platform in ("win32", "darwin")
            else f"To update a uv tool installation, run:\n\n{updates.UPDATE_COMMAND}"
        )
        update_button = None
        if installation:
            details += "\n\nUpdate now closes Exhale, updates it, then reopens it. " + (
                "Your selected segmentation backends are retained."
                if native
                else "Your selected extras and installation constraints are retained."
            )
            update_button = message.addButton("Update now", QtWidgets.QMessageBox.AcceptRole)
        else:
            details += "\n\n" + result["reason"]
        message.setInformativeText(details)
        message.addButton(QtWidgets.QMessageBox.Close)
        message.exec()
        if update_button is not None and message.clickedButton() == update_button:
            try:
                self.pending_job = updates.prepare_update(
                    {**installation, "version": version}, self.state_directory
                )
            except OSError as error:
                self.window.show_error("Could not prepare the update", str(error))
                return
            if not self.window.close():
                shutil.rmtree(self.pending_job)
                self.pending_job = None
            else:
                QtWidgets.QApplication.closeAllWindows()

    def _show_previous_result(self):
        directory = self.state_directory
        if not directory.exists():
            return
        for path in sorted(directory.glob("update-*/result.json")):
            try:
                result = json.loads(path.read_text(encoding="utf-8"))
                text = (
                    "Exhale was updated and its startup check passed."
                    if result["success"]
                    else "The update or its startup check failed. See the log for details."
                )
                QtWidgets.QMessageBox.information(
                    self.window, "Exhale update result", f"{text}\n\nLog: {result['log']}"
                )
                path.rename(path.with_name("reported.json"))
            except (OSError, ValueError, KeyError):
                continue

    def shutdown(self):
        """Stop scheduling and finish a bounded in-flight check before destroying Qt."""
        self._closing = True
        self.timer.stop()
        if self.worker is not None:
            self.worker.wait()
