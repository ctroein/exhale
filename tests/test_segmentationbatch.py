"""Batch scope, channel resolution, sequential cancellation and retained mask identity."""

from dataclasses import replace

import h5py
import numpy as np
import pytest
from qtpy import QtGui, QtWidgets

from exhale.analysis.analysisworker import AnalysisWorker
from exhale.analysis.segmentation_batch_dialog import SegmentationBatchDialog
from exhale.analysis.segmentationbatch import BatchSegmentationWorker
from exhale.analysis.segmentationio import publish_segmentation
from exhale.analysis.segmentationmethods import segmentation_method
from exhale.data.projectdata import ProjectData, SegmentationResult
from exhale.data.segmentation import SegmentationOutput, SegmentationParameters
from exhale.data.segmentationbatch import SegmentationBatchJob, suggested_batch_channel
from exhale.data.source_refs import open_source


@pytest.fixture
def project(tmp_path):
    model = ProjectData()
    for index in range(3):
        filename = tmp_path / f"sample{index}.h5"
        with h5py.File(filename, "w") as handle:
            handle.attrs["default"] = "entry"
            handle.create_dataset("entry/plotselect/P_K", data=np.full((8, 8), index + 1))
            handle.create_dataset("entry/plotselect/Fe_K", data=np.full((8, 8), index + 10))
        model.register_source(open_source(str(filename)))
    model.add_project_channel("P_K")
    model.add_project_channel("Fe_K")
    yield model
    for source in model.sources.values():
        source.close()


def jobs_for(project):
    return [
        SegmentationBatchJob(s.sample_id, s.name, s.channels["P_K"].ref)
        for s in project.samples.values()
    ]


def result_for(job, identity=42):
    labels = np.zeros((8, 8), np.uint32)
    labels[1:4, 1:4] = identity
    return SegmentationResult(
        job.sample_id,
        "stardist",
        job.input_ref,
        SegmentationParameters(),
        SegmentationOutput(labels, "model", "1"),
    )


def test_channel_suggestions_use_existing_or_p_without_materializing_data(project):
    sample = next(iter(project.samples.values()))
    assert suggested_batch_channel(project, sample, "stardist") == sample.channels["P_K"].ref
    chosen = sample.channels["Fe_K"].ref
    assert suggested_batch_channel(project, sample, "stardist", current_ref=chosen) == chosen
    project.add_segmentation_candidate(replace(result_for(jobs_for(project)[0]), input_ref=chosen))
    assert suggested_batch_channel(project, sample, "stardist") == chosen
    assert not sample.channels["P_K"].data_source.has_cache


def test_batch_dialog_skip_channel_edits_and_all_selection_are_stable(project):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    jobs = jobs_for(project)
    project.add_segmentation_candidate(result_for(jobs[0]))
    dialog = SegmentationBatchDialog(
        project, segmentation_method("stardist"), current_sample_id=jobs[0].sample_id
    )
    assert not dialog.jobs() and not dialog.startButton.isEnabled()
    names = [
        dialog.sampleTree.topLevelItem(i).text(0)
        for i in range(dialog.sampleTree.topLevelItemCount())
    ]
    dialog.selectAll.click()
    assert len(dialog.jobs()) == 2
    dialog.skipExisting.setChecked(False)
    assert len(dialog.jobs()) == 3
    item, combo, sample, _existing, _available = dialog._rows[1]
    combo.setCurrentIndex(combo.findData(sample.channels["Fe_K"].ref))
    assert (
        next(j for j in dialog.jobs() if j.sample_id == sample.sample_id).input_ref
        == sample.channels["Fe_K"].ref
    )
    combo.setCurrentIndex(0)
    assert not dialog.startButton.isEnabled()
    assert [dialog.sampleTree.topLevelItem(i).text(0) for i in range(3)] == names
    dialog.selectNone.click()
    assert not dialog.jobs()
    dialog.close()
    app.processEvents()


def test_worker_runs_sequentially_and_stop_keeps_only_finished_jobs(project, monkeypatch):
    jobs = jobs_for(project)
    seen = []

    def compute(worker):
        seen.append(int(worker.image[0, 0]))
        return result_for(jobs[0]).output

    monkeypatch.setattr(AnalysisWorker, "compute", compute)
    worker = BatchSegmentationWorker(jobs, project.sources, parameters=SegmentationParameters())
    completed = []
    worker.sample_finished.connect(
        lambda job, output: (completed.append(job.sample_id), worker.abort())
    )
    with pytest.raises(InterruptedError):
        worker.compute()
    assert seen == [1] and completed == [jobs[0].sample_id]
    assert worker.image.size == 0


def test_worker_continues_after_an_individual_failure(project, monkeypatch):
    jobs = jobs_for(project)
    seen, failures = [], []

    def compute(worker):
        value = int(worker.image[0, 0])
        seen.append(value)
        if value == 2:
            raise ValueError("Bad sample input")
        return result_for(jobs[0]).output

    monkeypatch.setattr(AnalysisWorker, "compute", compute)
    worker = BatchSegmentationWorker(jobs, project.sources)
    worker.sample_failed.connect(lambda job, error: failures.append((job.sample_id, error)))
    assert worker.compute() == [jobs[0].sample_id, jobs[2].sample_id]
    assert seen == [1, 2, 3] and failures == [(jobs[1].sample_id, "Bad sample input")]


def test_batch_publication_preserves_active_mask_and_its_working_edit(project, tmp_path):
    from exhale.data.segmentationediting import SegmentationEditSession

    job = jobs_for(project)[0]
    original = publish_segmentation(project, result_for(job), tmp_path)
    session = SegmentationEditSession(original)
    session.select(42)
    session.edit("remove", [(1, 1)], size=1)
    project.segmentation_edit_sessions[job.sample_id] = session
    before = session.labels.copy()
    new_labels = original.result.output.labels.copy()
    new_labels[5:7, 5:7] = 7
    incoming = replace(result_for(job), output=SegmentationOutput(new_labels, "model", "2"))
    added = publish_segmentation(project, incoming, tmp_path, activate=False)
    history = project.segmentation_histories[job.sample_id]
    assert history.active is original and added is not original
    assert project.segmentation_edit_sessions[job.sample_id] is session
    np.testing.assert_array_equal(session.labels, before)
    assert session.changed and len(history.candidates) == 2


def test_threaded_batch_publishes_incrementally_without_switching_the_view(
    project, tmp_path, monkeypatch
):
    import time
    from types import SimpleNamespace
    from unittest.mock import Mock

    from qtpy import QtCore

    from exhale.analysis.segmentationbatch import SegmentationBatchController
    from exhale.data.segmentationediting import SegmentationEditSession

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    jobs = jobs_for(project)
    original = publish_segmentation(project, result_for(jobs[0]), tmp_path)
    session = SegmentationEditSession(original)
    session.select(42)
    session.edit("remove", [(1, 1)], size=1)
    project.segmentation_edit_sessions[jobs[0].sample_id] = session

    class Window(QtWidgets.QWidget):
        segmentationResultsChanged = QtCore.Signal()

    class Owner(QtCore.QObject):
        pass

    window, owner = Window(), Owner()
    window.project_data, window.project_dir = project, tmp_path
    window.settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.IniFormat)
    window.analysisProgress, window.analysisBatchStatus = (
        QtWidgets.QProgressBar(),
        QtWidgets.QLabel(),
    )
    publication_threads = []
    window.project_state_manager = SimpleNamespace(
        project_changed=lambda: publication_threads.append(QtCore.QThread.currentThread())
    )
    owner.window, owner._edit_session = window, session
    owner.current_sample = lambda: project.samples[jobs[0].sample_id]
    owner.sample_changed = Mock()
    owner._refresh_masks = Mock()
    owner._append_status = Mock()
    owner._model_progress, owner._model_ready, owner.set_busy = Mock(), Mock(), Mock()
    calls = []

    def compute(worker):
        value = int(worker.image[0, 0])
        calls.append(value)
        time.sleep(0.03)
        labels = np.zeros((8, 8), np.uint32)
        labels[2:6, 2:6] = value
        return SegmentationOutput(labels, "model", "2")

    monkeypatch.setattr(AnalysisWorker, "compute", compute)
    batch = SegmentationBatchController(owner)
    batch.start(jobs, "stardist", SegmentationParameters(method_options={"prob_thresh": 0.5}))
    saw_incremental = False
    deadline = time.monotonic() + 5
    while batch.active and time.monotonic() < deadline:
        app.processEvents()
        if batch.completed and batch.active:
            saw_incremental = True
            assert project.segmentation_histories[jobs[0].sample_id].active is original
            assert owner._edit_session is session and session.changed
        time.sleep(0.003)
    assert not batch.active and batch.worker is None and batch.thread is None
    assert calls == [1, 2, 3] and len(batch.completed) == 3 and saw_incremental
    assert all(thread == app.thread() for thread in publication_threads)
    assert project.segmentation_histories[jobs[0].sample_id].active is original
    owner.sample_changed.assert_not_called()
    assert owner._edit_session is session and session.changed
    app.processEvents()
    window.close()


def test_threaded_batch_stop_discards_current_and_remaining_jobs(project, tmp_path, monkeypatch):
    import time
    from types import SimpleNamespace
    from unittest.mock import Mock

    from qtpy import QtCore

    from exhale.analysis.segmentationbatch import SegmentationBatchController

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    class Window(QtWidgets.QWidget):
        segmentationResultsChanged = QtCore.Signal()

    class Owner(QtCore.QObject):
        pass

    window, owner = Window(), Owner()
    window.project_data, window.project_dir = project, tmp_path
    window.settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.IniFormat)
    window.analysisProgress, window.analysisBatchStatus = (
        QtWidgets.QProgressBar(),
        QtWidgets.QLabel(),
    )
    window.project_state_manager = SimpleNamespace(project_changed=Mock())
    owner.window, owner._edit_session = window, None
    owner.current_sample = lambda: None
    owner._append_status, owner._model_progress, owner._model_ready, owner.set_busy = (
        Mock(),
        Mock(),
        Mock(),
        Mock(),
    )

    def compute(worker):
        for _ in range(8):
            time.sleep(0.005)
            worker.report("Working")
        return SegmentationOutput(np.ones((8, 8), np.uint32), "model", "1")

    monkeypatch.setattr(AnalysisWorker, "compute", compute)
    batch = SegmentationBatchController(owner)
    jobs = jobs_for(project)
    batch.start(jobs, "stardist", SegmentationParameters())
    stopped = False
    deadline = time.monotonic() + 5
    while batch.active and time.monotonic() < deadline:
        app.processEvents()
        if batch.completed and not stopped:
            batch.abort()
            stopped = True
        time.sleep(0.002)
    assert stopped and not batch.active
    assert batch.completed == [jobs[0].sample_id]
    assert set(project.segmentation_histories) == {jobs[0].sample_id}
    assert "Stopped" in window.analysisBatchStatus.text()
    app.processEvents()
    window.close()


def test_worker_stops_after_shared_model_failure_and_snapshots_parameters(project, monkeypatch):
    jobs = jobs_for(project)
    parameters = SegmentationParameters(method_options={"prob_thresh": 0.5})
    worker = BatchSegmentationWorker(jobs, project.sources, parameters=parameters)
    parameters.method_options["prob_thresh"] = 0.9
    attempted = []

    def compute(current):
        assert current.parameters.method_options["prob_thresh"] == 0.5
        attempted.append(int(current.image[0, 0]))
        current.model_error = "Cannot obtain model"
        raise ValueError(current.model_error)

    monkeypatch.setattr(AnalysisWorker, "compute", compute)
    assert worker.compute() == []
    assert attempted == [1]


@pytest.mark.parametrize("backwards", [False, True])
def test_incremental_mask_updates_keep_uncommitted_name_when_history_prunes(project, backwards):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from exhale.analysis.controller import AnalysisController
    from exhale.data.segmentationhistory import SegmentationHistory

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    job = jobs_for(project)[0]
    history = SegmentationHistory(job.sample_id, recent_limit=2)

    def candidate_at(start, name):
        labels = np.zeros((8, 8), np.uint32)
        labels[start : start + 2, start : start + 2] = 42
        candidate = history.add_result(
            replace(result_for(job), output=SegmentationOutput(labels, "model", "1"))
        )
        candidate.name = name
        return candidate

    candidate_at(1, "Old")
    active = candidate_at(3, "Active")
    combo = QtWidgets.QComboBox()
    editor = QtWidgets.QLineEdit()

    def refresh_icons():
        pixmap = QtGui.QPixmap(12, 12)
        pixmap.fill(QtGui.QColor("red"))
        combo.setItemIcon(combo.currentIndex(), QtGui.QIcon(pixmap))

    control = SimpleNamespace(
        window=SimpleNamespace(
            analysisMaskCombo=combo,
            analysisKeepMask=QtWidgets.QToolButton(),
            analysisRemoveMask=QtWidgets.QToolButton(),
            analysisRestoreMask=QtWidgets.QToolButton(),
            analysisCreateMask=QtWidgets.QToolButton(),
            analysisChNuclei=QtWidgets.QComboBox(),
        ),
        _mask_name_edit=editor,
        _history=lambda: history,
        _mask_name=AnalysisController._mask_name,
        current_candidate=lambda: history.active,
        refresh_mask_markers=refresh_icons,
        _refresh_comparison_choices=Mock(),
        _update_review_control=Mock(),
        worker=None,
        batch=SimpleNamespace(active=False),
        current_sample=lambda: project.samples[job.sample_id],
    )
    AnalysisController._refresh_masks(control)
    editor.setText("Typing a new name")
    editor.setModified(True)
    editor.setSelection(6, -4) if backwards else editor.setSelection(2, 4)
    candidate_at(5, "New")
    history.activate(active.candidate_id)
    AnalysisController._refresh_masks(control, incremental=True)
    assert combo.currentData() == active.candidate_id
    assert editor.text() == "Typing a new name" and editor.isModified()
    assert editor.selectionStart() == 2 and editor.selectedText() == "ping"
    assert editor.cursorPosition() == (2 if backwards else 6)
    combo.close()
    app.processEvents()
