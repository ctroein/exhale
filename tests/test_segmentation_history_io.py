"""Immutable candidate sidecars, atomic publication and save/recovery isolation."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import h5py
import numpy as np
import pytest

from exhale.analysis.segmentationio import (
    candidate_relative_path,
    publish_segmentation,
    save_candidate,
    save_segmentation,
)
from exhale.data.projectdata import LayerPresentation, ProjectData, SegmentationResult
from exhale.data.segmentation import SegmentationOutput, SegmentationParameters
from exhale.data.segmentationediting import SegmentationEditSession
from exhale.data.segmentationhistory import SegmentationCandidate
from exhale.data.source_refs import open_source
from exhale.project import projectio
from exhale.project.projectstatemanager import ProjectStateManager


@pytest.fixture
def project(tmp_path):
    source = tmp_path / "maps.h5"
    with h5py.File(source, "w") as f:
        f.attrs["default"] = "entry"
        f.create_dataset("entry/plotselect/P", data=np.ones((4, 12)))
    model = ProjectData()
    model.register_source(open_source(str(source)))
    yield model
    for opened in model.sources.values():
        opened.close()


def result(project, count=1, method="stardist", identity=42):
    sample = next(iter(project.samples.values()))
    labels = np.zeros((4, 12), dtype=np.uint32)
    labels.flat[:count] = identity
    return SegmentationResult(
        sample.sample_id,
        method,
        sample.channels["P"].ref,
        SegmentationParameters(),
        SegmentationOutput(labels, method, "v1"),
    )


def read(path):
    project = ProjectData()
    issues = projectio.load_project(project, path)
    for opened in project.sources.values():
        opened.close()
    return project, issues


def sidecar(candidate, root):
    return root / candidate_relative_path(
        candidate.sample_id, candidate.candidate_id, candidate.revision_id
    )


def test_rerun_and_autosave_preserve_saved_snapshot_and_recovery(project, tmp_path):
    first = publish_segmentation(project, result(project), tmp_path)
    saved = tmp_path / "project.xhp"
    projectio.save_project(project, saved)
    saved_bytes = saved.read_bytes()
    snapshot = sidecar(first, tmp_path)
    snapshot_bytes = snapshot.read_bytes()
    stamp = snapshot.stat().st_mtime_ns
    second = publish_segmentation(project, result(project, 2), tmp_path)
    autosave = tmp_path / "project.autosave.xhp"
    fake_manager = SimpleNamespace(
        window=SimpleNamespace(project_data=project, project_dir=tmp_path),
        autosave_path=lambda: autosave,
    )
    ProjectStateManager.write_autosave(fake_manager)
    assert saved.read_bytes() == saved_bytes
    assert snapshot.read_bytes() == snapshot_bytes
    assert snapshot.stat().st_mtime_ns == stamp
    baseline, issues = read(saved)
    assert not issues
    assert baseline.segmentation_histories[first.sample_id].active_id == first.candidate_id
    recovered, issues = read(autosave)
    assert not issues
    history = recovered.segmentation_histories[first.sample_id]
    assert history.active_id == second.candidate_id
    assert history.recency == (first.candidate_id, second.candidate_id)
    assert len(history.candidates) == 2


def test_duplicate_run_saves_only_provenance_and_keeps_annotation_metadata(project, tmp_path):
    first = publish_segmentation(project, result(project), tmp_path)
    first.name = "Reviewed"
    first.name_is_custom = True
    first.keep = True
    first.compare = True
    first.comparison_presentation = LayerPresentation(
        False, 0.3, "translucent_no_depth", (1, 1, 0, 1), "mask", 0
    )
    first.set_reviewed(True)
    path = sidecar(first, tmp_path)
    stamp = path.stat().st_mtime_ns
    duplicate = publish_segmentation(
        project, result(project, method="cellpose", identity=999), tmp_path
    )
    assert duplicate is first
    assert len(list((tmp_path / "segmentation").rglob("*.h5"))) == 1
    projectio.save_project(project, tmp_path / "project.xhp")
    restored, issues = read(tmp_path / "project.xhp")
    assert not issues
    candidate = restored.segmentation_histories[first.sample_id].active
    assert (
        candidate.candidate_id == first.candidate_id and candidate.revision_id == first.revision_id
    )
    assert candidate.name == "Reviewed" and candidate.keep and candidate.reviewed
    assert candidate.name_is_custom and candidate.compare
    assert candidate.comparison_presentation == first.comparison_presentation
    assert [run.method_id for run in candidate.provenance] == ["stardist", "cellpose"]
    assert path.stat().st_mtime_ns == stamp
    with patch(
        "exhale.analysis.segmentationio._atomic_hdf5", side_effect=AssertionError("rewrite")
    ):
        projectio.save_project(restored, tmp_path / "project.xhp")


def test_failed_snapshot_write_leaves_published_history_unchanged(project, tmp_path):
    first = publish_segmentation(project, result(project), tmp_path)
    history = project.segmentation_histories[first.sample_id]
    with patch("exhale.analysis.segmentationio.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            publish_segmentation(project, result(project, 2), tmp_path)
    assert tuple(history.candidates) == (first.candidate_id,)
    assert history.active is first
    assert not list(tmp_path.rglob("*.tmp"))


def test_existing_revision_cannot_be_overwritten_with_different_labels(project, tmp_path):
    first = publish_segmentation(project, result(project), tmp_path)
    conflict = replace(first, result=result(project, 2))
    before = sidecar(first, tmp_path).read_bytes()
    with pytest.raises(ValueError):
        save_candidate(conflict, tmp_path)
    assert sidecar(first, tmp_path).read_bytes() == before


def test_pruning_does_not_delete_files_referenced_by_previous_save(project, tmp_path):
    first = publish_segmentation(project, result(project), tmp_path)
    projectio.save_project(project, tmp_path / "project.xhp")
    history = project.segmentation_histories[first.sample_id]
    history.recent_limit = 2
    for count in range(2, 6):
        publish_segmentation(project, result(project, count), tmp_path)
    assert first.candidate_id not in history.candidates
    assert sidecar(first, tmp_path).is_file()
    restored, issues = read(tmp_path / "project.xhp")
    assert not issues
    assert restored.segmentation_histories[first.sample_id].active_id == first.candidate_id


def test_child_parent_and_review_survive_out_of_order_metadata(project, tmp_path):
    parent = publish_segmentation(project, result(project), tmp_path)
    child = SegmentationCandidate.from_result(result(project, 2))
    child.parent_id = parent.candidate_id
    child.edited = True
    child.set_reviewed(True)
    project.segmentation_histories[parent.sample_id].add_candidate(child)
    projectio.save_project(project, tmp_path / "project.xhp")
    state = json.loads((tmp_path / "project.xhp").read_text())
    state["segmentation_histories"][0]["candidates"].reverse()
    projectio.save_project_state(state, tmp_path / "project.xhp")
    restored, issues = read(tmp_path / "project.xhp")
    assert not issues
    active = restored.segmentation_histories[parent.sample_id].active
    assert active.candidate_id == child.candidate_id
    assert active.parent_id == parent.candidate_id and active.edited and active.reviewed


def test_missing_candidate_does_not_prevent_other_results_loading(project, tmp_path):
    first = publish_segmentation(project, result(project), tmp_path)
    second = publish_segmentation(project, result(project, 2), tmp_path)
    projectio.save_project(project, tmp_path / "project.xhp")
    sidecar(second, tmp_path).unlink()
    restored, issues = read(tmp_path / "project.xhp")
    assert issues
    history = restored.segmentation_histories[first.sample_id]
    assert history.active_id == first.candidate_id


def test_modified_snapshot_is_reported_without_losing_other_masks(project, tmp_path):
    first = publish_segmentation(project, result(project), tmp_path)
    second = publish_segmentation(project, result(project, 2), tmp_path)
    projectio.save_project(project, tmp_path / "project.xhp")
    with h5py.File(sidecar(second, tmp_path), "r+") as f:
        f["labels"][0, 0] = 7
    restored, issues = read(tmp_path / "project.xhp")
    assert any("contents" in issue for issue in issues)
    assert restored.segmentation_histories[first.sample_id].active_id == first.candidate_id


def test_failed_json_write_preserves_saved_metadata_and_referenced_arrays(project, tmp_path):
    first = publish_segmentation(project, result(project), tmp_path)
    saved = tmp_path / "project.xhp"
    projectio.save_project(project, saved)
    before = saved.read_bytes()
    snapshot = sidecar(first, tmp_path).read_bytes()
    publish_segmentation(project, result(project, 2), tmp_path)
    with patch("exhale.project.projectio.save_project_state", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            projectio.save_project(project, saved)
    assert saved.read_bytes() == before
    assert sidecar(first, tmp_path).read_bytes() == snapshot


def test_unfinished_edit_autosave_recovers_without_mutating_saved_candidate(project, tmp_path):
    parent = publish_segmentation(project, result(project), tmp_path)
    saved = tmp_path / "project.xhp"
    projectio.save_project(project, saved)
    before = saved.read_bytes()
    session = SegmentationEditSession(parent)
    project.segmentation_edit_sessions[parent.sample_id] = session
    assert projectio.export_project_state(project, tmp_path)["segmentation_drafts"] == []
    edited = session.labels.copy()
    edited[1, 1] = 777
    session.apply_labels(edited)
    autosave = tmp_path / "project.autosave.xhp"
    manager = SimpleNamespace(
        window=SimpleNamespace(project_data=project, project_dir=tmp_path),
        autosave_path=lambda: autosave,
    )
    ProjectStateManager.write_autosave(manager)
    draft = session.snapshot()
    snapshot = sidecar(draft, tmp_path)
    stamp = snapshot.stat().st_mtime_ns
    ProjectStateManager.write_autosave(manager)
    assert snapshot.stat().st_mtime_ns == stamp
    assert saved.read_bytes() == before
    restored, issues = read(autosave)
    assert not issues
    recovered = restored.segmentation_edit_sessions[parent.sample_id]
    np.testing.assert_array_equal(recovered.labels, edited)
    assert recovered.changed and not recovered.can_undo
    assert recovered.candidate_id == draft.candidate_id
    assert not recovered.source.edited
    baseline, issues = read(saved)
    assert not issues and not baseline.segmentation_edit_sessions
    assert baseline.segmentation_histories[parent.sample_id].active.result.output.labels[1, 1] == 0


def test_existing_method_result_loads_without_rewriting_its_sidecar(project, tmp_path):
    original = result(project)
    path = tmp_path / "old-mask.h5"
    save_segmentation(original.output, path, method_id=original.method_id)
    stamp = path.stat().st_mtime_ns
    state = projectio.export_project_state(project, tmp_path)
    state.pop("segmentation_histories")
    state["segmentation_results"] = [
        {
            "sample_id": original.sample_id,
            "method_id": original.method_id,
            "input_ref": original.input_ref.to_json(),
            "sidecar": path.name,
        }
    ]
    projectio.save_project_state(state, tmp_path / "project.xhp")
    restored, issues = read(tmp_path / "project.xhp")
    assert not issues
    history = restored.segmentation_histories[original.sample_id]
    assert len(history.candidates) == 1
    assert path.stat().st_mtime_ns == stamp


def test_unresolved_disconnection_survives_draft_save_and_recovery(project, tmp_path):
    parent = publish_segmentation(project, result(project, count=36), tmp_path)
    session = SegmentationEditSession(parent)
    project.segmentation_edit_sessions[parent.sample_id] = session
    session.select(42)
    session.edit("remove", [(0, 5), (3, 5)], size=3, disconnected="ask")
    assert session.pending_disconnections == {42}
    saved = tmp_path / "project.xhp"
    projectio.save_project(project, saved)
    recovered, issues = read(saved)
    assert not issues
    working = recovered.segmentation_edit_sessions[parent.sample_id]
    assert working.pending_disconnections == {42}
    np.testing.assert_array_equal(working.labels, session.labels)
    working.resolve_disconnection(42, split=True)
    assert not working.pending_disconnections
    assert len(working.areas[0]) == 2
    assert len(recovered.segmentation_histories[parent.sample_id].candidates) == 1


def test_removed_parent_files_remain_usable_by_previous_json_and_child_stays_independent(
    project, tmp_path
):
    parent = publish_segmentation(project, result(project), tmp_path)
    child = SegmentationCandidate.from_result(result(project, 2))
    child.parent_id = parent.candidate_id
    child.edited = True
    history = project.segmentation_histories[parent.sample_id]
    history.add_candidate(child)
    saved = tmp_path / "project.xhp"
    projectio.save_project(project, saved)
    previous = tmp_path / "previous.xhp"
    previous.write_bytes(saved.read_bytes())
    parent_stamp = sidecar(parent, tmp_path).stat().st_mtime_ns
    child_stamp = sidecar(child, tmp_path).stat().st_mtime_ns
    history.remove(parent.candidate_id)
    projectio.save_project(project, saved)
    assert sidecar(parent, tmp_path).stat().st_mtime_ns == parent_stamp
    assert sidecar(child, tmp_path).stat().st_mtime_ns == child_stamp
    loaded, issues = read(saved)
    assert not issues
    retained = loaded.segmentation_histories[parent.sample_id]
    assert len(retained.candidates) == 1 and retained.active.parent_id is None
    assert retained.active.edited and retained.active.provenance == child.provenance
    old, issues = read(previous)
    assert not issues and len(old.segmentation_histories[parent.sample_id].candidates) == 2


def test_review_choice_roundtrips_without_rewriting_label_snapshots(project, tmp_path):
    first = publish_segmentation(project, result(project), tmp_path)
    second = publish_segmentation(project, result(project, 2), tmp_path)
    history = project.segmentation_histories[first.sample_id]
    history.set_reviewed(first.candidate_id)
    saved = tmp_path / "project.xhp"
    projectio.save_project(project, saved)
    stamps = {
        candidate.candidate_id: sidecar(candidate, tmp_path).stat().st_mtime_ns
        for candidate in (first, second)
    }
    loaded, issues = read(saved)
    assert not issues
    restored = loaded.segmentation_histories[first.sample_id]
    assert restored.reviewed.candidate_id == first.candidate_id
    assert restored.active_id == second.candidate_id
    history.set_reviewed(second.candidate_id)
    projectio.save_project(project, saved)
    for candidate in (first, second):
        assert sidecar(candidate, tmp_path).stat().st_mtime_ns == stamps[candidate.candidate_id]
    loaded, issues = read(saved)
    assert not issues
    restored = loaded.segmentation_histories[first.sample_id]
    assert restored.reviewed.candidate_id == second.candidate_id
    assert not restored.candidates[first.candidate_id].reviewed


def test_downstream_reference_survives_project_reload_and_resolves_original_processing(
    project, tmp_path
):
    from exhale.data.segmentation import SegmentationPostprocessing
    from exhale.data.segmentationref import SegmentationReference

    candidate = project.add_segmentation_candidate(result(project, 3))
    candidate.result.postprocessing = SegmentationPostprocessing(minimum_area=2, expansion=1)
    reference = project.segmentation_reference(candidate.sample_id)
    expected = project.resolve_segmentation_reference(reference).copy()
    # A future consumer stores this JSON alongside its own output, not mask arrays.
    saved_reference = json.loads(json.dumps(reference.to_json()))
    candidate.result.postprocessing = SegmentationPostprocessing(minimum_area=999)
    filename = tmp_path / "project.xhp"
    projectio.save_project(project, filename)
    restored, issues = read(filename)
    assert not issues
    reference = SegmentationReference.from_json(saved_reference)
    before = projectio.export_project_state(restored, tmp_path)
    assert not restored.segmentation_reference_is_current(reference, candidate.candidate_id)
    np.testing.assert_array_equal(restored.resolve_segmentation_reference(reference), expected)
    assert projectio.export_project_state(restored, tmp_path) == before
