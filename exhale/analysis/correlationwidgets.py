"""Qt and pyqtgraph views for correlation matrices and pairwise scatter plots."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from qtpy import QtCore, QtGui, QtWidgets

from .correlations import (
    CorrelationMatrix,
    DensityGrid,
    SampleSimilarityMatrix,
    interpolated_density,
)

MatrixResult = CorrelationMatrix | SampleSimilarityMatrix


class CorrelationPlotWidget(QtWidgets.QWidget):
    """Show a labelled heat map and drill down to one pairwise scatter plot."""

    pairActivated = QtCore.Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._result: MatrixResult | None = None
        self._show_values = True
        self._decimals = 2
        self._value_labels = []
        self._axis_labels = []
        self._matrix_bounds = QtCore.QRectF()
        self._fit_pending = False

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QtWidgets.QStackedWidget(self)
        layout.addWidget(self.stack, 1)
        self.matrix_plot = pg.PlotWidget(self.stack)
        self.matrix_plot.installEventFilter(self)
        self.scatter_plot = pg.PlotWidget(self.stack)
        self.scatter_plot.installEventFilter(self)
        self.density_image = None
        self._density_bar_inserted = False
        self.density_color_bar = pg.ColorBarItem(
            values=(0.0, 1.0), label="log(1 + density)", interactive=False
        )
        self.density_color_bar.setMinimumWidth(125)
        density_axis = self.density_color_bar.getAxis("left")
        density_axis.setTicks(None)
        density_axis.setStyle(showValues=True)
        density_axis.setWidth(100)
        self.density_color_bar.getAxis("right").setStyle(showValues=False)
        self.density_color_bar.hide()
        self.stack.addWidget(self.matrix_plot)
        self.stack.addWidget(self.scatter_plot)

        self.image = pg.ImageItem(axisOrder="row-major")
        self.matrix_plot.addItem(self.image)
        matrix_item = self.matrix_plot.getPlotItem()
        matrix_item.setAspectLocked(True)
        matrix_item.invertY(True)
        matrix_item.hideAxis("left")
        matrix_item.hideAxis("bottom")
        vertical_margin = QtGui.QFontMetrics(QtWidgets.QApplication.font()).height() // 2
        matrix_item.layout.setContentsMargins(0, vertical_margin, 0, vertical_margin)
        self.matrix_border = QtWidgets.QGraphicsRectItem()
        self.matrix_border.setZValue(5)
        self.matrix_plot.addItem(self.matrix_border)
        self.matrix_plot.scene().sigMouseClicked.connect(self._matrix_clicked)

        colors = np.array(
            [
                (49, 54, 149, 255),
                (255, 255, 255, 255),
                (165, 0, 38, 255),
            ],
            dtype=np.ubyte,
        )
        self.color_map = pg.ColorMap((0.0, 0.5, 1.0), colors)
        self.image.setLookupTable(self.color_map.getLookupTable(0.0, 1.0, 256))
        self.image.setLevels((-1.0, 1.0))
        self.color_bar = pg.ColorBarItem(
            values=(-1.0, 1.0), colorMap=self.color_map, label="Pearson r", interactive=False
        )
        self.color_bar.setImageItem(self.image, insert_in=self.matrix_plot.getPlotItem())
        matrix_item.layout.setAlignment(self.color_bar, QtCore.Qt.AlignVCenter)
        self.reload_appearance()

    def set_result(self, result: MatrixResult | None) -> None:
        self._result = result
        if result is None:
            self.image.clear()
            self.matrix_border.setRect(QtCore.QRectF())
            self._clear_axis_labels()
            self._matrix_bounds = QtCore.QRectF()
        else:
            self.image.setImage(result.values, autoLevels=False)
            size = len(result.labels)
            matrix_rect = QtCore.QRectF(-0.5, -0.5, size, size)
            self.image.setRect(matrix_rect)
            self.matrix_border.setRect(matrix_rect)
            self._rebuild_axis_labels(result.labels)
        self._rebuild_value_labels()
        self._schedule_matrix_fit()
        self.show_matrix()

    def set_value_labels(self, visible: bool, decimals: int) -> None:
        self._show_values = visible
        self._decimals = decimals
        self._rebuild_value_labels()
        self._schedule_matrix_fit()

    def _rebuild_value_labels(self) -> None:
        for label in self._value_labels:
            self.matrix_plot.removeItem(label)
        self._value_labels.clear()
        if self._result is None:
            return
        for row, values in enumerate(self._result.values):
            for column, value in enumerate(values):
                if not np.isfinite(value):
                    continue
                background = self.color_map.map((value + 1.0) / 2.0, mode="qcolor")
                foreground = "black" if background.lightnessF() > 0.55 else "white"
                label = pg.TextItem(
                    f"{value:.{self._decimals}f}",
                    color=foreground,
                    anchor=(0.5, 0.5),
                )
                label.setPos(column, row)
                label.setZValue(10)
                self.matrix_plot.addItem(label)
                self._value_labels.append(label)
        for label in self._value_labels:
            label.setVisible(self._show_values)

    def _clear_axis_labels(self) -> None:
        for label in self._axis_labels:
            self.matrix_plot.removeItem(label)
        self._axis_labels.clear()

    def _rebuild_axis_labels(self, labels: tuple[str, ...]) -> None:
        self._clear_axis_labels()
        foreground = QtWidgets.QApplication.palette().color(QtGui.QPalette.Text)
        size = len(labels)
        for index, text in enumerate(labels):
            row_label = pg.TextItem(text, color=foreground, anchor=(1.0, 0.5))
            row_label.setPos(-0.65, index)
            row_label.setZValue(10)
            self.matrix_plot.addItem(row_label)
            self._axis_labels.append(row_label)

            column_label = pg.TextItem(
                text,
                color=foreground,
                anchor=(0.0, 0.5),
                angle=-45,
            )
            column_label.setPos(index, size - 0.35)
            column_label.setZValue(10)
            self.matrix_plot.addItem(column_label)
            self._axis_labels.append(column_label)

    def _fit_matrix(self) -> None:
        if self._result is None or not self._result.labels:
            return
        size = len(self._result.labels)
        metrics = QtGui.QFontMetrics(QtWidgets.QApplication.font())
        longest = max(metrics.horizontalAdvance(label) for label in self._result.labels)
        viewport = self.matrix_plot.viewport().size()
        if not self.matrix_plot.isVisible() or min(viewport.width(), viewport.height()) < 50:
            return
        minimum_cell = 28 + self._decimals * 7 if self._show_values else 12
        available = max(1, min(viewport.width(), viewport.height()))
        fitted_cell = max(minimum_cell, available / max(size + 2, 1))
        top_margin = metrics.height() / (2 * fitted_cell) + 0.1
        row_margin = max(0.35, longest / fitted_cell + 0.2)
        column_margin = max(
            0.6,
            (longest * 0.72 + metrics.height()) / fitted_cell + 0.3,
        )
        content_bounds = QtCore.QRectF(
            -0.5 - row_margin,
            -0.5 - top_margin,
            size + row_margin,
            size + top_margin + column_margin,
        )
        view_box = self.matrix_plot.getViewBox()
        view_rect = view_box.sceneBoundingRect()
        aspect = view_rect.width() / max(view_rect.height(), 1.0)
        self._matrix_bounds = QtCore.QRectF(content_bounds)
        if self._matrix_bounds.width() / self._matrix_bounds.height() < aspect:
            extra = self._matrix_bounds.height() * aspect - self._matrix_bounds.width()
            self._matrix_bounds.adjust(-extra / 2, 0, extra / 2, 0)
        else:
            extra = self._matrix_bounds.width() / aspect - self._matrix_bounds.height()
            self._matrix_bounds.adjust(0, -extra / 2, 0, extra / 2)
        maximum_x_span = max(
            1.0,
            min(self._matrix_bounds.width(), viewport.width() / minimum_cell),
        )
        maximum_y_span = max(
            1.0,
            min(self._matrix_bounds.height(), viewport.height() / minimum_cell),
        )
        view_box.setLimits(
            xMin=self._matrix_bounds.left(),
            xMax=self._matrix_bounds.right(),
            yMin=self._matrix_bounds.top(),
            yMax=self._matrix_bounds.bottom(),
            minXRange=1.0,
            minYRange=1.0,
            maxXRange=maximum_x_span,
            maxYRange=maximum_y_span,
        )
        view_box.setRange(self._matrix_bounds, padding=0.0)
        self._fit_pending = False

    def _schedule_matrix_fit(self) -> None:
        self._fit_pending = True
        QtCore.QTimer.singleShot(0, self._fit_matrix)

    def eventFilter(self, watched, event):
        if watched is self.scatter_plot and event.type() in (
            QtCore.QEvent.Show,
            QtCore.QEvent.Resize,
        ):
            QtCore.QTimer.singleShot(0, self._resize_density_color_bar)
        if (
            watched is self.matrix_plot
            and self._fit_pending
            and event.type() in (QtCore.QEvent.Show, QtCore.QEvent.Resize)
        ):
            QtCore.QTimer.singleShot(0, self._fit_matrix)
        if watched is self.matrix_plot and event.type() in (
            QtCore.QEvent.Show,
            QtCore.QEvent.Resize,
        ):
            QtCore.QTimer.singleShot(0, self._resize_matrix_color_bar)
        return super().eventFilter(watched, event)

    def _resize_matrix_color_bar(self) -> None:
        height = self.matrix_plot.getViewBox().geometry().height()
        if height > 0:
            self.color_bar.setMaximumHeight(height * 0.9)

    def _matrix_clicked(self, event) -> None:
        if self._result is None or not event.double() or event.button() != QtCore.Qt.LeftButton:
            return
        point = self.image.mapFromScene(event.scenePos())
        column = int(np.floor(point.x() + 0.5))
        row = int(np.floor(point.y() + 0.5))
        size = len(self._result.labels)
        if 0 <= row < size and 0 <= column < size and row != column:
            self.pairActivated.emit(row, column)

    def show_density(self, grid: DensityGrid, first_label: str, second_label: str) -> None:
        self.scatter_plot.clear()
        image = interpolated_density(grid)
        self.density_image = pg.ImageItem(image, axisOrder="row-major")
        self.density_image.setRect(
            QtCore.QRectF(
                grid.x_edges[0],
                grid.y_edges[0],
                grid.x_edges[-1] - grid.x_edges[0],
                grid.y_edges[-1] - grid.y_edges[0],
            )
        )
        self._update_density_colours()
        self.scatter_plot.addItem(self.density_image)
        if self._density_bar_inserted:
            self.density_color_bar.setImageItem(self.density_image)
        else:
            self.density_color_bar.setImageItem(
                self.density_image, insert_in=self.scatter_plot.getPlotItem()
            )
            self.scatter_plot.getPlotItem().layout.setAlignment(
                self.density_color_bar, QtCore.Qt.AlignVCenter
            )
            self._density_bar_inserted = True
        self._resize_density_color_bar()
        self.density_color_bar.show()
        self.scatter_plot.setLabel("bottom", first_label)
        self.scatter_plot.setLabel("left", second_label)
        self.scatter_plot.enableAutoRange()
        self.stack.setCurrentWidget(self.scatter_plot)

    def show_scatter(self, first, second, first_label: str, second_label: str) -> None:
        first = np.asarray(first, dtype=np.float64).ravel()
        second = np.asarray(second, dtype=np.float64).ravel()
        valid = np.isfinite(first) & np.isfinite(second)
        first = first[valid]
        second = second[valid]
        maximum_points = 100_000
        if first.size > maximum_points:
            step = int(np.ceil(first.size / maximum_points))
            first = first[::step]
            second = second[::step]
        self.scatter_plot.clear()
        self.density_image = None
        self.density_color_bar.hide()
        self.scatter_plot.plot(
            first,
            second,
            pen=None,
            symbol="o",
            symbolSize=3,
            symbolPen=None,
            symbolBrush=QtGui.QColor(60, 130, 220, 100),
        )
        self.scatter_plot.setLabel("bottom", first_label)
        self.scatter_plot.setLabel("left", second_label)
        self.scatter_plot.enableAutoRange()
        self.stack.setCurrentWidget(self.scatter_plot)

    def clear_scatter(self) -> None:
        self.scatter_plot.clear()
        self.density_image = None
        self.density_color_bar.hide()
        self.scatter_plot.setLabel("bottom", "")
        self.scatter_plot.setLabel("left", "")
        self.stack.setCurrentWidget(self.scatter_plot)

    def show_matrix(self) -> None:
        self.stack.setCurrentWidget(self.matrix_plot)

    def current_plot_item(self):
        current = self.stack.currentWidget()
        return current.getPlotItem()

    def reload_appearance(self) -> None:
        palette = QtWidgets.QApplication.palette()
        background = palette.color(QtGui.QPalette.Base)
        foreground = palette.color(QtGui.QPalette.Text)
        for plot in (self.matrix_plot, self.scatter_plot):
            plot.setBackground(background)
            for axis_name in ("left", "bottom"):
                axis = plot.getAxis(axis_name)
                axis.setPen(foreground)
                axis.setTextPen(foreground)
        self.matrix_border.setPen(pg.mkPen(foreground))
        for label in self._axis_labels:
            label.setColor(foreground)
        for axis_name in ("left", "right", "top", "bottom"):
            axis = self.color_bar.getAxis(axis_name)
            axis.setPen(foreground)
            axis.setTextPen(foreground)
        self.color_bar.getAxis("left").setLabel("Pearson r", color=foreground.name())
        for axis_name in ("left", "right", "top", "bottom"):
            axis = self.density_color_bar.getAxis(axis_name)
            axis.setPen(foreground)
            axis.setTextPen(foreground)
        self.density_color_bar.getAxis("left").setLabel("log(1 + density)", color=foreground.name())
        self._update_density_colours()

    def _update_density_colours(self) -> None:
        if self.density_image is None:
            return
        palette = QtWidgets.QApplication.palette()
        background = palette.color(QtGui.QPalette.Base)
        foreground = palette.color(QtGui.QPalette.Text)
        color_map = pg.ColorMap(
            (0.0, 1.0),
            np.asarray((background.getRgb(), foreground.getRgb()), dtype=np.ubyte),
        )
        self.density_color_bar.setColorMap(color_map)
        self.density_image.setLookupTable(color_map.getLookupTable(0.0, 1.0, 256))
        maximum = float(np.nanmax(self.density_image.image))
        levels = (0.0, maximum if maximum > 0 else 1.0)
        self.density_image.setLevels(levels)
        self.density_color_bar.setLevels(levels)
        self.density_color_bar.getAxis("left").setTicks(
            [[(position * 64.0, f"{levels[1] * position / 4:.2g}") for position in range(5)]]
        )

    def _resize_density_color_bar(self) -> None:
        height = self.scatter_plot.getViewBox().geometry().height()
        if height > 0:
            self.density_color_bar.setMaximumHeight(height * 0.9)


class CorrelationMatrixView(QtCore.QObject):
    """Bind one matrix result and its controls to an independent plot."""

    pairActivated = QtCore.Signal(int, int)

    def __init__(self, host, show_values, decimals, decimals_label, copy_button):
        super().__init__(host)
        self.result: MatrixResult | None = None
        self.plot = CorrelationPlotWidget(host)
        plot_layout = QtWidgets.QVBoxLayout(host)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.addWidget(self.plot)

        self._show_values = show_values
        self._decimals = decimals
        self._decimals_label = decimals_label
        show_values.toggled.connect(self._value_options_changed)
        decimals.valueChanged.connect(self._value_options_changed)
        copy_button.clicked.connect(self.copy_table)
        self.plot.pairActivated.connect(self.pairActivated.emit)
        self._value_options_changed()

    def set_result(self, result: MatrixResult | None) -> None:
        self.result = result
        self.plot.set_result(result)

    def _value_options_changed(self) -> None:
        enabled = self._show_values.isChecked()
        self._decimals.setEnabled(enabled)
        self._decimals_label.setEnabled(enabled)
        self.plot.set_value_labels(self._show_values.isChecked(), self._decimals.value())

    def copy_table(self) -> None:
        if self.result is None:
            return
        rows = ["\t" + "\t".join(self.result.labels)]
        for label, values in zip(self.result.labels, self.result.values, strict=True):
            formatted = ["" if not np.isfinite(value) else f"{value:.6g}" for value in values]
            rows.append(label + "\t" + "\t".join(formatted))
        QtWidgets.QApplication.clipboard().setText("\n".join(rows))

    def reload_appearance(self) -> None:
        self.plot.reload_appearance()
