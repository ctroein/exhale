"""Histogram rendering and normalization-marker invariants."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

import numpy as np
from qtpy import QtCore, QtWidgets

from exhale.histogramwidget import HistogramWidget


class HistogramWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.widget = HistogramWidget()
        self.widget.resize(400, 180)
        self.widget.show()
        self.app.processEvents()
        self.addCleanup(self.dispose)

    def dispose(self):
        self.widget.close()
        self.widget.deleteLater()
        self.app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)

    def test_linear_histogram_keeps_bin_edges_and_counts(self):
        counts = np.array([2, 5, 3])
        edges = np.array([-1.0, 0.0, 2.0, 5.0])
        self.widget.set_histogram(counts, edges)
        x, y = self.widget.curve.getData()
        np.testing.assert_array_equal(x, edges)
        np.testing.assert_array_equal(y, counts)
        self.assertFalse(self.widget.logarithmic)
        self.assertEqual(self.widget.curve.opts["fillLevel"], 0)

    def test_log_histogram_transforms_only_display_coordinates(self):
        counts = np.array([1, 4, 2])
        edges = np.geomspace(0.01, 100, 4)
        self.widget.set_histogram(counts, edges, logarithmic=True)
        x, y = self.widget.curve.getData()
        np.testing.assert_allclose(x, np.log10(edges))
        np.testing.assert_array_equal(y, counts)

        self.widget.set_limits(0.1, 10)
        self.assertEqual(self.widget.limits, (0.1, 10.0))
        self.assertAlmostEqual(self.widget.minimum_marker.value(), -1)
        self.assertAlmostEqual(self.widget.maximum_marker.value(), 1)

    def test_markers_are_ordered_bounded_and_emit_data_values(self):
        self.widget.set_histogram([1, 3, 2], [0, 1, 2, 3])
        self.widget.set_limits(0.5, 2.5)
        changes = []
        self.widget.limitsChanged.connect(
            lambda low, high: changes.append((low, high)))

        self.widget.minimum_marker.setValue(1.25)
        self.assertEqual(changes[-1], (1.25, 2.5))
        self.widget.maximum_marker.setValue(0.25)
        self.assertEqual(self.widget.maximum_marker.value(), 1.25)
        self.assertEqual(changes[-1], (1.25, 1.25))
        self.widget.maximum_marker.setValue(99)
        self.assertEqual(self.widget.maximum_marker.value(), 3)
        self.assertEqual(changes[-1], (1.25, 3.0))

    def test_programmatic_limits_emit_only_when_requested(self):
        self.widget.set_histogram([1, 2], [1, 2, 3])
        changes = []
        self.widget.limitsChanged.connect(
            lambda low, high: changes.append((low, high)))
        self.widget.set_limits(1.25, 2.75)
        self.assertEqual(changes, [])
        self.widget.set_limits(1.5, 2.5, emit=True)
        self.assertEqual(changes, [(1.5, 2.5)])

    def test_switching_scale_preserves_actual_limits(self):
        counts = [1, 2]
        self.widget.set_histogram(counts, [0.1, 1, 10])
        self.widget.set_limits(0.2, 5)
        self.widget.set_histogram(
            counts, [0.1, 1, 10], logarithmic=True, reset_view=False)
        np.testing.assert_allclose(self.widget.limits, (0.2, 5))
        self.assertAlmostEqual(
            self.widget.minimum_marker.value(), np.log10(0.2))
        self.assertAlmostEqual(
            self.widget.maximum_marker.value(), np.log10(5))

    def test_invalid_histograms_and_limits_are_rejected(self):
        invalid = (
            ([1, 2], [0, 1]),
            ([1, -1], [0, 1, 2]),
            ([1, 2], [0, 2, 1]),
            ([1, np.nan], [0, 1, 2]),
        )
        for counts, edges in invalid:
            with self.subTest(counts=counts, edges=edges), self.assertRaises(ValueError):
                self.widget.set_histogram(counts, edges)
        with self.assertRaises(ValueError):
            self.widget.set_histogram([1, 2], [0, 1, 2], logarithmic=True)

        self.widget.set_histogram([1, 2], [1, 2, 3])
        for limits in ((0, 2), (2.5, 2), (1, 4)):
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                self.widget.set_limits(*limits)


if __name__ == "__main__":
    unittest.main()
