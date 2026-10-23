"""Focused geometry tests for matrix plot interactions."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from qtpy import QtCore, QtGui, QtWidgets

from exhale.analysis.correlationwidgets import CorrelationPlotWidget
from exhale.analysis.matrixplots import correlation_matrix_spec, matrix_text_layout

_APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


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
    cell_size = view_box.sceneBoundingRect().width() / view_box.viewRect().width()
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
    original_cell_size = view_box.sceneBoundingRect().width() / view_box.viewRect().width()

    widget.set_matrix_spec(
        correlation_matrix_spec(values, ("A", "B", "C", "D"), show_values=True, decimals=3)
    )
    widget.set_matrix_spec(
        correlation_matrix_spec(values, ("A", "B", "C", "D"), show_values=True, decimals=2)
    )

    center = view_box.viewRect().center()
    content_center = widget._matrix_content_bounds.center()
    final_cell_size = view_box.sceneBoundingRect().width() / view_box.viewRect().width()
    assert center.x() == pytest.approx(content_center.x(), abs=1e-9)
    assert center.y() == pytest.approx(content_center.y(), abs=1e-9)
    assert final_cell_size == pytest.approx(original_cell_size, abs=0.02)
    widget.close()


def test_decimal_change_preserves_cell_size_and_updates_padding():
    values = np.eye(4)
    labels = ("A", "B", "C", "D")
    widget = CorrelationPlotWidget()
    widget.resize(800, 600)
    widget.show()
    _APP.processEvents()
    widget.set_matrix_spec(correlation_matrix_spec(values, labels, show_values=True, decimals=2))
    view_box = widget.matrix_plot.getViewBox()
    view_box.scaleBy((0.8, 0.8), QtCore.QPointF(1.5, 1.5))
    widget._matrix_view_range_changed()
    selected_cell_size = view_box.sceneBoundingRect().width() / view_box.viewRect().width()
    original_padding = widget._matrix_cell_padding

    widget.set_matrix_spec(correlation_matrix_spec(values, labels, show_values=True, decimals=3))
    decimal_cell_size = view_box.sceneBoundingRect().width() / view_box.viewRect().width()
    assert decimal_cell_size == pytest.approx(selected_cell_size, abs=0.02)
    assert widget._matrix_cell_padding < original_padding
    decimal_padding = widget._matrix_cell_padding

    larger = np.eye(5)
    widget.set_matrix_spec(
        correlation_matrix_spec(
            larger,
            (*labels, "E"),
            show_values=True,
            decimals=3,
        )
    )
    assert widget._matrix_cell_padding == pytest.approx(decimal_padding)
    widget.close()
