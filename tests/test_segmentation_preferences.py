"""Persistence boundaries for the next-run method and editing preferences."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from qtpy import QtCore, QtWidgets

from exhale.analysis.controller import AnalysisController
from exhale.data.projectdata import ProjectData
from exhale.project.projectio import export_project_state, load_project_state


@pytest.fixture
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def preference_controls(settings):
    window = SimpleNamespace(
        settings=settings,
        analysisBrushSize=QtWidgets.QSpinBox(),
        analysisOutlineDistance=QtWidgets.QSpinBox(),
        analysisFitOutline=QtWidgets.QCheckBox(),
        analysisProtectSegments=QtWidgets.QCheckBox(),
        analysisDisconnectedParts=QtWidgets.QComboBox(),
    )
    for spin in (window.analysisBrushSize, window.analysisOutlineDistance):
        spin.setRange(1, 1000)
    for key in ("keep", "split", "ask"):
        window.analysisDisconnectedParts.addItem(key, key)
    return SimpleNamespace(window=window)


def test_editing_preferences_round_trip_in_application_settings(app, tmp_path):
    path = str(tmp_path / "preferences.ini")
    control = preference_controls(QtCore.QSettings(path, QtCore.QSettings.IniFormat))
    AnalysisController._load_edit_preferences(control)
    assert control._brush_sizes == {"add": 5, "remove": 5}
    control._brush_sizes = {"add": 11, "remove": 23}
    window = control.window
    window.analysisFitOutline.setChecked(True)
    window.analysisOutlineDistance.setValue(17)
    window.analysisProtectSegments.setChecked(False)
    window.analysisDisconnectedParts.setCurrentIndex(1)
    AnalysisController._save_edit_preferences(control)
    window.settings.sync()

    restored = preference_controls(QtCore.QSettings(path, QtCore.QSettings.IniFormat))
    AnalysisController._load_edit_preferences(restored)
    assert restored._brush_sizes == {"add": 11, "remove": 23}
    assert restored.window.analysisBrushSize.value() == 11
    assert restored.window.analysisOutlineDistance.value() == 17
    assert restored.window.analysisFitOutline.isChecked()
    assert not restored.window.analysisProtectSegments.isChecked()
    assert restored.window.analysisDisconnectedParts.currentData() == "split"
    assert not any("tool" in key for key in window.settings.allKeys())


def test_method_is_project_state_and_restoring_does_not_emit_a_change(app):
    project = ProjectData()
    project.segmentation_method = "monai"
    restored = ProjectData()
    assert not load_project_state(restored, export_project_state(project), open_files=False)
    assert restored.segmentation_method == "monai"
    selector = QtWidgets.QComboBox()
    selector.addItem("StarDist", "stardist")
    selector.addItem("MONAI", "monai")
    changed = Mock()
    selector.currentIndexChanged.connect(changed)
    control = SimpleNamespace(
        window=SimpleNamespace(analysisPipelineComboBox=selector, project_data=restored),
        current_method_id=selector.currentData,
        settings_dialog=Mock(),
    )
    AnalysisController.restore_project_method(control)
    assert selector.currentData() == "monai"
    changed.assert_not_called()
    restored.clear()
    assert restored.segmentation_method is None


def test_unavailable_method_falls_back_without_overwriting_project_selection(app):
    selector = QtWidgets.QComboBox()
    selector.addItem("StarDist", "stardist")
    selector.addItem("MONAI", "monai")
    selector.model().item(1).setEnabled(False)
    project = ProjectData()
    project.segmentation_method = "monai"
    control = SimpleNamespace(
        window=SimpleNamespace(analysisPipelineComboBox=selector, project_data=project),
        current_method_id=selector.currentData,
        settings_dialog=Mock(),
    )
    AnalysisController.restore_project_method(control)
    assert selector.currentData() == "stardist"
    assert project.segmentation_method == "monai"
