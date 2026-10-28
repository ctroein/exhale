"""Edit project-owned settings for publication matrix exports."""

from __future__ import annotations

import math
from dataclasses import replace

from qtpy import QtGui, QtWidgets

from ..data.plotsettings import MatrixPlotSettings, MatrixPublicationSettings
from .matrix_export_dialog_ui import Ui_MatrixExportDialog
from .matrixpdf import minimum_matrix_dimensions_mm
from .matrixplots import MATRIX_PALETTES, MatrixPlotSpec


class MatrixExportDialog(QtWidgets.QDialog, Ui_MatrixExportDialog):
    """Edit shared typography and settings for one matrix plot type."""

    def __init__(
        self,
        publication_settings: MatrixPublicationSettings,
        plot_settings: MatrixPlotSettings,
        spec: MatrixPlotSpec,
        parent=None,
        *,
        palettes=MATRIX_PALETTES,
        fixed_decimals: int | None = None,
    ):
        super().__init__(parent)
        self.setupUi(self)
        self._publication_settings = publication_settings
        self._plot_settings = plot_settings
        self._spec = spec
        self._fixed_decimals = fixed_decimals

        for palette in palettes:
            self.palette.addItem(palette.name, palette.key)
        for name, key in (("Right", "right"), ("Left", "left"), ("Hidden", "hidden")):
            self.colorBarPosition.addItem(name, key)

        family = publication_settings.font_family or QtWidgets.QApplication.font().family()
        self.fontFamily.setCurrentFont(QtGui.QFont(family))
        self.fontSize.setValue(publication_settings.font_size)
        self._load_dimension(self.widthMm, self.automaticWidth, plot_settings.width_mm)
        self._load_dimension(self.heightMm, self.automaticHeight, plot_settings.height_mm)
        self.palette.setCurrentIndex(self.palette.findData(plot_settings.palette))
        self.colorBarPosition.setCurrentIndex(
            self.colorBarPosition.findData(plot_settings.color_bar_position)
        )
        self.showValues.setChecked(plot_settings.show_values)
        if spec.secondary_values is not None:
            self.decimals.setMinimum(0)
        self.decimals.setValue(plot_settings.decimals if fixed_decimals is None else fixed_decimals)
        self.cellBorders.setChecked(plot_settings.cell_borders)
        self.dpi.setValue(plot_settings.dpi)

        self.automaticWidth.toggled.connect(self.widthMm.setDisabled)
        self.automaticHeight.toggled.connect(self.heightMm.setDisabled)
        self.showValues.toggled.connect(self._set_decimals_enabled)
        self.fontFamily.currentFontChanged.connect(self._update_dimension_minima)
        self.fontSize.valueChanged.connect(self._update_dimension_minima)
        self.colorBarPosition.currentIndexChanged.connect(self._update_dimension_minima)
        self.showValues.toggled.connect(self._update_dimension_minima)
        self.decimals.valueChanged.connect(self._update_dimension_minima)
        self._set_decimals_enabled(plot_settings.show_values)
        self._update_dimension_minima()

    @staticmethod
    def _load_dimension(spin_box, automatic, value: float | None) -> None:
        automatic.setChecked(value is None)
        spin_box.setDisabled(value is None)
        if value is not None:
            spin_box.setValue(value)

    def _set_decimals_enabled(self, enabled: bool) -> None:
        self.decimals.setEnabled(enabled and self._fixed_decimals is None)
        self.decimalsLabel.setEnabled(enabled and self._fixed_decimals is None)

    def _update_dimension_minima(self, *_unused) -> None:
        publication = MatrixPublicationSettings(
            font_family=self.fontFamily.currentFont().family(),
            font_size=self.fontSize.value(),
        )
        settings = replace(
            self._plot_settings,
            color_bar_position=self.colorBarPosition.currentData(),
        )
        spec = replace(
            self._spec,
            show_values=self.showValues.isChecked(),
            decimals=self.decimals.value(),
        )
        minimum_width, minimum_height = minimum_matrix_dimensions_mm(spec, publication, settings)
        self.widthMm.setMinimum(math.ceil(minimum_width * 10) / 10)
        self.heightMm.setMinimum(math.ceil(minimum_height * 10) / 10)

    def accept(self) -> None:
        """Commit the controls to their project-owned settings."""
        self._publication_settings.font_family = self.fontFamily.currentFont().family()
        self._publication_settings.font_size = self.fontSize.value()
        self._plot_settings.width_mm = (
            None if self.automaticWidth.isChecked() else self.widthMm.value()
        )
        self._plot_settings.height_mm = (
            None if self.automaticHeight.isChecked() else self.heightMm.value()
        )
        self._plot_settings.palette = self.palette.currentData()
        self._plot_settings.color_bar_position = self.colorBarPosition.currentData()
        self._plot_settings.show_values = self.showValues.isChecked()
        if self._fixed_decimals is None:
            self._plot_settings.decimals = self.decimals.value()
        self._plot_settings.cell_borders = self.cellBorders.isChecked()
        self._plot_settings.dpi = self.dpi.value()
        super().accept()
