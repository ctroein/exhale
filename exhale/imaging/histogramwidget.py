"""Pyqtgraph histogram display with normalization-range markers."""

import math

import numpy as np
import pyqtgraph as pg
from qtpy import QtCore, QtWidgets


class HistogramWidget(pg.PlotWidget):
    """Display histogram bins and an ordered pair of draggable limits.

    The public API always uses original data values. Logarithmic conversion is
    confined to the plot coordinates, including the two marker positions.
    """

    limitsChanged = QtCore.Signal(float, float)
    histogramRangeRequested = QtCore.Signal(float, float)
    _BINNING_MARGIN = 0.25

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.reload_appearance()
        self.setMenuEnabled(False)
        self.hideButtons()
        self.hideAxis("left")
        self.hideAxis("bottom")
        self.getViewBox().setMouseMode(pg.ViewBox.PanMode)
        self.getViewBox().setMouseEnabled(x=True, y=False)
        self.getViewBox().setDefaultPadding(0.02)

        self.curve = pg.PlotCurveItem(
            pen=pg.mkPen("#707070"),
            brush=pg.mkBrush(128, 128, 128, 150),
            fillLevel=0,
        )
        self.addItem(self.curve)

        marker_pen = pg.mkPen("#0000a0", width=2)
        self.minimum_marker = pg.InfiniteLine(
            angle=90,
            movable=True,
            pen=marker_pen,
            hoverPen=pg.mkPen("#3030d0", width=2),
            label="Min",
            labelOpts={"position": 0.9},
        )
        self.maximum_marker = pg.InfiniteLine(
            angle=90,
            movable=True,
            pen=marker_pen,
            hoverPen=pg.mkPen("#3030d0", width=2),
            label="Max",
            labelOpts={"position": 0.9},
        )
        for marker in (self.minimum_marker, self.maximum_marker):
            self.addItem(marker)
            marker.hide()
            marker.sigPositionChanged.connect(self._marker_changed)

        self._logarithmic = False
        self._domain = None
        self._histogram_domain = None
        self._limits = None
        self._updating_markers = False
        self._adaptive_binning = False
        self._display_count_maximum = 1.0
        self._rebin_timer = QtCore.QTimer(self)
        self._rebin_timer.setSingleShot(True)
        self._rebin_timer.setInterval(200)
        self._rebin_timer.timeout.connect(self._request_visible_histogram)
        self.getViewBox().sigRangeChangedManually.connect(self._view_changed_manually)

    def reload_appearance(self):
        """Apply the current application palette to the plot."""
        self.setBackground(QtWidgets.QApplication.palette().window().color())

    @property
    def logarithmic(self):
        return self._logarithmic

    @property
    def limits(self):
        return self._limits

    def _to_display(self, value):
        if self._logarithmic:
            return math.log10(value)
        return float(value)

    def _from_display(self, value):
        if self._logarithmic:
            return 10.0**value
        return float(value)

    def set_histogram(
        self,
        counts,
        edges,
        *,
        logarithmic=False,
        reset_view=True,
        data_domain=None,
        adaptive_binning=False,
    ):
        """Set bin counts and edges, optionally using a logarithmic x-axis."""
        counts = np.asarray(counts)
        edges = np.asarray(edges)
        if counts.ndim != 1 or edges.ndim != 1 or len(edges) != len(counts) + 1 or len(counts) == 0:
            raise ValueError("Histogram needs one-dimensional counts and N+1 edges")
        if (
            not np.all(np.isfinite(counts))
            or np.any(counts < 0)
            or not np.all(np.isfinite(edges))
            or np.any(np.diff(edges) <= 0)
        ):
            raise ValueError("Histogram counts and edges must be finite and ordered")
        if logarithmic and edges[0] <= 0:
            raise ValueError("Logarithmic histogram edges must be positive")

        if data_domain is None:
            data_domain = (edges[0], edges[-1])
        data_domain = tuple(float(value) for value in data_domain)
        if (
            len(data_domain) != 2
            or not np.all(np.isfinite(data_domain))
            or data_domain[0] >= data_domain[1]
            or data_domain[0] > edges[0]
            or data_domain[1] < edges[-1]
        ):
            raise ValueError("Data domain must contain the histogram edges")
        if logarithmic and data_domain[0] <= 0:
            raise ValueError("Logarithmic data domain must be positive")

        old_limits = self._limits
        self._logarithmic = bool(logarithmic)
        self._domain = data_domain
        self._histogram_domain = (float(edges[0]), float(edges[-1]))
        self._adaptive_binning = bool(adaptive_binning)
        self._display_count_maximum = self._count_axis_maximum(counts)
        display_edges = np.log10(edges) if self._logarithmic else edges.astype(float, copy=False)
        self.curve.setData(display_edges, counts, stepMode="center")

        if old_limits is not None:
            if self._logarithmic and old_limits[0] == 0:
                low = 0
            else:
                low = max(self._domain[0], old_limits[0])
            high = min(self._domain[1], old_limits[1])
            if low <= high:
                self.set_limits(low, high)
            else:
                self.clear_limits()
        if reset_view:
            self.reset_view()
        else:
            self.getViewBox().setYRange(0, self._display_count_maximum, padding=0.02)

    @staticmethod
    def _count_axis_maximum(counts):
        """Cap one exceptional bin at twice the next-highest populated bin."""
        highest = float(np.max(counts))
        if len(counts) < 2:
            return max(1.0, highest)
        second_highest = float(np.partition(counts, -2)[-2])
        if second_highest > 0:
            highest = min(highest, 2 * second_highest)
        return max(1.0, highest)

    def set_limits(self, minimum, maximum, *, emit=False):
        """Place the ordered limit markers using original data values."""
        if self._domain is None:
            raise RuntimeError("Set histogram data before setting limits")
        minimum = float(minimum)
        maximum = float(maximum)
        domain_minimum = 0 if self._logarithmic else self._domain[0]
        if not (domain_minimum <= minimum <= maximum <= self._domain[1]):
            raise ValueError("Limits must be ordered and inside the histogram range")

        self._updating_markers = True
        try:
            # Zero represents the lower end of a logarithmic transformation;
            # draw its marker at the first positive histogram edge.
            displayed_minimum = self._domain[0] if self._logarithmic and minimum == 0 else minimum
            low = self._to_display(displayed_minimum)
            high = self._to_display(maximum)
            domain_low = self._to_display(self._domain[0])
            domain_high = self._to_display(self._domain[1])
            self.minimum_marker.setBounds((domain_low, high))
            self.maximum_marker.setBounds((low, domain_high))
            self.minimum_marker.setValue(low)
            self.maximum_marker.setValue(high)
            self.minimum_marker.show()
            self.maximum_marker.show()
            self._limits = (minimum, maximum)
        finally:
            self._updating_markers = False
        if emit:
            self.limitsChanged.emit(*self._limits)

    def clear_limits(self):
        self._limits = None
        self.minimum_marker.hide()
        self.maximum_marker.hide()

    def clear_histogram(self):
        """Discard histogram data and hide both range markers."""
        self.curve.clear()
        self._domain = None
        self._histogram_domain = None
        self._adaptive_binning = False
        self._rebin_timer.stop()
        self.clear_limits()

    def _view_changed_manually(self):
        if self._adaptive_binning and not self._logarithmic:
            self._rebin_timer.start()

    def _request_visible_histogram(self):
        """Request finer bins after a material change to the visible x-range."""
        if self._domain is None or self._histogram_domain is None:
            return
        view_low, view_high = self.getViewBox().viewRange()[0]
        domain_low, domain_high = self._domain
        visible_low = max(domain_low, float(view_low))
        visible_high = min(domain_high, float(view_high))
        if visible_low >= visible_high:
            return

        full_width = domain_high - domain_low
        visible_width = visible_high - visible_low
        if visible_width >= 0.9 * full_width:
            requested = self._domain
        else:
            margin = self._BINNING_MARGIN * visible_width
            requested = (
                max(domain_low, visible_low - margin),
                min(domain_high, visible_high + margin),
            )

        binned_low, binned_high = self._histogram_domain
        binned_width = binned_high - binned_low
        if np.allclose(requested, self._histogram_domain, rtol=1e-9, atol=0):
            return
        substantially_finer = visible_width <= 0.5 * binned_width
        substantially_broader = visible_width >= 0.8 * binned_width
        margin_exhausted = (
            binned_low > domain_low and visible_low <= binned_low + 0.05 * binned_width
        ) or (binned_high < domain_high and visible_high >= binned_high - 0.05 * binned_width)
        if substantially_finer or substantially_broader or margin_exhausted:
            self.histogramRangeRequested.emit(*requested)

    def _marker_changed(self):
        if self._updating_markers or self._domain is None:
            return
        minimum = self._from_display(self.minimum_marker.value())
        maximum = self._from_display(self.maximum_marker.value())
        # InfiniteLine enforces these bounds during dragging. Reapply them when
        # either line moves so the two markers can never cross subsequently.
        self._limits = (minimum, maximum)
        domain_low = self._to_display(self._domain[0])
        domain_high = self._to_display(self._domain[1])
        self.minimum_marker.setBounds((domain_low, self.maximum_marker.value()))
        self.maximum_marker.setBounds((self.minimum_marker.value(), domain_high))
        self.limitsChanged.emit(minimum, maximum)

    def reset_view(self):
        """Fit the histogram and markers without leaving auto-range enabled."""
        view_box = self.getViewBox()
        view_box.setLimits(xMin=None, xMax=None, maxXRange=None)
        view_box.autoRange(padding=0.02)
        view_box.disableAutoRange()
        initial_low, initial_high = view_box.viewRange()[0]
        initial_width = initial_high - initial_low
        view_box.setLimits(
            xMin=initial_low,
            xMax=initial_high,
            maxXRange=initial_width,
        )
        view_box.setYRange(0, self._display_count_maximum, padding=0.02)
