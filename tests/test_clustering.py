"""Method ownership, fixed batch inputs, incremental results and failure isolation."""

from dataclasses import replace
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import Mock, patch
from weakref import WeakKeyDictionary

import h5py
import numpy as np
import pytest
from qtpy import QtCore, QtTest, QtWidgets

from exhale.analysis.clustering_batch_dialog import ClusteringBatchDialog
from exhale.analysis.clusteringbatch import ClusteringBatchWorker
from exhale.analysis.clusteringmethods import CLUSTERING_METHODS
from exhale.analysis.controller import AnalysisController
from exhale.analysis.segmentationio import clustering_relative_path, save_xrf_sample
from exhale.data.clustering import DEFAULT_CLUSTERING_METHOD, clustering_job
from exhale.data.projectdata import ClusteringParameters, ClusteringResult, ProjectData
from exhale.data.source_refs import open_source
from exhale.main_window import MainWindow
from exhale.project import projectio
from exhale.project.projectio import load_project, save_project


@pytest.fixture
def project(tmp_path):
    model = ProjectData()
    for index in range(3):
        path = tmp_path / f"sample{index}.h5"
        with h5py.File(path, "w") as handle:
            handle.attrs["default"] = "entry"
            group = handle.create_group("entry/plotselect")
            for key in ("P", "Fe", "Zn"):
                group[key] = np.arange(96, dtype=float).reshape(8, 12) + index + 1
        sample = model.register_source(open_source(str(path)))
        for key in sample.channels:
            model.add_project_channel_from_sample(sample.sample_id, key)
    yield model
    model.clear()


def jobs(project):
    return tuple(clustering_job(project, sample) for sample in project.samples.values())


@pytest.fixture
def window(project, tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    with patch.object(AnalysisController, "setup", lambda *args, **kwargs: None):
        window = MainWindow(initialize_analysis_view=False)
    window.settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.IniFormat)
    window.settings.setValue("behavior/autosave_project", False)
    window.project_data = project
    window.project_dir = tmp_path / "project"
    window.project_dir.mkdir()
    window.show_error = Mock()
    window.clustering_controller.refresh_samples()
    yield window
    window.clustering_controller.shutdown()
    window.project_state_manager._autosave_timer.stop()
    window.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def wait_until(predicate):
    deadline = monotonic() + 5
    while not predicate() and monotonic() < deadline:
        QtWidgets.QApplication.processEvents()
        QtTest.QTest.qWait(10)
    assert predicate()


def test_jobs_follow_enabled_channels_and_keep_unique_keys_despite_duplicate_names(project):
    sample = next(iter(project.samples.values()))
    project.skip_sample_channel(sample.sample_id, "Zn")
    sample.channels["P"].name = sample.channels["Fe"].name = "Same name"
    job = clustering_job(project, sample)
    assert set(job.keys) == {"P", "Fe"}
    assert len(job.refs) == 2
    method = CLUSTERING_METHODS[0]
    arrays = [project.sources[ref.source_id].load_array(ref) for ref in job.refs]
    result = method.compute(arrays, job, ClusteringParameters(2, 2), lambda message: None)
    assert set(result.elements) == {"P", "Fe"}


def test_batch_publishes_each_completed_sample_and_continues_after_a_failure(project, tmp_path):
    queue = jobs(project)
    real_method = CLUSTERING_METHODS[0]
    started, completed, failures = [], [], []
    worker = ClusteringBatchWorker(
        queue, project.sources, real_method.method_id, ClusteringParameters(2, 2), tmp_path
    )

    def compute(arrays, job, parameters, callback, *, progress=None):
        if job is queue[1]:
            raise ValueError("broken input")
        return real_method.compute(arrays, job, parameters, callback, progress=progress)

    progress = []
    worker.work_progress.connect(lambda done, total, text: progress.append((done, total, text)))
    worker.sample_started.connect(lambda index, job: started.append(job.sample_id))
    worker.sample_finished.connect(lambda result: completed.append((result, len(started))))
    worker.sample_failed.connect(lambda job, error: failures.append((job.sample_id, error)))
    with patch(
        "exhale.analysis.clusteringbatch.clustering_method",
        return_value=SimpleNamespace(compute=compute),
    ):
        worker.execute()
    assert [result.sample_id for result, _count in completed] == [
        queue[0].sample_id,
        queue[2].sample_id,
    ]
    assert [count for _result, count in completed] == [1, 3]
    assert failures == [(queue[1].sample_id, "broken input")]
    done = [entry[0] for entry in progress]
    total = sum(len(job.refs) + 1 for job in queue)
    assert done == sorted(done)
    assert done[0] == 0 and done[-1] == total
    assert all(entry[1] == total for entry in progress)
    assert any(0 < value < total for value in done)
    assert all(
        (tmp_path / clustering_relative_path(result.sample_id)).is_file()
        for result, _count in completed
    )


def test_cancel_after_one_sample_keeps_it_and_does_not_start_the_next(project, tmp_path):
    queue = jobs(project)
    worker = ClusteringBatchWorker(
        queue, project.sources, DEFAULT_CLUSTERING_METHOD, ClusteringParameters(2, 2), tmp_path
    )
    completed = []

    def ready(result):
        completed.append(result.sample_id)
        worker.abort()

    worker.sample_finished.connect(ready)
    with pytest.raises(InterruptedError):
        worker.execute()
    assert completed == [queue[0].sample_id]
    assert not (tmp_path / clustering_relative_path(queue[1].sample_id)).exists()


def test_results_replace_only_their_sample_and_method_and_roundtrip(project, tmp_path):
    job = jobs(project)[0]
    method = CLUSTERING_METHODS[0]
    parameters = ClusteringParameters(2, 2)
    arrays = [project.sources[ref.source_id].load_array(ref) for ref in job.refs]
    output = method.compute(arrays, job, parameters, lambda message: None)
    first = ClusteringResult(job.sample_id, job.refs, parameters, output)
    alternate = replace(first, method_id="other-method")
    project.set_clustering_result(first)
    project.set_clustering_result(alternate)
    replacement = replace(first, parameters=ClusteringParameters(3, 3))
    project.set_clustering_result(replacement)
    assert project.clustering_result(job.sample_id) is replacement
    assert project.clustering_result(job.sample_id, "other-method") is alternate
    project.clustering_method = "other-method"
    for result in (replacement, alternate):
        save_xrf_sample(
            output,
            tmp_path / clustering_relative_path(job.sample_id, result.method_id),
            method_id=result.method_id,
        )
    save_project(project, tmp_path / "project.xhp")
    restored = ProjectData()
    try:
        assert not load_project(restored, tmp_path / "project.xhp")
        assert restored.clustering_method == "other-method"
        assert set(restored.clustering_results[job.sample_id]) == {
            DEFAULT_CLUSTERING_METHOD,
            "other-method",
        }
        assert (
            restored.clustering_result(job.sample_id, DEFAULT_CLUSTERING_METHOD).parameters.min_k
            == 3
        )
    finally:
        restored.clear()


def test_select_unclustered_uses_current_method_and_all_means_all(project):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    job = jobs(project)[0]
    project.set_clustering_result(
        ClusteringResult(
            job.sample_id, job.refs, ClusteringParameters(), None, method_id="other-method"
        )
    )
    dialog = ClusteringBatchDialog(project, CLUSTERING_METHODS[0], job.sample_id)
    assert [entry.sample_id for entry in dialog.jobs()] == [job.sample_id]
    dialog.selectNew.click()
    assert len(dialog.jobs()) == 3
    project.set_clustering_result(
        ClusteringResult(job.sample_id, job.refs, ClusteringParameters(), None)
    )
    dialog.close()
    dialog = ClusteringBatchDialog(project, CLUSTERING_METHODS[0], job.sample_id)
    assert len(dialog.jobs()) == 1
    assert dialog.selectionInfo.text() == "1 sample selected"
    dialog.selectAll.click()
    assert len(dialog.jobs()) == 3
    dialog.selectNew.click()
    assert len(dialog.jobs()) == 2
    assert job.sample_id not in {entry.sample_id for entry in dialog.jobs()}
    assert dialog.selectionInfo.text() == "2 samples selected"
    assert all("skipped" not in dialog.sampleTree.topLevelItem(i).text(2) for i in range(3))
    dialog.selectNone.click()
    assert not dialog.jobs() and dialog.selectionInfo.text() == "0 samples selected"
    dialog.close()
    app.processEvents()


def test_saved_single_method_result_can_be_resaved_without_moving_its_sidecar(project, tmp_path):
    job = jobs(project)[0]
    parameters = ClusteringParameters(2, 2)
    arrays = [project.sources[ref.source_id].load_array(ref) for ref in job.refs]
    output = CLUSTERING_METHODS[0].compute(arrays, job, parameters, lambda message: None)
    relative = f"element-clusters/{job.sample_id}.h5"
    save_xrf_sample(output, tmp_path / relative, method_id="element-clusters")
    project.set_clustering_result(ClusteringResult(job.sample_id, job.refs, parameters, output))
    state = projectio.export_project_state(project, tmp_path)
    state["clustering_results"][0].pop("method_id")
    state["clustering_results"][0]["sidecar"] = relative
    path = tmp_path / "project.xhp"
    projectio.save_project_state(state, path)
    restored = ProjectData()
    try:
        assert not load_project(restored, path)
        save_project(restored, path)
        again = ProjectData()
        try:
            assert not load_project(again, path)
            assert again.clustering_result(job.sample_id).sidecar == relative
        finally:
            again.clear()
    finally:
        restored.clear()


def test_gui_publishes_finished_jobs_without_stealing_selection_and_stop_keeps_them(window):
    project = window.project_data
    queue = jobs(project)
    selected = queue[-1].sample_id
    window.clusteringSampleComboBox.setCurrentIndex(
        window.clusteringSampleComboBox.findData(selected)
    )
    owner = window.clustering_controller
    second_started = Event()
    real_method = CLUSTERING_METHODS[0]

    def compute(arrays, job, parameters, callback, *, progress=None):
        if job is queue[0]:
            return real_method.compute(arrays, job, parameters, callback, progress=progress)
        second_started.set()
        while True:
            callback("Waiting for cancellation")
            sleep(0.01)

    with patch(
        "exhale.analysis.clusteringbatch.clustering_method",
        return_value=SimpleNamespace(compute=compute),
    ):
        owner.start(queue)
        wait_until(
            lambda: (
                second_started.is_set()
                and project.clustering_result(queue[0].sample_id) is not None
            )
        )
        assert window.clusteringSampleComboBox.currentData() == selected
        assert window.clusteringSampleComboBox.isEnabled()
        assert not window.clusteringMethodCombo.isEnabled()
        owner.abort()
        wait_until(lambda: owner.worker is None)
    assert set(project.clustering_results) == {queue[0].sample_id}
    window.show_error.assert_not_called()


def test_clearing_project_rejects_already_queued_completion(window):
    owner = window.clustering_controller
    owner.dialog.clusterMinK.setValue(2)
    owner.dialog.clusterMaxK.setValue(2)
    owner.start(jobs(window.project_data)[:1])
    assert owner.thread.wait(5000)
    assert not window.project_data.clustering_results
    window.clear_project()
    QtWidgets.QApplication.processEvents()
    assert owner.worker is None and not window.project_data.clustering_results
    window.show_error.assert_not_called()


def test_viewer_colors_and_opacity_follow_element_switches(window):
    from napari.components import ViewerModel

    from exhale.analysis.naparihelper import NapariHelper

    queue = jobs(window.project_data)
    job = queue[0]
    parameters = ClusteringParameters(2, 2)
    arrays = [window.project_data.sources[ref.source_id].load_array(ref) for ref in job.refs]
    output = CLUSTERING_METHODS[0].compute(arrays, job, parameters, lambda message: None)
    window.project_data.set_clustering_result(
        ClusteringResult(job.sample_id, job.refs, parameters, output)
    )
    helper = NapariHelper.__new__(NapariHelper)
    helper.viewer = ViewerModel()
    helper._image_colors = WeakKeyDictionary()
    helper._label_presentations = WeakKeyDictionary()
    helper._label_color_rng = np.random.default_rng(0)
    helper.info_widget = Mock()
    owner = window.clustering_controller
    owner.naparihelper = helper
    window.tabWidget.setCurrentWidget(window.clusteringTab)
    np.testing.assert_allclose(helper.image_color(owner.map_color_editor.layer), (0, 1, 0, 1))
    mode, color = helper.label_display_mode(owner.color_editor.layer)
    assert mode == helper.LABEL_CATEGORICAL
    np.testing.assert_allclose(color, (1, 0, 0, 1))
    assert not window.clusteringBlending.isChecked()
    window.clusteringBlending.click()
    assert helper.layer_blending(owner.color_editor.layer) == helper.BLENDING_ADD
    helper.set_image_color(owner.map_color_editor.layer, (0, 1, 0, 1))
    helper.set_label_presentation(
        owner.color_editor.layer, helper.LABEL_MONOCHROME, (0, 0, 1, 1), 0
    )
    window.clusteringOpacity.setValue(40)
    owner._presentation_changed()
    window.clusteringElementCombo.setCurrentIndex(1)
    np.testing.assert_allclose(helper.image_color(owner.map_color_editor.layer), (0, 1, 0, 1))
    np.testing.assert_allclose(helper.label_display_mode(owner.color_editor.layer)[1], (0, 0, 1, 1))
    assert window.clusteringOpacity.value() == 40
    assert window.clusteringBlending.isChecked()
    assert helper.layer_blending(owner.color_editor.layer) == helper.BLENDING_ADD
    window.clusteringBlending.click()
    assert helper.layer_blending(owner.color_editor.layer) == helper.BLENDING_NORMAL
    saved = window.project_data.clustering_result(job.sample_id).layer_settings
    assert set(saved.layers) == {"element_map", "element_clusters"}
