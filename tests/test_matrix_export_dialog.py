"""Tests for publication matrix export controls."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from qtpy import QtWidgets

from exhale.analysis.matrix_export_dialog import MatrixExportDialog
from exhale.analysis.matrixplots import correlation_matrix_spec
from exhale.data.plotsettings import MatrixPlotSettings, MatrixPublicationSettings

_APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _spec():
    return correlation_matrix_spec(np.eye(2), ("Copper", "Zinc"))


def test_matrix_export_dialog_commits_fixed_and_automatic_dimensions():
    publication = MatrixPublicationSettings(font_size=10.0)
    plot = MatrixPlotSettings(width_mm=None, height_mm=180.0)
    dialog = MatrixExportDialog(publication, plot, _spec())

    assert dialog.automaticWidth.isChecked()
    assert not dialog.widthMm.isEnabled()
    assert not dialog.automaticHeight.isChecked()
    assert dialog.heightMm.value() == 180.0

    dialog.automaticWidth.setChecked(False)
    dialog.widthMm.setValue(125.5)
    dialog.automaticHeight.setChecked(True)
    dialog.fontSize.setValue(9.5)
    dialog.palette.setCurrentIndex(dialog.palette.findData("purple-white-green"))
    dialog.colorBarPosition.setCurrentIndex(dialog.colorBarPosition.findData("left"))
    dialog.showValues.setChecked(False)
    dialog.cellBorders.setChecked(True)
    dialog.dpi.setValue(600)
    dialog.accept()

    assert _APP is not None
    assert publication.font_size == 9.5
    assert plot.width_mm == 125.5
    assert plot.height_mm is None
    assert plot.palette == "purple-white-green"
    assert plot.color_bar_position == "left"
    assert not plot.show_values
    assert plot.cell_borders
    assert plot.dpi == 600


def test_matrix_export_dialog_rejection_does_not_change_settings():
    publication = MatrixPublicationSettings(font_family="DejaVu Sans", font_size=11.0)
    plot = MatrixPlotSettings(width_mm=140.0, height_mm=None)
    dialog = MatrixExportDialog(publication, plot, _spec())

    dialog.fontSize.setValue(20.0)
    dialog.automaticWidth.setChecked(True)
    dialog.reject()

    assert publication == MatrixPublicationSettings(font_family="DejaVu Sans", font_size=11.0)
    assert plot == MatrixPlotSettings(width_mm=140.0, height_mm=None)


def test_matrix_export_dialog_prevents_dimensions_below_current_minimum():
    dialog = MatrixExportDialog(
        MatrixPublicationSettings(font_size=12.0), MatrixPlotSettings(), _spec()
    )

    width_minimum = dialog.widthMm.minimum()
    dialog.widthMm.setValue(1.0)

    assert dialog.widthMm.value() == width_minimum
    assert width_minimum > 10.0
