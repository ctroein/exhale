"""Tests for project-owned matrix plot presentation settings."""

from exhale.data.plotsettings import ELEMENT_CORRELATIONS, SAMPLE_SIMILARITIES
from exhale.data.projectdata import ProjectData
from exhale.project.projectio import export_project_state, load_project_state


def test_matrix_plot_settings_round_trip_independently():
    project = ProjectData()
    project.matrix_plot_settings[ELEMENT_CORRELATIONS].palette = "linnaea"
    project.matrix_plot_settings[ELEMENT_CORRELATIONS].decimals = 4
    project.matrix_plot_settings[ELEMENT_CORRELATIONS].width_mm = 125.5
    project.matrix_plot_settings[ELEMENT_CORRELATIONS].cell_borders = True
    project.matrix_plot_settings[ELEMENT_CORRELATIONS].dpi = 600
    project.matrix_plot_settings[SAMPLE_SIMILARITIES].palette = "nightlife"
    project.matrix_plot_settings[SAMPLE_SIMILARITIES].show_values = False
    project.matrix_plot_settings[SAMPLE_SIMILARITIES].height_mm = 210.0
    project.matrix_publication_settings.font_family = "Liberation Sans"
    project.matrix_publication_settings.font_size = 9.5
    state = export_project_state(project)

    restored = ProjectData()
    issues = load_project_state(restored, state, open_files=False)

    assert not issues
    assert restored.matrix_plot_settings[ELEMENT_CORRELATIONS].palette == "linnaea"
    assert restored.matrix_plot_settings[ELEMENT_CORRELATIONS].decimals == 4
    assert restored.matrix_plot_settings[ELEMENT_CORRELATIONS].width_mm == 125.5
    assert restored.matrix_plot_settings[ELEMENT_CORRELATIONS].height_mm is None
    assert restored.matrix_plot_settings[ELEMENT_CORRELATIONS].cell_borders
    assert restored.matrix_plot_settings[ELEMENT_CORRELATIONS].dpi == 600
    assert restored.matrix_plot_settings[SAMPLE_SIMILARITIES].palette == "nightlife"
    assert not restored.matrix_plot_settings[SAMPLE_SIMILARITIES].show_values
    assert restored.matrix_plot_settings[SAMPLE_SIMILARITIES].height_mm == 210.0
    assert restored.matrix_publication_settings.font_family == "Liberation Sans"
    assert restored.matrix_publication_settings.font_size == 9.5


def test_invalid_matrix_plot_settings_are_reset_without_blocking_project_load():
    state = export_project_state(ProjectData())
    state["matrix_plots"][ELEMENT_CORRELATIONS]["palette"] = "unknown"

    restored = ProjectData()
    issues = load_project_state(restored, state, open_files=False)

    assert len(issues) == 1
    assert "Element Correlations" in issues[0]
    assert restored.matrix_plot_settings[ELEMENT_CORRELATIONS].palette == "magnolia"


def test_invalid_matrix_publication_settings_are_reset_without_blocking_project_load():
    state = export_project_state(ProjectData())
    state["matrix_publication"]["font_size"] = 1000

    restored = ProjectData()
    issues = load_project_state(restored, state, open_files=False)

    assert issues == [
        "Matrix publication settings were reset: Matrix font size must be between 4 and 72 pt"
    ]
    assert restored.matrix_publication_settings.font_family == ""
    assert restored.matrix_publication_settings.font_size == 10.0
