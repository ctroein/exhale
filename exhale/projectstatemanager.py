"""Dirty-state tracking and project replacement policy."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

from qtpy import QtCore, QtWidgets

from . import application_name, projectio

PROJECT_AUTOSAVE_KEY = "behavior/autosave_project"
PROJECT_AUTOSAVE_DELAY_MS = 750
PROJECT_AUTOSAVE_FILENAME = "project.autosave.xhp"
UNSAVED_AUTOSAVE_FILENAME = "unsaved-project.autosave.xhp"
_CURRENT_PROJECT = object()


class ProjectStateManager(QtCore.QObject):
    """Compare live project state with the last saved or loaded state."""

    dirtyChanged = QtCore.Signal(bool)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self._baseline = None
        self._dirty = False
        self._notifications_suspended = 0
        self._comparison_pending = False
        self._autosave_timer = QtCore.QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(PROJECT_AUTOSAVE_DELAY_MS)
        self._autosave_timer.timeout.connect(self._autosave_now)

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    @contextmanager
    def suspend_notifications(self):
        self._notifications_suspended += 1
        try:
            yield
        finally:
            self._notifications_suspended -= 1

    def connect_sources(self) -> None:
        """Connect controls that modify serialized project state."""
        w = self.window
        signals = [
            w.loadedFileAlias.textEdited,
            w.elementList.itemChanged,
            w.elementName.editingFinished,
            w.elementNormalizer.currentIndexChanged,
            w.gammaValue.valueChanged,
            w.elementNormalizeMin.valueChanged,
            w.elementNormalizeMax.valueChanged,
            w.elementHistogramPlot.limitsChanged,
            w.addImageButton.clicked,
            w.deleteImageButton.clicked,
            w.imageList.itemChanged,
            w.composeLayoutCB.currentIndexChanged,
            w.composeColors.currentIndexChanged,
            w.composeScalebar.currentIndexChanged,
            w.composeScalebarColor.colorChanged,
            w.composeScalebarBgColor.colorChanged,
            w.composeScalebarBg.toggled,
            w.composeFontsize.valueChanged,
            w.composeDPI.valueChanged,
            w.composePanelLabels.toggled,
            w.composeElementLabels.toggled,
            w.composeElementBorders.toggled,
            w.composeElementLabelsColored.toggled,
            w.composePanelLabelColor.colorChanged,
            w.resolutionValue.valueChanged,
            w.resolutionUnits.currentIndexChanged,
            w.imageHeaderBox.border.valueChanged,
            w.imageHeaderBox.colorChanged,
            w.clusterMinK.valueChanged,
            w.clusterMaxK.valueChanged,
            w.clusterNInit.valueChanged,
            w.nucleiExpansion.valueChanged,
            w.nucleiMinArea.valueChanged,
        ]
        for box in w.imageElementBoxes:
            signals.extend((box.combo.currentIndexChanged, box.colorChanged))
        for signal in signals:
            signal.connect(self.project_changed)

    def project_changed(self, *_unused) -> None:
        if self._notifications_suspended or self._comparison_pending:
            return
        self._comparison_pending = True
        QtCore.QTimer.singleShot(0, self._compare_with_baseline)

    def compare_now(self) -> bool:
        self._comparison_pending = False
        if self._notifications_suspended:
            return self._dirty
        self._set_dirty(self._snapshot() != self._baseline)
        if self._dirty and self.autosave_enabled():
            self._autosave_timer.start()
        else:
            self._autosave_timer.stop()
        return self._dirty

    def _compare_with_baseline(self) -> None:
        self.compare_now()

    def mark_saved(self) -> None:
        self._baseline = self._snapshot()
        self._comparison_pending = False
        self._autosave_timer.stop()
        self._set_dirty(False)

    def mark_loaded(self, saved_state, *, recovered=False) -> None:
        """Use the on-disk saved state as baseline after loading."""
        self._baseline = self._canonical_state(saved_state)
        self._comparison_pending = False
        self._set_dirty(self._snapshot() != self._baseline)
        if recovered and self.autosave_enabled():
            self._autosave_timer.start()

    def prepare_to_leave_project(self, action: str) -> bool:
        """Resolve unsaved changes before replacing or closing a project."""
        if not self.compare_now():
            return True
        answer = QtWidgets.QMessageBox.question(
            self.window,
            "Unsaved project changes",
            f"Save changes before {action}?",
            (QtWidgets.QMessageBox.Save
             | QtWidgets.QMessageBox.Discard
             | QtWidgets.QMessageBox.Cancel),
            QtWidgets.QMessageBox.Save,
        )
        if answer == QtWidgets.QMessageBox.Cancel:
            return False
        if answer == QtWidgets.QMessageBox.Save:
            return self.window.project_manager.save_project()
        self.discard_autosave()
        return True

    def autosave_enabled(self) -> bool:
        return self.window.settings.value(
            PROJECT_AUTOSAVE_KEY, True, type=bool)

    def autosave_setting_changed(self) -> None:
        if self.autosave_enabled() and self._dirty:
            self._autosave_timer.start()
        else:
            self._autosave_timer.stop()

    def autosave_path(self, project_dir=_CURRENT_PROJECT) -> Path:
        if project_dir is _CURRENT_PROJECT:
            project_dir = self.window.project_dir
        if project_dir is not None:
            return Path(project_dir) / PROJECT_AUTOSAVE_FILENAME
        data_dir = Path(QtCore.QStandardPaths.writableLocation(
            QtCore.QStandardPaths.AppDataLocation))
        return data_dir / UNSAVED_AUTOSAVE_FILENAME

    def write_autosave(self) -> Path:
        path = self.autosave_path()
        projectio.save_project_state(
            projectio.export_project_state(self.window), path)
        return path

    def discard_autosave(self, project_dir=None) -> None:
        if project_dir is None:
            self.autosave_path().unlink(missing_ok=True)
        else:
            self.autosave_path(project_dir).unlink(missing_ok=True)

    def discard_unsaved_autosave(self) -> None:
        self.autosave_path(None).unlink(missing_ok=True)

    def _autosave_now(self) -> None:
        if not self._dirty or not self.autosave_enabled():
            return
        try:
            self.write_autosave()
        except Exception as exc:
            self.window.show_error("Autosaving the project failed", str(exc))

    def recover_unsaved_project(self) -> bool:
        path = self.autosave_path(None)
        if not path.is_file():
            return False
        try:
            with path.open(encoding="utf-8") as stream:
                state = json.load(stream)
            projectio.validate_project_state(state)
        except Exception as exc:
            self.window.show_error("Loading recovery data failed", str(exc))
            path.unlink(missing_ok=True)
            return False
        answer = QtWidgets.QMessageBox.question(
            self.window,
            "Recover unsaved project?",
            f"{application_name} found autosaved changes from an unsaved project. "
            "Recover them?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes,
        )
        if answer != QtWidgets.QMessageBox.Yes:
            path.unlink(missing_ok=True)
            return False
        with self.suspend_notifications():
            self.window.clear_project()
            projectio.load_project_state(self.window, state)
            self.window.project_dir = None
            self.window.refresh_project_ui()
        self._baseline = None
        self._set_dirty(True)
        self.window.update_window_title()
        return True

    def _snapshot(self) -> str:
        return self._canonical_state(projectio.export_project_state(self.window))

    @staticmethod
    def _canonical_state(state) -> str:
        return json.dumps(
            state,
            sort_keys=True, separators=(",", ":"), allow_nan=False)

    def _set_dirty(self, dirty: bool) -> None:
        if dirty == self._dirty:
            return
        self._dirty = dirty
        self.dirtyChanged.emit(dirty)
