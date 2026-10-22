"""Tests for vector correlation-matrix PDF export."""

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from qtpy import QtWidgets

from exhale.analysis.matrixpdf import (
    POINTS_PER_MM,
    export_matrix_pdf,
    export_matrix_png,
    export_matrix_svg,
    matrix_pdf_layout,
    prepare_matrix_export,
)
from exhale.analysis.matrixplots import correlation_matrix_spec
from exhale.data.plotsettings import MatrixPlotSettings, MatrixPublicationSettings

_APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _spec():
    return correlation_matrix_spec(
        np.array([[1.0, -0.25], [-0.25, np.nan]]),
        ("Copper", "Zinc"),
        decimals=2,
    )


def test_automatic_dimensions_fit_the_matrix_and_color_bar():
    publication = MatrixPublicationSettings(font_size=9.0)
    layout = matrix_pdf_layout(_spec(), publication, MatrixPlotSettings())

    assert _APP is not None
    assert layout.text.page_padding == 0.0
    assert layout.matrix.width() == pytest.approx(2 * layout.cell_size)
    assert layout.color_bar is not None
    assert layout.color_bar.top() == pytest.approx(layout.matrix.top())
    assert layout.color_bar.bottom() == pytest.approx(layout.matrix.bottom())
    assert layout.page_width > layout.matrix.right()
    assert layout.page_height > layout.matrix.bottom()


def test_one_fixed_dimension_drives_cell_size_and_other_dimension_is_automatic():
    settings = MatrixPlotSettings(width_mm=100.0, height_mm=None)
    layout = matrix_pdf_layout(_spec(), MatrixPublicationSettings(), settings)

    assert layout.page_width == pytest.approx(100.0 * POINTS_PER_MM)
    assert layout.page_height > 0


def test_fixed_height_drives_cell_size_and_width_is_automatic():
    settings = MatrixPlotSettings(width_mm=None, height_mm=100.0)
    layout = matrix_pdf_layout(_spec(), MatrixPublicationSettings(), settings)

    assert layout.page_width > 0
    assert layout.page_height == pytest.approx(100.0 * POINTS_PER_MM)


def test_two_fixed_dimensions_are_preserved_without_distorting_cells():
    settings = MatrixPlotSettings(width_mm=120.0, height_mm=100.0)
    layout = matrix_pdf_layout(_spec(), MatrixPublicationSettings(), settings)

    assert layout.width_mm == pytest.approx(120.0)
    assert layout.height_mm == pytest.approx(100.0)
    assert layout.matrix.width() == pytest.approx(layout.matrix.height())


@pytest.mark.parametrize("position", ["left", "right", "hidden"])
@pytest.mark.parametrize("show_values", [False, True])
def test_layout_combinations_keep_optional_color_bar_aligned(position, show_values):
    spec = correlation_matrix_spec(
        np.eye(4),
        ("Aluminium", "Calcium", "Manganese", "Phosphorus"),
        show_values=show_values,
        decimals=4,
    )
    settings = MatrixPlotSettings(color_bar_position=position)

    layout = matrix_pdf_layout(spec, MatrixPublicationSettings(font_size=11.0), settings)

    assert layout.cell_size > 0
    assert layout.matrix.right() <= layout.page_width
    assert layout.matrix.bottom() <= layout.page_height
    if position == "hidden":
        assert layout.color_bar is None
    else:
        assert layout.color_bar is not None
        assert layout.color_bar.top() == pytest.approx(layout.matrix.top())
        assert layout.color_bar.bottom() == pytest.approx(layout.matrix.bottom())


def test_too_small_fixed_figure_reports_the_layout_problem():
    settings = MatrixPlotSettings(width_mm=10.0, height_mm=10.0)

    with pytest.raises(ValueError, match="too small.*current font size"):
        matrix_pdf_layout(_spec(), MatrixPublicationSettings(font_size=12.0), settings)


def test_pdf_export_writes_a_pdf_with_vector_content(tmp_path):
    filename = tmp_path / "matrix.pdf"

    export_matrix_pdf(
        _spec(),
        MatrixPublicationSettings(font_family="DejaVu Sans", font_size=9.0),
        MatrixPlotSettings(color_bar_position="left"),
        str(filename),
    )

    contents = filename.read_bytes()
    assert contents.startswith(b"%PDF-")
    assert len(contents) > 1000


def test_png_export_uses_physical_size_and_dpi(tmp_path):
    filename = tmp_path / "matrix.png"
    settings = MatrixPlotSettings(width_mm=100.0, dpi=300)

    outcome = export_matrix_png(
        _spec(), MatrixPublicationSettings(font_size=9.0), settings, str(filename)
    )

    image = QtWidgets.QApplication.instance()
    assert image is not None
    from qtpy import QtGui

    rendered = QtGui.QImage(str(filename))
    assert rendered.width() == round(outcome.layout.page_width * settings.dpi / 72.0)
    assert rendered.height() == round(outcome.layout.page_height * settings.dpi / 72.0)


def test_png_cell_fills_have_no_antialiased_seams(tmp_path):
    from qtpy import QtGui

    filename = tmp_path / "matrix.png"
    spec = correlation_matrix_spec(
        np.array([[-1.0, 1.0], [1.0, -1.0]]),
        ("Cu", "Zn"),
        show_values=False,
    )
    settings = MatrixPlotSettings(width_mm=100.0, height_mm=80.0, dpi=144)

    outcome = export_matrix_png(
        spec, MatrixPublicationSettings(font_size=9.0), settings, str(filename)
    )

    rendered = QtGui.QImage(str(filename))
    scale = min(
        rendered.width() / outcome.layout.page_width,
        rendered.height() / outcome.layout.page_height,
    )
    matrix = outcome.layout.matrix
    colors = {
        QtGui.QColor(*spec.color_stops[0].color).name(),
        QtGui.QColor(*spec.color_stops[-1].color).name(),
    }
    rendered_colors = {
        rendered.pixelColor(x, y).name()
        for y in range(round(matrix.top() * scale) + 2, round(matrix.bottom() * scale) - 2)
        for x in range(round(matrix.left() * scale) + 2, round(matrix.right() * scale) - 2)
    }
    assert rendered_colors <= colors


def test_svg_export_contains_vector_shapes_without_embedded_image(tmp_path):
    filename = tmp_path / "matrix.svg"
    settings = MatrixPlotSettings(width_mm=100.0, height_mm=80.0, dpi=144)

    outcome = export_matrix_svg(
        _spec(), MatrixPublicationSettings(font_size=9.0), settings, str(filename)
    )

    contents = filename.read_text(encoding="utf-8")
    assert "<svg" in contents
    assert "<image" not in contents
    root_size = re.search(r'<svg width="(\d+)px" height="(\d+)px"', contents)
    assert root_size is not None
    assert tuple(map(int, root_size.groups())) == (
        round(outcome.layout.page_width * settings.dpi / 72.0),
        round(outcome.layout.page_height * settings.dpi / 72.0),
    )


def test_export_fitting_reduces_precision_without_changing_settings():
    settings = MatrixPlotSettings(width_mm=45.0, height_mm=45.0, decimals=6)
    publication = MatrixPublicationSettings(font_size=12.0)
    spec = correlation_matrix_spec(np.eye(2), ("Cu", "Zn"), decimals=6)

    fitted_spec, fitted_publication, outcome = prepare_matrix_export(spec, publication, settings)

    assert fitted_spec.decimals < spec.decimals
    assert fitted_publication.font_size <= publication.font_size
    assert outcome.adjustments
    assert settings.decimals == 6
    assert publication.font_size == 12.0
