"""Tests for correlation-matrix export format routing."""

import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from qtpy import QtWidgets

from exhale.analysis.correlation_controller import CorrelationController
from exhale.analysis.matrixplots import MATRIX_PALETTES, correlation_matrix_spec
from exhale.data.plotsettings import ELEMENT_CORRELATIONS
from exhale.data.projectdata import ProjectData

_APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _outcome():
    return SimpleNamespace(
        adjustments=(),
        layout=SimpleNamespace(width_mm=100.0, height_mm=100.0),
    )


def _controller(filename):
    project_data = ProjectData()
    window = SimpleNamespace(
        project_data=project_data,
        project_manager=SimpleNamespace(default_export_directory=Mock(return_value="/exports")),
        project_state_manager=SimpleNamespace(project_changed=Mock()),
        askFileName=Mock(return_value=filename),
    )
    controller = CorrelationController.__new__(CorrelationController)
    controller.window = window
    controller._show_input_error = Mock()
    result = SimpleNamespace(
        values=np.array([[1.0, 0.5], [0.5, 1.0]]),
        labels=("Copper", "Zinc"),
    )
    plot_item = Mock()
    matrix = SimpleNamespace(
        result=result,
        reload_settings=Mock(),
        make_spec=Mock(
            side_effect=lambda: correlation_matrix_spec(
                result.values,
                result.labels,
                palette=project_data.matrix_plot_settings[ELEMENT_CORRELATIONS].palette,
            )
        ),
        palettes=MATRIX_PALETTES,
        plot=SimpleNamespace(current_plot_item=Mock(return_value=plot_item)),
    )
    return controller, matrix, plot_item


@patch("exhale.analysis.correlation_controller.MatrixExportDialog")
def test_pdf_export_uses_dedicated_matrix_renderer(dialog_class):
    controller, matrix, _plot_item = _controller("/exports/matrix.pdf")
    dialog_class.return_value.exec.return_value = QtWidgets.QDialog.DialogCode.Accepted

    with patch("exhale.analysis.correlation_controller.export_matrix_pdf") as export_pdf:
        export_pdf.return_value = _outcome()
        controller.export_matrix(matrix, ELEMENT_CORRELATIONS, "element-correlations.pdf")

    assert _APP is not None
    export_pdf.assert_called_once()
    assert export_pdf.call_args.args[-1] == "/exports/matrix.pdf"
    matrix.reload_settings.assert_called_once_with()
    controller.window.project_state_manager.project_changed.assert_called_once_with()


@patch("exhale.analysis.correlation_controller.MatrixExportDialog")
def test_svg_export_uses_publication_renderer(dialog_class):
    controller, matrix, _plot_item = _controller("/exports/matrix.svg")
    dialog_class.return_value.exec.return_value = QtWidgets.QDialog.DialogCode.Accepted

    with patch("exhale.analysis.correlation_controller.export_matrix_svg") as export_svg:
        export_svg.return_value = _outcome()
        controller.export_matrix(matrix, ELEMENT_CORRELATIONS, "element-correlations.pdf")

    export_svg.assert_called_once()
    assert export_svg.call_args.args[-1] == "/exports/matrix.svg"


@patch("exhale.analysis.correlation_controller.MatrixExportDialog")
def test_png_export_uses_publication_renderer(dialog_class):
    controller, matrix, _plot_item = _controller("/exports/matrix.png")
    dialog_class.return_value.exec.return_value = QtWidgets.QDialog.DialogCode.Accepted

    with patch("exhale.analysis.correlation_controller.export_matrix_png") as export_png:
        export_png.return_value = _outcome()
        controller.export_matrix(matrix, ELEMENT_CORRELATIONS, "element-correlations.pdf")

    export_png.assert_called_once()
    assert export_png.call_args.args[-1] == "/exports/matrix.png"


@patch("exhale.analysis.correlation_controller.MatrixExportDialog")
def test_cancelled_matrix_export_does_not_change_or_export(dialog_class):
    controller, matrix, _plot_item = _controller("/exports/matrix.pdf")
    dialog_class.return_value.exec.return_value = QtWidgets.QDialog.DialogCode.Rejected

    with patch("exhale.analysis.correlation_controller.export_matrix_pdf") as export_pdf:
        controller.export_matrix(matrix, ELEMENT_CORRELATIONS, "element-correlations.pdf")

    export_pdf.assert_not_called()
    matrix.reload_settings.assert_not_called()
    controller.window.askFileName.assert_not_called()
