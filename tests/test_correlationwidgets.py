"""Focused geometry tests for matrix plot interactions."""

import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from qtpy import QtCore, QtGui, QtWidgets

from exhale.analysis.correlationwidgets import CorrelationMatrixView, CorrelationPlotWidget
from exhale.analysis.matrixplots import (
    correlation_matrix_spec,
    distance_matrix_spec,
    matrix_text_layout,
)
from exhale.data.plotsettings import MatrixPlotSettings

_APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_matrix_view_does_not_rebuild_an_unchanged_result():
    host = QtWidgets.QWidget()
    show_values = QtWidgets.QCheckBox()
    decimals = QtWidgets.QSpinBox()
    decimals_label = QtWidgets.QLabel()
    copy_button = QtWidgets.QPushButton()
    palette = QtWidgets.QComboBox()
    view = CorrelationMatrixView(
        host,
        show_values,
        decimals,
        decimals_label,
        copy_button,
        palette,
        MatrixPlotSettings(),
    )
    result = SimpleNamespace(values=np.eye(2), labels=("A", "B"))
    update = Mock(wraps=view._update_plot_spec)
    view._update_plot_spec = update

    view.set_result(result)
    view.set_result(result)

    update.assert_called_once_with()
    decimals.setValue(decimals.value() + 1)
    assert update.call_count == 2
    host.close()


def _wheel(widget, delta):
    viewport = widget.matrix_plot.viewport()
    position = QtCore.QPointF(viewport.rect().center())
    event = QtGui.QWheelEvent(
        position,
        widget.matrix_plot.mapToGlobal(position.toPoint()),
        QtCore.QPoint(),
        QtCore.QPoint(0, delta),
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
        QtCore.Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QtWidgets.QApplication.sendEvent(viewport, event)
    _APP.processEvents()


def test_initial_matrix_uses_default_one_digit_padding_when_it_fits():
    values = np.eye(4)
    widget = CorrelationPlotWidget()
    widget.resize(800, 600)
    widget.show()
    _APP.processEvents()
    spec = correlation_matrix_spec(
        values,
        ("A", "B", "C", "D"),
        show_values=True,
        decimals=2,
    )

    widget.set_matrix_spec(spec)

    metrics = QtGui.QFontMetrics(QtWidgets.QApplication.font())
    text = matrix_text_layout(spec, metrics.height(), metrics.horizontalAdvance)
    view_box = widget.matrix_plot.getViewBox()
    cell_size = view_box.geometry().width() / view_box.viewRect().width()
    assert cell_size == pytest.approx(text.default_cell, abs=0.02)
    before = view_box.viewRect().width()
    _wheel(widget, 120)
    assert view_box.viewRect().width() < before
    widget.close()


def test_wheel_zoom_keeps_current_view_center_for_oversized_matrix():
    size = 20
    widget = CorrelationPlotWidget()
    widget.resize(500, 400)
    widget.show()
    _APP.processEvents()
    widget.set_matrix_spec(
        correlation_matrix_spec(
            np.eye(size),
            tuple(str(index) for index in range(size)),
            show_values=True,
            decimals=2,
        )
    )
    view_box = widget.matrix_plot.getViewBox()
    assert view_box.viewRect().width() < size
    view_box.translateBy(x=2.0)
    before = view_box.viewRect()
    assert before.center().x() != pytest.approx((size - 1) / 2)

    _wheel(widget, 120)

    after = view_box.viewRect()
    assert after.width() < before.width()
    assert after.center().x() == pytest.approx(before.center().x(), abs=1e-9)
    assert after.center().y() == pytest.approx(before.center().y(), abs=1e-9)
    widget.close()


def test_zooming_out_to_minimum_cell_size_does_not_shift_matrix():
    size = 8
    widget = CorrelationPlotWidget()
    widget.resize(800, 600)
    widget.show()
    _APP.processEvents()
    widget.set_matrix_spec(
        correlation_matrix_spec(
            np.eye(size),
            tuple(f"Element {index}" for index in range(size)),
            show_values=False,
            decimals=2,
        )
    )
    view_box = widget.matrix_plot.getViewBox()

    previous_offset = None
    for step in range(20):
        matrix_scene = widget.image.mapRectToScene(widget.image.boundingRect())
        offset = matrix_scene.center() - view_box.geometry().center()
        if previous_offset is not None and step >= 10:
            assert abs(offset.x() - previous_offset.x()) < 2.0
            assert abs(offset.y() - previous_offset.y()) < 2.0
        previous_offset = offset
        _wheel(widget, -30)

    widget.close()


def test_oversized_column_labels_are_within_pannable_bounds():
    size = 8
    widget = CorrelationPlotWidget()
    widget.resize(500, 300)
    widget.show()
    _APP.processEvents()
    widget.set_matrix_spec(
        correlation_matrix_spec(
            np.eye(size),
            tuple(f"Very long element label {index}" for index in range(size)),
            show_values=True,
            decimals=2,
        )
    )
    view_box = widget.matrix_plot.getViewBox()
    assert widget._matrix_content_bounds.height() > view_box.viewRect().height()

    view_box.translateBy(y=100.0)
    widget._matrix_view_range_changed()

    assert view_box.viewRect().bottom() == pytest.approx(
        widget._matrix_content_bounds.bottom(), abs=1e-9
    )
    widget.close()


def test_complete_matrix_figure_is_centered_when_it_fits():
    size = 4
    widget = CorrelationPlotWidget()
    widget.resize(1200, 800)
    widget.show()
    _APP.processEvents()
    widget.set_matrix_spec(
        correlation_matrix_spec(
            np.eye(size),
            tuple(f"Long element label {index}" for index in range(size)),
            show_values=True,
            decimals=2,
        )
    )
    view = widget.matrix_plot.getViewBox().viewRect()
    content = widget._matrix_content_bounds

    assert view.width() >= content.width()
    assert view.height() >= content.height()
    assert view.center().x() == pytest.approx(content.center().x(), abs=1e-9)
    assert view.center().y() == pytest.approx(content.center().y(), abs=1e-9)
    widget.close()


def test_decimal_round_trip_keeps_complete_figure_centered():
    values = np.eye(4)
    widget = CorrelationPlotWidget()
    widget.resize(800, 600)
    widget.show()
    _APP.processEvents()

    widget.set_matrix_spec(
        correlation_matrix_spec(values, ("A", "B", "C", "D"), show_values=True, decimals=2)
    )
    view_box = widget.matrix_plot.getViewBox()
    matrix_center = QtCore.QPointF(1.5, 1.5)
    view_box.scaleBy((0.8, 0.8), matrix_center)
    widget._matrix_view_range_changed()
    original_cell_size = view_box.geometry().width() / view_box.viewRect().width()

    widget.set_matrix_spec(
        correlation_matrix_spec(values, ("A", "B", "C", "D"), show_values=True, decimals=3)
    )
    widget.set_matrix_spec(
        correlation_matrix_spec(values, ("A", "B", "C", "D"), show_values=True, decimals=2)
    )

    center = view_box.viewRect().center()
    content_center = widget._matrix_content_bounds.center()
    final_cell_size = view_box.geometry().width() / view_box.viewRect().width()
    assert center.x() == pytest.approx(content_center.x(), abs=1e-9)
    assert center.y() == pytest.approx(content_center.y(), abs=1e-9)
    assert final_cell_size == pytest.approx(original_cell_size, abs=0.02)
    widget.close()


def test_palette_change_cannot_corrupt_cell_size_used_by_decimal_change():
    values = np.eye(4)
    labels = ("A", "B", "C", "D")
    widget = CorrelationPlotWidget()
    widget.resize(800, 600)
    widget.show()
    _APP.processEvents()
    widget.set_matrix_spec(
        correlation_matrix_spec(values, labels, palette="magnolia", show_values=True, decimals=2)
    )
    view_box = widget.matrix_plot.getViewBox()
    view_box.scaleBy((0.8, 0.8), QtCore.QPointF(1.5, 1.5))
    widget._matrix_view_range_changed()
    selected_cell_size = view_box.geometry().width() / view_box.viewRect().width()

    widget.set_matrix_spec(
        correlation_matrix_spec(values, labels, palette="linnaea", show_values=True, decimals=2)
    )
    widget.set_matrix_spec(
        correlation_matrix_spec(values, labels, palette="linnaea", show_values=True, decimals=3)
    )

    final_cell_size = view_box.geometry().width() / view_box.viewRect().width()
    assert final_cell_size == pytest.approx(selected_cell_size, abs=0.02)
    assert widget._matrix_cell_size == pytest.approx(selected_cell_size, abs=0.02)
    widget.close()


def test_decimal_and_data_changes_preserve_cell_size():
    values = np.eye(4) * 12
    labels = ("A", "B", "C", "D")
    widget = CorrelationPlotWidget()
    widget.resize(800, 600)
    widget.show()
    _APP.processEvents()
    widget.set_matrix_spec(
        distance_matrix_spec(values, labels, units="µm", show_values=True, decimals=2)
    )
    view_box = widget.matrix_plot.getViewBox()
    view_box.scaleBy((0.6, 0.6), QtCore.QPointF(1.5, 1.5))
    widget._matrix_view_range_changed()
    selected_cell_size = view_box.geometry().width() / view_box.viewRect().width()
    assert widget._matrix_cell_size == pytest.approx(selected_cell_size, abs=0.02)

    widget.set_matrix_spec(
        distance_matrix_spec(values, labels, units="µm", show_values=True, decimals=3)
    )
    decimal_cell_size = view_box.geometry().width() / view_box.viewRect().width()
    assert decimal_cell_size == pytest.approx(selected_cell_size, abs=0.02)

    larger = np.eye(5) * 100
    widget.set_matrix_spec(
        distance_matrix_spec(
            larger,
            (*labels, "E"),
            units="µm",
            show_values=True,
            decimals=3,
        )
    )
    data_cell_size = view_box.geometry().width() / view_box.viewRect().width()
    assert data_cell_size == pytest.approx(selected_cell_size, abs=0.02)
    assert widget._matrix_cell_size == pytest.approx(selected_cell_size, abs=0.02)
    widget.close()


def test_value_and_secondary_text_changes_preserve_cell_size_within_limits():
    values = np.asarray(((12.0, 34.0), (56.0, 78.0)))
    deviations = np.ones_like(values)
    labels = ("A", "B")
    widget = CorrelationPlotWidget()
    widget.resize(800, 600)
    widget.show()
    _APP.processEvents()
    widget.set_matrix_spec(
        distance_matrix_spec(
            values,
            labels,
            units="µm",
            standard_deviations=deviations,
            show_values=True,
            show_secondary=False,
        )
    )
    view_box = widget.matrix_plot.getViewBox()
    selected_cell_size = view_box.geometry().width() / view_box.viewRect().width()

    for show_values, show_secondary in ((False, False), (True, True), (True, False)):
        widget.set_matrix_spec(
            distance_matrix_spec(
                values,
                labels,
                units="µm",
                standard_deviations=deviations,
                show_values=show_values,
                show_secondary=show_secondary,
            )
        )
        cell_size = view_box.geometry().width() / view_box.viewRect().width()
        assert cell_size == pytest.approx(selected_cell_size, abs=0.02)
    widget.close()


def test_matrix_zoom_allows_six_digits_of_padding():
    values = np.eye(2)
    widget = CorrelationPlotWidget()
    widget.resize(800, 600)
    widget.show()
    _APP.processEvents()
    spec = correlation_matrix_spec(values, ("A", "B"), show_values=True, decimals=2)
    widget.set_matrix_spec(spec)

    metrics = QtGui.QFontMetrics(QtWidgets.QApplication.font())
    text = matrix_text_layout(spec, metrics.height(), metrics.horizontalAdvance)
    minimum_cell, maximum_cell = widget._matrix_cell_limits(text, spec)
    assert maximum_cell - minimum_cell == pytest.approx(6 * text.digit_width)
    widget.close()


def test_equal_matrix_specs_do_not_refit_or_rebuild_labels():
    widget = CorrelationPlotWidget()
    widget.resize(900, 700)
    widget.show()
    _APP.processEvents()
    values = np.array(((1.0, np.nan), (2.0, 3.0)))
    secondary = np.array(((0.0, np.nan), (0.5, 0.7)))
    widget.set_matrix_spec(
        distance_matrix_spec(values, ("A", "B"), units="nm", standard_deviations=secondary)
    )
    _APP.processEvents()
    fit = Mock(wraps=widget._fit_matrix)
    labels = Mock(wraps=widget._rebuild_axis_labels)
    widget._fit_matrix = fit
    widget._rebuild_axis_labels = labels
    original_cell = widget._matrix_cell_size
    original_range = QtCore.QRectF(widget.matrix_plot.getViewBox().viewRect())
    for _ in range(20):
        widget.set_matrix_spec(
            distance_matrix_spec(
                values.copy(), ("A", "B"), units="nm", standard_deviations=secondary.copy()
            )
        )
        _APP.processEvents()
    fit.assert_not_called()
    labels.assert_not_called()
    assert widget._matrix_cell_size == original_cell
    assert widget.matrix_plot.getViewBox().viewRect() == original_range
    widget.close()


def test_repeated_matrix_fits_preserve_fractional_cell_size():
    widget = CorrelationPlotWidget()
    widget.resize(900, 700)
    widget.show()
    _APP.processEvents()
    widget.set_matrix_spec(distance_matrix_spec(np.ones((4, 4)), ("A", "B", "C", "D"), units="nm"))
    _APP.processEvents()
    for cell in (widget._matrix_cell_size, widget._matrix_cell_size + 3.25):
        widget._matrix_cell_size = cell
        for _ in range(20):
            widget._reset_matrix_view = True
            widget._fit_matrix()
            _APP.processEvents()
            assert widget._matrix_cell_size == pytest.approx(cell, abs=1e-9)
    widget.close()


def test_initial_matrix_keeps_default_padding_when_scrolling_is_needed():
    widget = CorrelationPlotWidget()
    widget.resize(500, 400)
    widget.show()
    _APP.processEvents()
    spec = correlation_matrix_spec(np.eye(12), tuple(str(index) for index in range(12)), decimals=2)
    widget.set_matrix_spec(spec)
    _APP.processEvents()
    metrics = QtGui.QFontMetrics(QtWidgets.QApplication.font())
    text = matrix_text_layout(spec, metrics.height(), metrics.horizontalAdvance)
    assert widget._matrix_cell_size == pytest.approx(text.default_cell, abs=1e-9)
    assert widget.matrix_plot.getViewBox().viewRect().width() < 12
    widget.close()


def test_density_one_point_reference_maps_to_ten_percent_after_smoothing():
    from exhale.analysis.correlations import DensityGrid

    widget = CorrelationPlotWidget()
    for bins in (50, 100, 500):
        edges = np.linspace(0.0, 0.01, bins + 1)
        area = (edges[1] - edges[0]) ** 2
        density = np.zeros((bins, bins))
        density[bins // 2, bins // 2] = 1.0 / area
        widget.show_density(DensityGrid(edges, edges, density, count=1), "A", "B")
        lower, upper = widget.density_image.getLevels()
        peak = widget.density_image.image.max()
        assert (peak - lower) / (upper - lower) == pytest.approx(0.1)
        assert widget.density_color_bar.levels() == pytest.approx((lower, upper))
    widget.close()
