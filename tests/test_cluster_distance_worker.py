"""Check asynchronous null statistics, caching, and stale-result isolation."""

import os
from concurrent.futures import CancelledError
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pytest
from qtpy import QtCore, QtWidgets

from exhale.analysis import correlation_controller as module
from exhale.analysis.cluster_distances import RandomPlacementStatistics, random_placement_statistics
from exhale.data.plotsettings import CLUSTER_DISTANCES, MatrixPlotSettings

_APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _controller():
    window = QtWidgets.QWidget()
    channels = {}
    for index, count in enumerate((2, 3, 4)):
        channels[str(index)] = SimpleNamespace(
            name=str(index),
            cluster_df=pd.DataFrame(
                [(row, index) for row in range(count)],
                columns=("centroid-0", "centroid-1"),
            ),
            cluster_labels=np.ones((5, 5), dtype=int),
        )
    result = SimpleNamespace(
        xrf_sample=SimpleNamespace(elements=channels), element_refs=("a", "b", "c")
    )
    window.clusterDistanceSample = QtWidgets.QComboBox()
    window.clusterDistanceSample.addItem("sample", "sample")
    window.clusterDistanceMethod = QtWidgets.QComboBox()
    window.clusterDistanceMethod.addItem("method", "method")
    window.clusterDistanceValue = QtWidgets.QComboBox()
    window.clusterDistanceValue.addItems(
        ("Distance", "Pixels", "Null-model normalized", "Null-model percentile")
    )
    window.clusterDistanceSecondary = QtWidgets.QCheckBox()
    window.showClusterDistanceValues = QtWidgets.QCheckBox()
    window.clusterDistanceDecimals = QtWidgets.QSpinBox()
    window.clusterDistanceDecimalsLabel = QtWidgets.QLabel()
    window.clusterDistanceMinimum = QtWidgets.QSpinBox()
    window.clusterDistancePlotHost = QtWidgets.QWidget()
    window.clusterDistanceStatus = QtWidgets.QLabel()
    settings = MatrixPlotSettings(normalize_to_random=True, distance_secondary="observed")
    window.project_data = SimpleNamespace(
        segmentation_result=lambda *_: result,
        image_defaults=SimpleNamespace(resolution=(2.0, "µm")),
        matrix_plot_settings={CLUSTER_DISTANCES: settings},
    )
    controller = module.CorrelationController.__new__(module.CorrelationController)
    QtCore.QObject.__init__(controller, window)
    controller.window = window
    controller._distance_generation = 0
    controller._distance_request = None
    controller._null_workers = {}
    controller._distance_cache = {}
    controller._null_cache = {}
    controller.distance_matrix = SimpleNamespace(set_result=Mock(), plot=QtWidgets.QWidget())
    controller._distance_placeholder = QtWidgets.QLabel()
    return controller, window, settings


def test_worker_cache_filter_resolution_and_secondary_values(monkeypatch):
    calls = []
    null = RandomPlacementStatistics(
        np.full((3, 3), 4.0),
        np.ones((3, 3)),
        np.ones((3, 3)),
        np.array((2, 3, 4)),
        1000,
        np.full((3, 3), 25.0),
    )

    def simulate(counts, masks, **_kwargs):
        calls.append((counts, masks))
        assert not counts.flags.writeable
        assert all(not mask.flags.writeable for mask in masks)
        return null

    monkeypatch.setattr(module, "random_placement_statistics", simulate)
    controller, window, settings = _controller()
    try:
        controller.calculate_distances(show_errors=False)
        assert controller.distance_matrix.set_result.call_args.args[0] is None
        loop = QtCore.QEventLoop()
        timer = QtCore.QTimer()
        timer.timeout.connect(lambda: loop.quit() if controller._null_workers == {} else None)
        timer.start(5)
        QtCore.QTimer.singleShot(3000, loop.quit)
        loop.exec()
        assert not controller._null_workers
        assert len(calls) == 1
        matrix = controller.distance_matrix.set_result.call_args.args[0]
        observed = next(iter(controller._distance_cache.values()))
        np.testing.assert_allclose(
            matrix.standard_deviations, observed.standard_deviations / 4.0, equal_nan=True
        )
        assert matrix.normalized
        window.clusterDistanceMinimum.setValue(3)
        controller.calculate_distances(show_errors=False)
        assert controller.distance_matrix.set_result.call_args.args[0].values.shape == (2, 2)
        assert len(calls) == 1
        for normalized in (False, True):
            for secondary in ("none", "observed"):
                settings.normalize_to_random = normalized
                settings.distance_secondary = secondary
                window.project_data.image_defaults.resolution = (3.0, "µm")
                controller.calculate_distances(show_errors=False)
                matrix = controller.distance_matrix.set_result.call_args.args[0]
                assert matrix.normalized == normalized
        settings.normalize_to_random = False
        settings.distance_pixels = True
        controller.calculate_distances(show_errors=False)
        pixel_matrix = controller.distance_matrix.set_result.call_args.args[0]
        np.testing.assert_allclose(pixel_matrix.values, observed.values[1:, 1:])
        np.testing.assert_allclose(
            pixel_matrix.standard_deviations, observed.standard_deviations[1:, 1:]
        )
        assert pixel_matrix.units == "px"
        settings.distance_pixels = False
        settings.distance_percentile = True
        settings.normalize_to_random = False
        controller.calculate_distances(show_errors=False)
        matrix = controller.distance_matrix.set_result.call_args.args[0]
        np.testing.assert_allclose(matrix.values, 25.0)
        assert matrix.percentile
        controller.distance_matrix.result = matrix
        spec = controller._distance_spec(matrix.values, matrix.labels)
        assert spec.levels == (0.0, 100.0)
        assert spec.color_bar_label == "Null-model percentile (%)"
        assert spec.decimals == 1
        assert not spec.show_secondary
        controller.distance_matrix.result = replace(matrix, simulations=10000)
        assert controller._distance_spec(matrix.values, matrix.labels).decimals == 2
        assert not window.clusterDistanceSecondary.isEnabled()
        assert len(calls) == 1
    finally:
        controller.shutdown()
        window.close()


def test_late_result_cannot_replace_another_request_or_project():
    controller, window, _settings = _controller()
    try:
        controller._distance_request = (0, "new sample")
        controller._null_completed((0, "old sample"), object(), None)
        controller.distance_matrix.set_result.assert_not_called()
        assert (0, "old sample") in controller._null_cache
        controller._cancel_null_workers()
        controller._null_completed((0, "old project"), object(), None)
        assert (0, "old project") not in controller._null_cache
        controller.distance_matrix.set_result.assert_not_called()
    finally:
        controller.shutdown()
        window.close()


def test_simulation_supports_cooperative_cancellation():
    with pytest.raises(CancelledError):
        random_placement_statistics((2, 3), (np.ones((5, 5)),), cancelled=lambda: True)


def test_worker_error_clears_busy_placeholder():
    controller, window, _settings = _controller()
    try:
        signature = (0, "sample")
        controller._distance_request = signature
        controller._distance_placeholder.show()
        window.clusterDistancePlotHost.setCursor(QtCore.Qt.BusyCursor)
        controller._null_completed(
            signature, None, "The segmented elements contain no cluster regions"
        )
        assert controller._distance_placeholder.isHidden()
        assert window.clusterDistancePlotHost.cursor().shape() != QtCore.Qt.BusyCursor
        assert "no cluster regions" in window.clusterDistanceStatus.text()
        assert controller.distance_matrix.set_result.call_args.args == (None,)
    finally:
        controller.shutdown()
        window.close()
