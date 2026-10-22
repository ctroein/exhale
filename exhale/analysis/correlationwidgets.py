"""Qt and pyqtgraph views for correlation matrices and pairwise scatter plots."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from qtpy import QtCore, QtGui, QtWidgets

from ..data.plotsettings import MatrixPlotSettings
from .correlations import (
    CorrelationMatrix,
    DensityGrid,
    SampleSimilarityMatrix,
    interpolated_density,
)
from .matrixplots import (
    CORRELATION_COLOR_STOPS,
    MATRIX_PALETTES,
    ColorStop,
    MatrixPlotSpec,
    correlation_matrix_spec,
    matrix_text_layout,
)

MatrixResult = CorrelationMatrix | SampleSimilarityMatrix


def _color_map(stops: tuple[ColorStop, ...]) -> pg.ColorMap:
    positions = np.fromiter((stop.position for stop in stops), dtype=np.float64)
    colors = np.asarray([stop.color for stop in stops], dtype=np.ubyte)
    return pg.ColorMap(positions, colors)


def _plot_background(palette: QtGui.QPalette) -> QtGui.QColor:
    if palette.color(QtGui.QPalette.Window).lightness() < 128:
        return QtGui.QColor("black")
    return palette.color(QtGui.QPalette.Base)


def _density_background(palette: QtGui.QPalette) -> QtGui.QColor:
    if palette.color(QtGui.QPalette.Window).lightness() < 128:
        return QtGui.QColor("black")
    return QtGui.QColor("white")


class _MatrixColorBarItem(pg.ColorBarItem):
    """Keep a layout-managed color bar aligned with a matrix rectangle."""

    def __init__(self, *args, **kwargs):
        self._matrix_vertical_extent: tuple[float, float] | None = None
        self._right_label_left_offset = 0.0
        super().__init__(*args, **kwargs)

    def set_right_label_left_offset(self, offset: float) -> None:
        self._right_label_left_offset = offset
        self._position_right_label()

    def _position_right_label(self) -> None:
        if "right" not in getattr(self, "axes", {}):
            return
        axis = self.getAxis("right")
        axis.resizeEvent()
        current_left = axis.label.sceneBoundingRect().left()
        target_left = self.bar.sceneBoundingRect().right() + self._right_label_left_offset
        axis.label.setPos(axis.label.pos() + QtCore.QPointF(target_left - current_left, 0))

    def set_matrix_vertical_extent(self, top: float, bottom: float) -> None:
        self._matrix_vertical_extent = (top, bottom)
        self.setGeometry(self.geometry())

    def setGeometry(self, rect) -> None:
        rect = QtCore.QRectF(rect)
        if self._matrix_vertical_extent is not None:
            rect.setTop(self._matrix_vertical_extent[0])
            rect.setBottom(self._matrix_vertical_extent[1])
        super().setGeometry(rect)
        self._position_right_label()


class CorrelationPlotWidget(QtWidgets.QWidget):
    """Show a labelled heat map and drill down to one pairwise scatter plot."""

    pairActivated = QtCore.Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._matrix_spec: MatrixPlotSpec | None = None
        self._value_labels = []
        self._axis_labels = []
        self._matrix_bounds = QtCore.QRectF()
        self._matrix_content_bounds = QtCore.QRectF()
        self._clamping_matrix_view = False
        self._fit_pending = False
        self._reset_matrix_view = False

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
        matrix_item.getViewBox().sigRangeChangedManually.connect(self._matrix_view_range_changed)
        matrix_item.hideAxis("left")
        matrix_item.hideAxis("bottom")
        vertical_margin = QtGui.QFontMetrics(QtWidgets.QApplication.font()).height() // 2
        matrix_item.layout.setContentsMargins(0, vertical_margin, 0, vertical_margin)
        self.matrix_border = QtWidgets.QGraphicsRectItem()
        self.matrix_border.setZValue(5)
        self.matrix_plot.addItem(self.matrix_border)
        self.matrix_plot.scene().sigMouseClicked.connect(self._matrix_clicked)

        self.color_map = _color_map(CORRELATION_COLOR_STOPS)
        self.color_bar = _MatrixColorBarItem(
            values=(-1.0, 1.0),
            colorMap=self.color_map,
            interactive=False,
        )
        self.color_bar.getAxis("right").setStyle(showValues=True)
        self.color_bar.getAxis("right").setTicks(
            [
                [(-1.0, "-1"), (0.0, "0"), (1.0, "1")],
                [(value / 10.0, "") for value in range(-9, 10) if value],
            ]
        )
        self.color_bar.setImageItem(self.image, insert_in=self.matrix_plot.getPlotItem())
        matrix_item.layout.setAlignment(self.color_bar, QtCore.Qt.AlignVCenter)
        self.reload_appearance()

    def set_matrix_spec(self, spec: MatrixPlotSpec | None) -> None:
        """Display a matrix according to a renderer-independent specification."""
        previous = self._matrix_spec
        self._reset_matrix_view = self._reset_matrix_view or (
            spec is not None
            and (
                previous is None
                or previous.values is not spec.values
                or previous.labels != spec.labels
            )
        )
        self._matrix_spec = spec
        if spec is None:
            self.image.clear()
            self.matrix_border.setRect(QtCore.QRectF())
            self._clear_axis_labels()
            self._matrix_bounds = QtCore.QRectF()
            self._matrix_content_bounds = QtCore.QRectF()
        else:
            self.color_map = _color_map(spec.color_stops)
            self.image.setLookupTable(self.color_map.getLookupTable(0.0, 1.0, 256))
            self.image.setLevels(spec.levels)
            self.color_bar.setColorMap(self.color_map)
            self.color_bar.setLevels(spec.levels)
            foreground = QtWidgets.QApplication.palette().color(QtGui.QPalette.Text)
            self.color_bar.getAxis("right").setLabel(spec.color_bar_label, color=foreground.name())
            self.image.setImage(spec.values, autoLevels=False)
            size = len(spec.labels)
            matrix_rect = QtCore.QRectF(-0.5, -0.5, size, size)
            self.image.setRect(matrix_rect)
            self.matrix_border.setRect(matrix_rect)
            self._rebuild_axis_labels(spec.labels)
            if self._reset_matrix_view:
                self.matrix_plot.getViewBox().setRange(
                    matrix_rect.adjusted(-1.0, -1.0, 1.0, 1.0),
                    padding=0.0,
                    disableAutoRange=True,
                )
        self._rebuild_value_labels()
        self._schedule_matrix_fit()
        self.show_matrix()

    def _rebuild_value_labels(self) -> None:
        for label in self._value_labels:
            self.matrix_plot.removeItem(label)
        self._value_labels.clear()
        if self._matrix_spec is None:
            return
        spec = self._matrix_spec
        lower, upper = spec.levels
        level_span = upper - lower
        for row, values in enumerate(spec.values):
            for column, value in enumerate(values):
                if not np.isfinite(value):
                    continue
                normalized = 0.5 if level_span == 0 else (value - lower) / level_span
                background = self.color_map.map(normalized, mode="qcolor")
                foreground = "black" if background.lightnessF() > 0.55 else "white"
                label = pg.TextItem(
                    f"{value:.{spec.decimals}f}",
                    color=foreground,
                    anchor=(0.5, 0.5),
                )
                label.setPos(column, row)
                label.setZValue(10)
                self.matrix_plot.addItem(label)
                self._value_labels.append(label)
        for label in self._value_labels:
            label.setVisible(spec.show_values)

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
                anchor=(1.0, 0.0),
                angle=45,
            )
            column_label.setPos(index, size - 0.35)
            column_label.setZValue(10)
            self.matrix_plot.addItem(column_label)
            self._axis_labels.append(column_label)

    def _fit_matrix(self) -> None:
        if self._matrix_spec is None or not self._matrix_spec.labels:
            self.matrix_plot.setUpdatesEnabled(True)
            return
        spec = self._matrix_spec
        size = len(spec.labels)
        metrics = QtGui.QFontMetrics(QtWidgets.QApplication.font())
        text = matrix_text_layout(spec, metrics.height(), metrics.horizontalAdvance)
        color_bar_axis = self.color_bar.getAxis("right")
        color_bar_axis.setStyle(tickTextOffset=round(text.color_bar_tick_gap))
        self.color_bar.set_right_label_left_offset(text.color_bar_label_offset)
        color_bar_axis.setWidth(
            round(text.color_bar_label_offset + color_bar_axis.label.boundingRect().height())
        )
        matrix_layout = self.matrix_plot.getPlotItem().layout
        matrix_layout.setColumnFixedWidth(4, round(text.color_bar_matrix_gap))
        matrix_layout.activate()
        viewport = self.matrix_plot.viewport().size()
        if not self.matrix_plot.isVisible() or min(viewport.width(), viewport.height()) < 50:
            self.matrix_plot.setUpdatesEnabled(True)
            return
        fitted_cell = text.preferred_cell
        top_margin = text.font_height / (2 * fitted_cell) + 0.1
        row_margin = max(0.35, text.row_label_width / fitted_cell)
        column_margin = max(
            0.6,
            text.column_label_height / fitted_cell + 0.3,
        )
        content_bounds = QtCore.QRectF(
            -0.5 - row_margin,
            -0.5 - top_margin,
            size + row_margin,
            size + top_margin + column_margin,
        )
        self._matrix_content_bounds = QtCore.QRectF(content_bounds)
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
        minimum_cell = text.minimum_cell
        maximum_cell = text.preferred_cell if spec.show_values else 3.0 * minimum_cell
        minimum_x_span = view_rect.width() / maximum_cell
        minimum_y_span = view_rect.height() / maximum_cell
        maximum_x_span = view_rect.width() / minimum_cell
        maximum_y_span = view_rect.height() / minimum_cell
        navigation_width = max(self._matrix_bounds.width(), maximum_x_span)
        navigation_height = navigation_width / aspect
        if navigation_height < max(self._matrix_bounds.height(), maximum_y_span):
            navigation_height = max(self._matrix_bounds.height(), maximum_y_span)
            navigation_width = navigation_height * aspect
        center = self._matrix_bounds.center()
        self._matrix_bounds = QtCore.QRectF(
            center.x() - navigation_width / 2,
            center.y() - navigation_height / 2,
            navigation_width,
            navigation_height,
        )
        view_box.setLimits(
            xMin=self._matrix_bounds.left(),
            xMax=self._matrix_bounds.right(),
            yMin=self._matrix_bounds.top(),
            yMax=self._matrix_bounds.bottom(),
            minXRange=minimum_x_span,
            minYRange=minimum_y_span,
            maxXRange=maximum_x_span,
            maxYRange=maximum_y_span,
        )
        if self._reset_matrix_view:
            initial_width = view_rect.width() / text.preferred_cell
            center = self._matrix_bounds.center()
        else:
            current_range = view_box.viewRect()
            initial_width = min(current_range.width(), maximum_x_span)
            center = current_range.center()
        initial_width = min(max(initial_width, minimum_x_span), maximum_x_span)
        initial_height = initial_width / aspect
        if initial_height > maximum_y_span:
            initial_height = maximum_y_span
            initial_width = initial_height * aspect
        center.setX(
            min(
                self._matrix_bounds.right() - initial_width / 2,
                max(self._matrix_bounds.left() + initial_width / 2, center.x()),
            )
        )
        center.setY(
            min(
                self._matrix_bounds.bottom() - initial_height / 2,
                max(self._matrix_bounds.top() + initial_height / 2, center.y()),
            )
        )
        initial_range = QtCore.QRectF(
            center.x() - initial_width / 2,
            center.y() - initial_height / 2,
            initial_width,
            initial_height,
        )
        view_box.setRange(initial_range, padding=0.0, disableAutoRange=True)
        self._position_matrix_column_labels(text)
        self._update_matrix_content_bounds()
        self._clamp_matrix_view_to_content()
        self._reset_matrix_view = False
        self._fit_pending = False
        self.matrix_plot.setUpdatesEnabled(True)
        self.matrix_plot.update()
        QtCore.QTimer.singleShot(0, self._resize_matrix_color_bar)

    def _schedule_matrix_fit(self) -> None:
        self._fit_pending = True
        if self.matrix_plot.isVisible():
            self.matrix_plot.setUpdatesEnabled(False)
        QtCore.QTimer.singleShot(0, self._fit_matrix)

    def eventFilter(self, watched, event):
        if watched is self.scatter_plot and event.type() in (
            QtCore.QEvent.Show,
            QtCore.QEvent.Resize,
        ):
            QtCore.QTimer.singleShot(0, self._resize_density_color_bar)
        if watched is self.matrix_plot and event.type() in (
            QtCore.QEvent.Show,
            QtCore.QEvent.Resize,
        ):
            self._fit_pending = True
            QtCore.QTimer.singleShot(0, self._fit_matrix)
            QtCore.QTimer.singleShot(0, self._resize_matrix_color_bar)
        return super().eventFilter(watched, event)

    def _resize_matrix_color_bar(self) -> None:
        if self._matrix_spec is None or not self._matrix_spec.labels:
            return
        matrix_item = self.matrix_plot.getPlotItem()
        matrix_rect = self.image.mapRectToItem(matrix_item, self.image.boundingRect())
        if matrix_rect.height() <= 0:
            return
        visible_matrix_rect = matrix_rect.intersected(self.matrix_plot.getViewBox().geometry())
        self.color_bar.set_matrix_vertical_extent(
            visible_matrix_rect.top(), visible_matrix_rect.bottom()
        )

    def _matrix_view_range_changed(self, *_unused) -> None:
        self._position_matrix_column_labels()
        self._update_matrix_content_bounds()
        self._clamp_matrix_view_to_content()
        QtCore.QTimer.singleShot(0, self._resize_matrix_color_bar)

    def _update_matrix_content_bounds(self) -> None:
        if self._matrix_spec is None:
            self._matrix_content_bounds = QtCore.QRectF()
            return
        size = len(self._matrix_spec.labels)
        bounds = QtCore.QRectF(-0.5, -0.5, size, size)
        view_box = self.matrix_plot.getViewBox()
        for label in self._axis_labels:
            scene_bounds = label.sceneBoundingRect()
            top_left = view_box.mapSceneToView(scene_bounds.topLeft())
            bottom_right = view_box.mapSceneToView(scene_bounds.bottomRight())
            bounds = bounds.united(QtCore.QRectF(top_left, bottom_right).normalized())
        self._matrix_content_bounds = bounds

    def _clamp_matrix_view_to_content(self) -> None:
        if self._clamping_matrix_view or self._matrix_content_bounds.isEmpty():
            return
        view_box = self.matrix_plot.getViewBox()
        current = view_box.viewRect()
        bounds = self._matrix_content_bounds
        center = QtCore.QPointF(current.center())
        if current.width() >= bounds.width():
            center.setX(bounds.center().x())
        else:
            center.setX(
                min(
                    bounds.right() - current.width() / 2,
                    max(bounds.left() + current.width() / 2, center.x()),
                )
            )
        if current.height() >= bounds.height():
            center.setY(bounds.center().y())
        else:
            center.setY(
                min(
                    bounds.bottom() - current.height() / 2,
                    max(bounds.top() + current.height() / 2, center.y()),
                )
            )
        if center == current.center():
            return
        corrected = QtCore.QRectF(current)
        corrected.moveCenter(center)
        self._clamping_matrix_view = True
        try:
            view_box.setRange(corrected, padding=0.0, disableAutoRange=True)
        finally:
            self._clamping_matrix_view = False

    def _position_matrix_column_labels(self, text=None) -> None:
        if self._matrix_spec is None:
            return
        if text is None:
            metrics = QtGui.QFontMetrics(QtWidgets.QApplication.font())
            text = matrix_text_layout(
                self._matrix_spec, metrics.height(), metrics.horizontalAdvance
            )
        pixel_height = abs(self.matrix_plot.getViewBox().viewPixelSize()[1])
        y = len(self._matrix_spec.labels) - 0.5 + text.column_label_gap * pixel_height
        for label in self._axis_labels[1::2]:
            label.setPos(label.pos().x(), y)

    def _matrix_clicked(self, event) -> None:
        if (
            self._matrix_spec is None
            or not event.double()
            or event.button() != QtCore.Qt.LeftButton
        ):
            return
        point = self.image.mapFromScene(event.scenePos())
        column = int(np.floor(point.x() + 0.5))
        row = int(np.floor(point.y() + 0.5))
        size = len(self._matrix_spec.labels)
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
        background = _plot_background(palette)
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
        color_bar_label = "" if self._matrix_spec is None else self._matrix_spec.color_bar_label
        self.color_bar.getAxis("right").setLabel(color_bar_label, color=foreground.name())
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
        background = _density_background(palette)
        foreground = palette.color(QtGui.QPalette.Text)
        positions = (0.0, 0.01, 0.25, 0.5, 0.75, 1.0)
        foreground_fractions = (0.0, 0.03, 0.08, 0.25, 0.55, 1.0)
        colors = []
        for fraction in foreground_fractions:
            colors.append(
                (
                    round(background.red() * (1 - fraction) + foreground.red() * fraction),
                    round(background.green() * (1 - fraction) + foreground.green() * fraction),
                    round(background.blue() * (1 - fraction) + foreground.blue() * fraction),
                    255,
                )
            )
        color_map = pg.ColorMap(
            positions,
            np.asarray(colors, dtype=np.ubyte),
        )
        lookup_table = color_map.getLookupTable(0.0, 1.0, 256)
        display_map = pg.ColorMap(np.linspace(0.0, 1.0, 256), lookup_table)
        self.density_color_bar.setColorMap(display_map)
        self.density_image.setLookupTable(lookup_table)
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

    def __init__(
        self,
        host,
        show_values,
        decimals,
        decimals_label,
        copy_button,
        palette,
        settings: MatrixPlotSettings,
    ):
        super().__init__(host)
        self.result: MatrixResult | None = None
        self.plot = CorrelationPlotWidget(host)
        plot_layout = QtWidgets.QVBoxLayout(host)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.addWidget(self.plot)

        self._show_values = show_values
        self._decimals = decimals
        self._decimals_label = decimals_label
        self._palette = palette
        self._settings = settings
        for definition in MATRIX_PALETTES:
            palette.addItem(definition.name, definition.key)
        show_values.toggled.connect(self._value_options_changed)
        decimals.valueChanged.connect(self._value_options_changed)
        palette.currentIndexChanged.connect(self._palette_changed)
        copy_button.clicked.connect(self.copy_table)
        self.plot.pairActivated.connect(self.pairActivated.emit)
        self.reload_settings()

    def set_result(self, result: MatrixResult | None) -> None:
        self.result = result
        self._update_plot_spec()

    def _value_options_changed(self) -> None:
        enabled = self._show_values.isChecked()
        self._decimals.setEnabled(enabled)
        self._decimals_label.setEnabled(enabled)
        self._settings.show_values = enabled
        self._settings.decimals = self._decimals.value()
        self._update_plot_spec()

    def _palette_changed(self) -> None:
        if self._palette.currentData() is not None:
            self._settings.palette = self._palette.currentData()
        self._update_plot_spec()

    def reload_settings(self) -> None:
        """Reload project-owned choices into the controls and plot."""
        with (
            QtCore.QSignalBlocker(self._show_values),
            QtCore.QSignalBlocker(self._decimals),
            QtCore.QSignalBlocker(self._palette),
        ):
            self._show_values.setChecked(self._settings.show_values)
            self._decimals.setValue(self._settings.decimals)
            palette_index = self._palette.findData(self._settings.palette)
            if palette_index < 0:
                palette_index = self._palette.findData("blue-white-red")
                self._settings.palette = "blue-white-red"
            self._palette.setCurrentIndex(palette_index)
        self._decimals.setEnabled(self._settings.show_values)
        self._decimals_label.setEnabled(self._settings.show_values)
        self._update_plot_spec()

    def _update_plot_spec(self) -> None:
        spec = None
        if self.result is not None:
            spec = correlation_matrix_spec(
                self.result.values,
                self.result.labels,
                palette=self._settings.palette,
                show_values=self._show_values.isChecked(),
                decimals=self._decimals.value(),
            )
        self.plot.set_matrix_spec(spec)

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
