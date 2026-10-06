"""Project-directory selection and persistence policy."""

from __future__ import annotations

import json
from pathlib import Path

from qtpy import QtWidgets

from . import application_name, projectio
from .overridecursor import OverrideCursor
from .projectstatemanager import PROJECT_AUTOSAVE_FILENAME


PROJECT_FILENAME = "project.xhp"
PROJECT_DIRECTORY_SETTING = "ProjectDirectory"


class ProjectManager:
    """Manage the directory associated with the window's current project."""

    def __init__(self, window):
        self.window = window

    def default_dialog_directory(self) -> str:
        if self.window.project_dir is not None:
            return str(self.window.project_dir)
        return self.window.settings.value(
            PROJECT_DIRECTORY_SETTING, str(Path.home()))

    def remember_directory(self, directory: str | Path) -> None:
        self.window.settings.setValue(
            PROJECT_DIRECTORY_SETTING, str(Path(directory)))

    def new_project(self) -> bool:
        w = self.window
        if not w.project_state_manager.prepare_to_leave_project(
                "creating a new project"):
            return False
        with w.project_state_manager.suspend_notifications():
            w.clear_project()
            w.project_dir = None
            w.initialize_empty_project()
            w.refresh_project_ui()
        w.project_state_manager.mark_saved()
        w.update_window_title()
        return True

    def open_project(self) -> bool:
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self.window,
            f"Open {application_name} project",
            self.default_dialog_directory(),
        )
        if not directory:
            return False
        return self.load_project_dir(directory)

    def load_project_dir(self, directory: str | Path) -> bool:
        directory = Path(directory).resolve()
        project_file = directory / PROJECT_FILENAME
        try:
            with project_file.open(encoding="utf-8") as stream:
                saved_state = json.load(stream)
            projectio.validate_project_state(saved_state)
        except Exception as exc:
            self._show_error("Loading failed", exc)
            return False

        if not self.window.project_state_manager.prepare_to_leave_project(
                "opening another project"):
            return False

        state = saved_state
        recovered = False
        autosave_file = directory / PROJECT_AUTOSAVE_FILENAME
        if autosave_file.is_file():
            try:
                with autosave_file.open(encoding="utf-8") as stream:
                    autosaved_state = json.load(stream)
                projectio.validate_project_state(autosaved_state)
            except Exception as exc:
                self._show_error("Loading autosaved project failed", exc)
                autosave_file.unlink(missing_ok=True)
            else:
                if autosaved_state != saved_state:
                    answer = QtWidgets.QMessageBox.question(
                        self.window,
                        "Recover autosaved changes?",
                        f"{application_name} found autosaved changes for this project. "
                        "Recover them?",
                        (QtWidgets.QMessageBox.Yes
                         | QtWidgets.QMessageBox.No
                         | QtWidgets.QMessageBox.Cancel),
                        QtWidgets.QMessageBox.Yes,
                    )
                    if answer == QtWidgets.QMessageBox.Cancel:
                        return False
                    if answer == QtWidgets.QMessageBox.Yes:
                        state = autosaved_state
                        recovered = True
                    else:
                        autosave_file.unlink(missing_ok=True)
                else:
                    autosave_file.unlink(missing_ok=True)

        manager = self.window.project_state_manager
        try:
            with manager.suspend_notifications(), OverrideCursor():
                self.window.clear_project()
                projectio.load_project_state(self.window, state)
        except Exception as exc:
            self._show_error("Loading failed", exc)
            self.window.refresh_project_ui()
            return False

        self.window.project_dir = directory
        self.remember_directory(directory)
        self.window.refresh_project_ui()
        manager.mark_loaded(saved_state, recovered=recovered)
        self.window.update_window_title()
        return True

    def save_project(self) -> bool:
        if self.window.project_dir is None:
            return self.save_project_as()
        if not self._save_to(self.window.project_dir):
            return False
        self.window.project_state_manager.mark_saved()
        self.window.project_state_manager.discard_autosave()
        self.window.project_state_manager.discard_unsaved_autosave()
        self.window.update_window_title()
        return True

    def save_project_as(self) -> bool:
        old_project_dir = self.window.project_dir
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self.window,
            f"Save {application_name} project as",
            self.default_dialog_directory(),
        )
        if not directory:
            return False
        directory = Path(directory).resolve()
        if not self._directory_is_empty_enough(directory):
            answer = QtWidgets.QMessageBox.question(
                self.window,
                "Save into existing directory?",
                f"This directory contains files not managed by {application_name}. "
                "Save the project there anyway?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if answer != QtWidgets.QMessageBox.Yes:
                return False
        if not self._save_to(directory):
            return False
        self.window.project_dir = directory
        self.remember_directory(directory)
        self.window.project_state_manager.mark_saved()
        if old_project_dir is not None:
            self.window.project_state_manager.discard_autosave(
                old_project_dir)
        self.window.project_state_manager.discard_autosave(directory)
        self.window.project_state_manager.discard_unsaved_autosave()
        self.window.update_window_title()
        return True

    def _save_to(self, directory: Path) -> bool:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with OverrideCursor():
                projectio.save_project(
                    self.window, directory / PROJECT_FILENAME)
        except Exception as exc:
            self._show_error("Saving failed", exc)
            return False
        return True

    @staticmethod
    def _directory_is_empty_enough(directory: Path) -> bool:
        if not directory.exists():
            return True
        if not directory.is_dir():
            return False
        return all(
            entry.name in {
                PROJECT_FILENAME, PROJECT_AUTOSAVE_FILENAME, ".DS_Store"}
            for entry in directory.iterdir()
        )

    def _show_error(self, title: str, error: Exception) -> None:
        self.window.show_error(title, str(error))
