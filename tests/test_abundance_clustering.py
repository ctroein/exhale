"""Abundance support, spatial links, ToMATo prominence, persistence and options."""

from importlib.util import find_spec
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest
from qtpy import QtCore, QtTest, QtWidgets
from skimage.measure import label

from exhale.analysis.abundance_clustering_options_dialog import AbundanceClusteringOptionsDialog
from exhale.analysis.clustering_abundance import (
    abundance_statistics,
    cluster_channel,
    compute,
    estimate_cutoff,
    validate_options,
)
from exhale.analysis.clusteringmethods import CLUSTERING_METHODS
from exhale.analysis.segmentationio import load_xrf_sample, save_xrf_sample
from exhale.data.channeldata import ArrayChannelData
from exhale.data.projectdata import Channel, ClusteringParameters, ClusteringResult, ProjectData
from exhale.data.source_refs import ElementRef
from exhale.project.projectio import export_project_state, load_project_state

METHODS = [
    "cutoff-proximity",
    pytest.param(
        "tomato", marks=pytest.mark.skipif(find_spec("gudhi") is None, reason="GUDHI absent")
    ),
]


def fragmented_peaks():
    raw = np.zeros((60, 100))
    raw[10:25:2, 10:25:2] = 10
    raw[10:25:2, 65:80:2] = 10
    raw[16, 30:65:8] = 10
    raw[50, 50] = 10
    return raw


def test_method_chooser_replaces_hdbscan():
    assert {method.method_id for method in CLUSTERING_METHODS} == {
        "intensity-partition",
        "cutoff-proximity",
        "tomato",
    }


@pytest.mark.parametrize("method_id", METHODS)
def test_fragmented_regions_are_measured_without_filling_gaps(method_id):
    raw = fragmented_peaks()
    before = raw.copy()
    result = cluster_channel(raw, "Fe", {"min_cluster_size": 15}, method_id=method_id)
    labels = result.cluster_labels
    left, right = labels[10, 10], labels[10, 65]
    assert left > 0 and right > 0 and left != right
    assert np.all(labels[10:25:2, 10:25:2] == left)
    assert np.all(labels[10:25:2, 65:80:2] == right)
    assert labels[50, 50] == 0
    assert not labels[raw == 0].any()
    assert len(result.cluster_df) == 2
    for row in result.cluster_df.to_dict("records"):
        coordinates = np.argwhere(labels == row["label"])
        assert label(labels == row["label"]).max() > 1
        assert row["area"] == len(coordinates)
        assert row["mean_intensity"] == 10
        np.testing.assert_allclose([row["centroid-0"], row["centroid-1"]], coordinates.mean(axis=0))
    np.testing.assert_array_equal(raw, before)


def test_raw_median_and_difference_mad_define_the_automatic_cutoff():
    raw = np.arange(25, dtype=float).reshape(5, 5)
    differences = np.r_[np.diff(raw, axis=0).ravel(), np.diff(raw, axis=1).ravel()]
    scale = np.median(np.abs(differences - np.median(differences))) / (
        0.6744897501960817 * np.sqrt(2)
    )
    assert abundance_statistics(raw) == (12, scale)
    channel = cluster_channel(raw, "Fe", {}, method_id="cutoff-proximity")
    assert channel.intensity_thresholds[0] == 12 + 3 * scale
    assert not channel.cluster_labels[raw <= 12 + 3 * scale].any()
    outlier = raw.copy()
    outlier[-1, -1] = 1e6
    bounded = abundance_statistics(outlier)
    outlier[-1, -1] = 1e9
    assert abundance_statistics(outlier) == bounded


def test_contrast_estimate_matches_supported_window_means_and_abundance_scaling():
    raw = np.arange(100, dtype=float).reshape(10, 10)
    raw[4:8, 3:7] += 100
    raw[5, 4] = np.nan
    estimate = estimate_cutoff(raw, 10)
    windows = np.lib.stride_tricks.sliding_window_view(raw, (4, 4))
    counts = np.isfinite(windows).sum(axis=(-1, -2))
    means = np.nanmean(windows, axis=(-1, -2))
    assert estimate.window == (4, 4)
    assert estimate.baseline == np.nanmedian(raw)
    assert estimate.bright == pytest.approx(means[counts >= 10].max())
    assert estimate.contrast_cutoff == pytest.approx(
        estimate.baseline + 0.10 * (estimate.bright - estimate.baseline)
    )
    assert estimate.baseline + estimate.multiple * estimate.scale == pytest.approx(estimate.cutoff)
    scaled = estimate_cutoff(raw * 5 + 7, 10)
    assert scaled.cutoff == pytest.approx(estimate.cutoff * 5 + 7)
    assert scaled.multiple == pytest.approx(estimate.multiple)


def test_contrast_estimate_handles_narrow_insufficient_and_zero_scale_maps():
    narrow = estimate_cutoff(np.arange(20, dtype=float).reshape(1, 20), 10)
    assert narrow.window == (1, 10)
    assert narrow.multiple is None
    assert estimate_cutoff(np.ones((8, 8)), 10) is None
    assert estimate_cutoff(np.full((8, 8), np.nan), 10) is None
    assert estimate_cutoff(np.eye(2), 10) is None


def cutoff_project():
    project = ProjectData()
    for index, name in enumerate(("First", "Second")):
        sample = project.create_sample(name)
        for key, power in (("Fe", 1), ("Zn", 2)):
            if index == 1 and key == "Zn":
                continue
            raw = np.arange(100, dtype=float).reshape(10, 10) ** power + index
            sample.channels[key] = Channel(
                key,
                key,
                ElementRef(f"source{index}", key),
                data_source=ArrayChannelData(raw),
            )
            project.add_project_channel_from_sample(sample.sample_id, key)
    return project


def test_cutoff_overview_background_estimates_and_sample_specific_overrides():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    project = cutoff_project()
    first, second = project.samples.values()
    dialog = AbundanceClusteringOptionsDialog(method_id="cutoff-proximity")
    dialog.set_context(project, first)
    assert dialog.thresholdTable.rowCount() == 2
    assert dialog.thresholdTable.columnCount() == 2
    assert dialog.thresholdTable.cellWidget(1, 1) is None
    dialog.show()
    for _ in range(100):
        app.processEvents()
        QtTest.QTest.qWait(5)
        if len(dialog._estimates) == 3:
            break
    assert len(dialog._estimates) == 3
    cell = dialog._cells[first.sample_id, "Fe"]
    assert cell.multiple.value() == pytest.approx(
        round(dialog._estimates[first.sample_id, "Fe"].multiple, 2)
    )
    assert "Contrast fraction = 0.1" in dialog.cutoffDetails.toPlainText()
    cell.auto.setChecked(False)
    cell.multiple.setValue(1.5)
    assert project.clustering_settings.cutoffs == {first.sample_id: {"Fe": 1.5}}
    assert (
        project.clustering_settings.parameters(second.sample_id, "tomato").method_options[
            "cutoff_scales"
        ]
        == {}
    )
    dialog.minClusterSize.setValue(20)
    dialog.set_method("tomato")
    dialog.set_context(project, second)
    assert dialog._cells[first.sample_id, "Fe"].multiple.value() == 1.5
    assert project.clustering_settings.parameters(first.sample_id, "tomato").method_options[
        "cutoff_scales"
    ] == {"Fe": 1.5}
    dialog.close()
    dialog.stop_estimates()
    dialog.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def test_restore_all_auto_clears_overrides_and_reuses_calculated_values():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    project = cutoff_project()
    first, second = project.samples.values()
    project.clustering_settings.cutoffs = {
        first.sample_id: {"Fe": 1.5},
        second.sample_id: {"Fe": 5, "Zn": 7},
    }
    dialog = AbundanceClusteringOptionsDialog(method_id="tomato")
    dialog.set_context(project, first)
    for pair, source in dialog._inputs.items():
        dialog._estimates[pair] = estimate_cutoff(source.array(), dialog.minClusterSize.value())
    cached = dict(dialog._estimates)
    changes = QtTest.QSignalSpy(dialog.settingsChanged)
    assert dialog.restoreAuto.isEnabled()
    dialog.restoreAuto.click()
    assert not project.clustering_settings.cutoffs
    assert not dialog.restoreAuto.isEnabled()
    assert len(changes) == 1
    assert dialog._estimates == cached
    assert dialog._worker is None
    for pair, cell in dialog._cells.items():
        assert cell.auto.isChecked()
        assert not cell.multiple.isEnabled()
        assert cell.multiple.value() == pytest.approx(round(cached[pair].multiple, 2))
    dialog.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def test_cutoff_enter_commits_without_restoring_and_tab_moves_widget_focus():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    project = cutoff_project()
    first = next(iter(project.samples.values()))
    dialog = AbundanceClusteringOptionsDialog(method_id="tomato")
    dialog.set_context(project, first)
    dialog.show()
    app.processEvents()
    cell = dialog._cells[first.sample_id, "Fe"]
    next_cell = dialog._cells[first.sample_id, "Zn"]
    try:
        cell.auto.setChecked(False)
        cell.multiple.setFocus()
        cell.multiple.selectAll()
        QtTest.QTest.keyClicks(cell.multiple, "6.5")
        QtTest.QTest.keyClick(cell.multiple, QtCore.Qt.Key.Key_Return)
        app.processEvents()
        assert project.clustering_settings.cutoffs[first.sample_id]["Fe"] == 6.5
        assert not cell.auto.isChecked()
        assert dialog.isVisible()
        assert cell.multiple.hasFocus()
        QtTest.QTest.keyClick(cell.multiple, QtCore.Qt.Key.Key_Up)
        assert cell.multiple.value() == 7
        QtTest.QTest.keyClick(cell.multiple, QtCore.Qt.Key.Key_Down)
        assert cell.multiple.value() == 6.5
        QtTest.QTest.keyClick(cell.multiple, QtCore.Qt.Key.Key_Tab)
        assert next_cell.auto.hasFocus()
        assert dialog.thresholdTable.currentColumn() == 1
        QtTest.QTest.keyClick(next_cell.auto, QtCore.Qt.Key.Key_Backtab)
        assert cell.multiple.hasFocus()
        assert dialog.thresholdTable.currentColumn() == 0
    finally:
        dialog.close()
        dialog.stop_estimates()
        dialog.deleteLater()
        app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def test_auto_previews_run_off_the_gui_thread_and_keep_manual_values(monkeypatch):
    from exhale.analysis import abundance_clustering_options_dialog as module

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    entered, release = Event(), Event()
    real_estimate = module.estimate_cutoff

    def blocked(raw, minimum):
        entered.set()
        assert release.wait(3)
        return real_estimate(raw, minimum)

    monkeypatch.setattr(module, "estimate_cutoff", blocked)
    project = cutoff_project()
    sample = next(iter(project.samples.values()))
    project.clustering_settings.cutoffs[sample.sample_id] = {"Fe": 5}
    dialog = AbundanceClusteringOptionsDialog(method_id="tomato")
    dialog.set_context(project, sample)
    try:
        dialog.show()
        assert entered.wait(1)
        ticks = []
        QtCore.QTimer.singleShot(0, lambda: ticks.append(True))
        app.processEvents()
        assert ticks == [True]
        release.set()
        for _ in range(100):
            app.processEvents()
            QtTest.QTest.qWait(5)
            if len(dialog._estimates) == 3:
                break
        assert len(dialog._estimates) == 3
        cell = dialog._cells[sample.sample_id, "Fe"]
        assert cell.multiple.value() == 5
        assert not cell.auto.isChecked()
    finally:
        release.set()
        dialog.close()
        dialog.stop_estimates()
        dialog.deleteLater()
        app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def test_low_contrast_auto_estimate_has_a_two_s_floor():
    raw = np.random.default_rng(23).normal(10, 1, (30, 30))
    estimate = estimate_cutoff(raw, 10)
    assert 0 < estimate.uncapped_multiple < 2
    assert estimate.multiple == 2
    assert estimate.cutoff == pytest.approx(estimate.baseline + 2 * estimate.scale)


def test_small_positive_scale_produces_a_capped_available_estimate():
    raw = np.random.default_rng(42).normal(1, 0.001, (30, 30))
    raw[10:15, 10:15] += 100
    estimate = estimate_cutoff(raw, 10)
    assert estimate.scale > 0
    assert estimate.uncapped_multiple > 1000
    assert estimate.multiple == 15
    assert estimate.cutoff == pytest.approx(estimate.baseline + 15 * estimate.scale)


@pytest.mark.parametrize("method_id", METHODS)
def test_auto_cutoff_execution_uses_each_map_and_respects_overrides(method_id):
    raw = np.arange(100, dtype=float).reshape(10, 10)
    job = SimpleNamespace(sample_name="test", keys=("Fe", "Zn"), names=("Fe", "Zn"))
    options = {"auto_cutoff": True, "cutoff_scales": {"Zn": 1.5}}
    output = compute(
        [raw, raw**2],
        job,
        ClusteringParameters(method_options=options),
        lambda text: None,
        method_id=method_id,
    )
    assert output.elements["Fe"].intensity_thresholds[0] == pytest.approx(
        estimate_cutoff(raw, 10).cutoff
    )
    median, scale = abundance_statistics(raw**2)
    assert output.elements["Zn"].intensity_thresholds[0] == pytest.approx(median + 1.5 * scale)
    second = compute(
        [raw**3, raw**2],
        job,
        ClusteringParameters(method_options=options),
        lambda text: None,
        method_id=method_id,
    )
    assert second.elements["Fe"].intensity_thresholds[0] == pytest.approx(
        estimate_cutoff(raw**3, 10).cutoff
    )
    assert (
        second.elements["Fe"].intensity_thresholds[0]
        != output.elements["Fe"].intensity_thresholds[0]
    )


@pytest.mark.parametrize("method_id", METHODS)
def test_auto_cutoff_without_positive_scale_uses_saved_shared_multiple(method_id):
    raw = np.arange(20, dtype=float).reshape(1, 20)
    job = SimpleNamespace(sample_name="test", keys=("Fe",), names=("Fe",))
    output = compute(
        [raw],
        job,
        ClusteringParameters(method_options={"auto_cutoff": True}),
        lambda text: None,
        method_id=method_id,
    )
    assert output.elements["Fe"].intensity_thresholds[0] == np.median(raw)


@pytest.mark.parametrize("method_id", METHODS)
def test_element_cutoff_multiple_uses_each_samples_abundance_scale(method_id):
    raw = np.arange(25, dtype=float).reshape(5, 5)
    job = SimpleNamespace(sample_name="test", keys=("Fe",), names=("Iron",))
    parameters = ClusteringParameters(method_options={"cutoff_scales": {"Fe": 1.0}})
    original = compute([raw], job, parameters, lambda text: None, method_id=method_id)
    scaled = compute([raw * 10 + 7], job, parameters, lambda text: None, method_id=method_id)
    median, scale = abundance_statistics(raw)
    first, second = original.elements["Fe"], scaled.elements["Fe"]
    assert first.intensity_thresholds[0] == pytest.approx(median + scale)
    assert second.intensity_thresholds[0] == pytest.approx((median + scale) * 10 + 7)
    np.testing.assert_array_equal(first.cluster_labels, second.cluster_labels)


@pytest.mark.parametrize("method_id", METHODS)
def test_manual_cutoff_and_link_distance_have_separate_effects(method_id):
    raw = np.zeros((7, 7))
    raw[2, 2] = raw[2, 4] = 10
    options = {"min_cluster_size": 2, "radius": 2}
    linked = cluster_channel(raw, "Fe", options, method_id=method_id, threshold=5)
    assert linked.cluster_labels[2, 2] == linked.cluster_labels[2, 4] > 0
    assert linked.cluster_labels[2, 3] == 0
    assert linked.intensity_thresholds.tolist() == [5]
    separate = cluster_channel(
        raw, "Fe", {**options, "radius": 1}, method_id=method_id, threshold=5
    )
    assert not separate.cluster_labels.any()
    rejected = cluster_channel(raw, "Fe", options, method_id=method_id, threshold=10)
    assert not rejected.cluster_labels.any()


@pytest.mark.skipif(find_spec("gudhi") is None, reason="GUDHI absent")
def test_prominence_merges_peaks_without_changing_abundance_support():
    raw = np.array([[0.0, 10.0, 8.0, 9.0, 0.0]])
    options = {"min_cluster_size": 1, "radius": 1}
    weak = cluster_channel(
        raw, "Fe", {**options, "prominence": 0.1}, method_id="tomato", threshold=5
    )
    strong = cluster_channel(
        raw, "Fe", {**options, "prominence": 1}, method_id="tomato", threshold=5
    )
    assert len(weak.cluster_df) == 2
    assert len(strong.cluster_df) == 1
    np.testing.assert_array_equal(weak.cluster_labels > 0, strong.cluster_labels > 0)


@pytest.mark.parametrize("method_id", METHODS)
@pytest.mark.parametrize("raw", [np.full((10, 10), 4.0), np.full((4, 5), np.nan), np.eye(4)])
def test_uniform_invalid_and_insufficient_maps_return_empty_results(method_id, raw):
    channel = cluster_channel(raw, "Fe", {"min_cluster_size": 20}, method_id=method_id)
    assert not channel.cluster_labels.any()
    assert channel.cluster_df.empty
    assert {"label", "area", "mean_intensity", "centroid-0", "centroid-1"} == set(
        channel.cluster_df
    )


@pytest.mark.parametrize("method_id", METHODS)
def test_invalid_pixels_remain_background_and_leave_finite_measurements(method_id):
    raw = fragmented_peaks()
    raw[11, 11], raw[12, 11] = np.nan, np.inf
    channel = cluster_channel(raw, "Fe", {}, method_id=method_id)
    assert not channel.cluster_labels[~np.isfinite(raw)].any()
    assert np.isfinite(channel.cluster_df.to_numpy()).all()


@pytest.mark.parametrize(
    "options",
    [
        {"min_cluster_size": 0},
        {"min_cluster_size": True},
        {"min_cluster_size": 2.5},
        {"radius": 0.5},
        {"radius": np.inf},
        {"cutoff_scale": -1},
        {"auto_cutoff": "true"},
        {"cutoff_scales": {"Fe": -1}},
        {"cutoff_scales": {"Fe": np.nan}},
        {"prominence": np.nan},
        {"thresholds": {"Fe": np.nan}},
        {"thresholds": {"Fe": True}},
        {"thresholds": {"Fe": 1j}},
        {"thresholds": []},
    ],
)
def test_invalid_options_are_rejected(options):
    with pytest.raises(ValueError):
        validate_options(options, tomato=True)


@pytest.mark.parametrize("method_id", METHODS)
def test_fragmented_labels_and_actual_cutoff_roundtrip(tmp_path, method_id):
    job = SimpleNamespace(sample_name="test", keys=("Fe",), names=("Iron",))
    output = compute(
        [fragmented_peaks()], job, ClusteringParameters(), lambda text: None, method_id=method_id
    )
    path = tmp_path / "clusters.h5"
    save_xrf_sample(output, path, method_id=method_id)
    restored = load_xrf_sample(path, expected_method_id=method_id)
    original, copied = output.elements["Fe"], restored.elements["Fe"]
    np.testing.assert_array_equal(original.cluster_labels, copied.cluster_labels)
    np.testing.assert_array_equal(original.intensity_thresholds, copied.intensity_thresholds)
    np.testing.assert_allclose(original.cluster_df, copied.cluster_df)


@pytest.mark.parametrize("method_id", METHODS)
def test_cancellation_discards_the_current_element(method_id):
    job = SimpleNamespace(sample_name="test", keys=("Fe",), names=("Iron",))

    def cancel(text):
        if "measuring abundance clusters" in text:
            raise InterruptedError("stop")

    with pytest.raises(InterruptedError):
        compute([fragmented_peaks()], job, ClusteringParameters(), cancel, method_id=method_id)


@pytest.mark.parametrize("method_id", ("cutoff-proximity", "tomato"))
def test_cutoff_settings_persist_without_results(method_id):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    project = cutoff_project()
    sample = next(iter(project.samples.values()))
    dialog = AbundanceClusteringOptionsDialog(method_id=method_id)
    dialog.set_context(project, sample)
    cell = dialog._cells[sample.sample_id, "Fe"]
    cell.auto.setChecked(False)
    cell.multiple.setValue(2.5)
    dialog.minClusterSize.setValue(31)
    dialog.linkRadius.setValue(2.5)
    parameters = dialog.parameters()
    assert parameters.method_options["cutoff_scales"] == {"Fe": 2.5}
    restored = ProjectData()
    assert not load_project_state(restored, export_project_state(project), open_files=False)
    assert restored.clustering_settings.parameters(sample.sample_id, method_id) == parameters
    assert not restored.clustering_results
    dialog.close()
    dialog.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def test_retired_hdbscan_selection_becomes_cutoff_proximity():
    project = ProjectData()
    state = export_project_state(project)
    state["clustering_method"] = "hdbscan"
    assert not load_project_state(project, state, open_files=False)
    assert project.clustering_method == "cutoff-proximity"


@pytest.mark.parametrize("method_id", METHODS)
def test_switching_auto_to_same_manual_cutoff_reuses_clusters(method_id, monkeypatch):
    rng = np.random.default_rng(12)
    raw = rng.normal(10, 1, (30, 30))
    raw[10:20, 10:20] += 30
    ref = ElementRef("test", "Fe")
    job = SimpleNamespace(sample_name="test", keys=("Fe",), names=("Fe",), refs=(ref,))
    parameters = ClusteringParameters(method_options={"auto_cutoff": True})
    output = compute([raw], job, parameters, lambda _: None, method_id=method_id)
    previous = ClusteringResult("test", (ref,), parameters, output, method_id=method_id)
    multiple = estimate_cutoff(raw, 10).multiple
    manual = ClusteringParameters(
        method_options={"auto_cutoff": True, "cutoff_scales": {"Fe": multiple}}
    )

    def unexpected_clustering(*args, **kwargs):
        pytest.fail("Unchanged effective cutoff must reuse the saved clusters")

    monkeypatch.setattr(
        "exhale.analysis.clustering_abundance.cluster_channel", unexpected_clustering
    )
    reused = compute([raw], job, manual, lambda _: None, method_id=method_id, previous=previous)
    assert reused.elements["Fe"] is output.elements["Fe"]
