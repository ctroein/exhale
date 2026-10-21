"""Tests for project-owned matrix plot presentation settings."""

from exhale.data.plotsettings import ELEMENT_CORRELATIONS, SAMPLE_SIMILARITIES
from exhale.data.projectdata import ProjectData
from exhale.project.projectio import export_project_state, load_project_state


def test_matrix_plot_settings_round_trip_independently():
    project = ProjectData()
    project.matrix_plot_settings[ELEMENT_CORRELATIONS].palette = "purple-white-green"
    project.matrix_plot_settings[ELEMENT_CORRELATIONS].decimals = 4
    project.matrix_plot_settings[SAMPLE_SIMILARITIES].palette = "blue-black-red"
    project.matrix_plot_settings[SAMPLE_SIMILARITIES].show_values = False
    state = export_project_state(project)

    restored = ProjectData()
    issues = load_project_state(restored, state, open_files=False)

    assert not issues
    assert restored.matrix_plot_settings[ELEMENT_CORRELATIONS].palette == "purple-white-green"
    assert restored.matrix_plot_settings[ELEMENT_CORRELATIONS].decimals == 4
    assert restored.matrix_plot_settings[SAMPLE_SIMILARITIES].palette == "blue-black-red"
    assert not restored.matrix_plot_settings[SAMPLE_SIMILARITIES].show_values


def test_invalid_matrix_plot_settings_are_reset_without_blocking_project_load():
    state = export_project_state(ProjectData())
    state["matrix_plots"][ELEMENT_CORRELATIONS]["palette"] = "unknown"

    restored = ProjectData()
    issues = load_project_state(restored, state, open_files=False)

    assert len(issues) == 1
    assert "Element Correlations" in issues[0]
    assert restored.matrix_plot_settings[ELEMENT_CORRELATIONS].palette == "blue-white-red"
