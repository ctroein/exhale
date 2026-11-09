"""Spatial separation, fragmented-region measurements, thresholds and HDBSCAN persistence."""

from types import SimpleNamespace

import numpy as np
import pytest
from qtpy import QtCore, QtWidgets
from skimage.measure import label

from exhale.analysis.clustering_hdbscan import cluster_channel, compute, validate_options
from exhale.analysis.hdbscan_options_dialog import HdbscanOptionsDialog
from exhale.analysis.segmentationio import load_xrf_sample, save_xrf_sample
from exhale.data.projectdata import ClusteringParameters


def fragmented_peaks():
    raw = np.zeros((60, 100))
    raw[10:25:2, 10:25:2] = 10
    raw[10:25:2, 65:80:2] = 10
    raw[16, 30:65:8] = 10
    raw[50, 50] = 10
    return raw


def test_sparse_bridge_does_not_merge_dense_fragmented_regions_or_fill_gaps():
    raw = fragmented_peaks()
    before = raw.copy()
    result = cluster_channel(raw, "Fe", minimum=15, support=5)
    labels = result.cluster_labels
    left, right = labels[10, 10], labels[10, 65]
    assert left > 0 and right > 0 and left != right
    assert np.all(labels[10:25:2, 10:25:2] == left)
    assert np.all(labels[10:25:2, 65:80:2] == right)
    assert labels[50, 50] == 0
    assert not labels[raw == 0].any()
    assert len(result.cluster_df) == 2
    assert 0 < result.intensity_thresholds[0] < 10
    for row in result.cluster_df.to_dict("records"):
        coordinates = np.argwhere(labels == row["label"])
        assert label(labels == row["label"]).max() > 1
        assert row["area"] == len(coordinates)
        assert row["mean_intensity"] == 10
        np.testing.assert_allclose([row["centroid-0"], row["centroid-1"]], coordinates.mean(axis=0))
    np.testing.assert_array_equal(raw, before)


def test_otsu_uses_raw_abundances_and_manual_cutoff_overrides_it():
    raw = fragmented_peaks() * 3 + 7
    result = cluster_channel(raw, "Fe", minimum=15, support=5)
    assert 7 < result.intensity_thresholds[0] < 37
    assert result.cluster_labels.any()
    manual = cluster_channel(raw, "Fe", minimum=15, support=5, threshold=37)
    assert not manual.cluster_labels.any()
    assert manual.intensity_thresholds.tolist() == [37]


@pytest.mark.parametrize("raw", [np.full((10, 10), 4.0), np.full((4, 5), np.nan), np.eye(4)])
def test_uniform_invalid_and_insufficient_maps_return_empty_measured_results(raw):
    channel = cluster_channel(raw, "Fe", minimum=20, support=5)
    assert not channel.cluster_labels.any()
    assert channel.cluster_df.empty
    assert set(channel.cluster_df) == {
        "label",
        "area",
        "mean_intensity",
        "centroid-0",
        "centroid-1",
    }


def test_invalid_pixels_remain_background_and_do_not_corrupt_measurements():
    raw = fragmented_peaks()
    raw[11, 11] = np.nan
    raw[12, 11] = np.inf
    channel = cluster_channel(raw, "Fe", minimum=15, support=5)
    assert not channel.cluster_labels[~np.isfinite(raw)].any()
    assert np.isfinite(channel.cluster_df.to_numpy()).all()


def test_one_cluster_is_allowed():
    raw = np.zeros((30, 30))
    raw[8:20:2, 8:20:2] = 10
    channel = cluster_channel(raw, "Fe", minimum=10, support=4)
    assert channel.cluster_df.shape[0] == 1


@pytest.mark.parametrize(
    "options",
    [
        {"min_cluster_size": 1},
        {"min_cluster_size": True},
        {"min_cluster_size": 2.5},
        {"min_samples": 0},
        {"thresholds": {"Fe": np.nan}},
        {"thresholds": {"Fe": np.inf}},
        {"thresholds": {"Fe": True}},
        {"thresholds": {"Fe": 1j}},
        {"thresholds": []},
    ],
)
def test_invalid_options_are_rejected(options):
    with pytest.raises(ValueError):
        validate_options(options)


def test_actual_cutoff_and_fragmented_labels_roundtrip_without_relabelling(tmp_path):
    raw = fragmented_peaks()
    job = SimpleNamespace(sample_name="test", keys=("Fe",), names=("Iron",))
    parameters = ClusteringParameters(method_options={"min_cluster_size": 15, "min_samples": 5})
    output = compute([raw], job, parameters, lambda text: None)
    path = tmp_path / "hdbscan.h5"
    save_xrf_sample(output, path, method_id="hdbscan")
    restored = load_xrf_sample(path, expected_method_id="hdbscan")
    original, copied = output.elements["Fe"], restored.elements["Iron"]
    np.testing.assert_array_equal(original.cluster_labels, copied.cluster_labels)
    np.testing.assert_array_equal(original.intensity_thresholds, copied.intensity_thresholds)
    np.testing.assert_allclose(original.cluster_df, copied.cluster_df)


def test_cancellation_after_fit_discards_the_current_element():
    job = SimpleNamespace(sample_name="test", keys=("Fe",), names=("Iron",))
    parameters = ClusteringParameters(method_options={"min_cluster_size": 15, "min_samples": 5})

    def cancel_after_fit(text):
        if "measuring HDBSCAN" in text:
            raise InterruptedError("stop")

    with pytest.raises(InterruptedError):
        compute([fragmented_peaks()], job, parameters, cancel_after_fit)


def test_cutoff_drafts_and_settings_survive_sample_switches_and_restore():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    channels = {key: SimpleNamespace(name=key, key=key) for key in ("Fe", "Zn")}
    sample = SimpleNamespace(effective_channels=lambda _: channels)
    project = SimpleNamespace(project_channels={}, abundance_units="ng/mm²")
    dialog = HdbscanOptionsDialog()
    dialog.set_context(project, sample)
    assert dialog.parameters().method_options == {
        "min_cluster_size": 20,
        "min_samples": 5,
        "thresholds": {},
    }
    dialog.thresholdTable.item(0, 1).setCheckState(QtCore.Qt.CheckState.Unchecked)
    with pytest.raises(ValueError, match="Fe"):
        dialog.parameters()
    dialog.set_context(project, sample)  # An unfinished edit must not break a Qt callback.
    editor = dialog.thresholdTable.cellWidget(0, 2)
    assert editor.isEnabled()
    editor.setText("1.23456789e-12")
    dialog.minClusterSize.setValue(31)
    dialog.densitySupport.setValue(7)
    parameters = dialog.parameters()
    assert parameters.method_options["thresholds"] == {"Fe": 1.23456789e-12}
    dialog.set_context(project, None)
    assert dialog.parameters() == parameters
    dialog.set_parameters(parameters)
    dialog.set_context(project, sample)
    assert dialog.parameters() == parameters
    dialog.thresholdTable.item(0, 1).setCheckState(QtCore.Qt.CheckState.Checked)
    assert dialog.parameters().method_options["thresholds"] == {}
    dialog.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
