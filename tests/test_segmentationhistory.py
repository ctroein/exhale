"""Candidate identity, partition deduplication, provenance and retention contracts."""

from dataclasses import replace

import numpy as np
import pytest

from exhale.data.projectdata import ProjectData, SegmentationResult
from exhale.data.segmentation import (
    SegmentationOutput,
    SegmentationParameters,
    SegmentationPostprocessing,
)
from exhale.data.segmentationhistory import (
    SegmentationCandidate,
    SegmentationHistory,
    partition_digest,
)
from exhale.data.source_refs import ElementRef


def result(index=1, *, method="stardist", sample="sample", labels=None):
    if labels is None:
        labels = np.zeros((4, 12), dtype=np.uint32)
        labels.flat[:index] = index
    return SegmentationResult(
        sample,
        method,
        ElementRef("data.h5", "/P"),
        SegmentationParameters(method_options={"nested": {"value": 1}}),
        SegmentationOutput(labels, "model-" + method, "version-1"),
    )


def test_duplicate_geometry_ignores_numeric_ids_and_preserves_background_and_grouping():
    original = np.array([[0, 42, 42], [2**32 - 1, 0, 2**32 - 1]], dtype=np.uint32)
    renamed = np.array([[0, 9, 9], [3, 0, 3]], dtype=np.uint32)
    assert partition_digest(original) == partition_digest(renamed)
    assert partition_digest(original) != partition_digest(np.array([[0, 9, 9], [3, 0, 4]]))
    assert partition_digest(original) != partition_digest(renamed.reshape(3, 2))
    assert partition_digest(original) != partition_digest(np.where(renamed == 0, 7, renamed))


def test_candidate_owns_labels_and_settings_and_run_parameters():
    source = result()
    _ = source.processed_labels
    candidate = SegmentationCandidate.from_result(source)
    source.output.labels[:] = 0
    source.parameters.method_options["nested"]["value"] = 99
    source.layer_settings.order = ("changed",)
    source.postprocessing = SegmentationPostprocessing(500)
    assert candidate.result.output.labels.flat[0] == 1
    assert not candidate.result.output.labels.flags.writeable
    assert candidate.result._processed_cache is None
    assert candidate.result.parameters.method_options["nested"]["value"] == 1
    assert candidate.provenance[0].parameters.method_options["nested"]["value"] == 1
    assert candidate.result.layer_settings.order == ()
    assert candidate.result.postprocessing.minimum_area == 0


def test_duplicate_runs_merge_across_methods_without_overwriting_annotation_state():
    history = SegmentationHistory("sample")
    first = history.add_result(result(labels=[[0, 42, 42], [7, 0, 7]]))
    first.name = "Reviewed correction"
    first.keep = True
    first.edited = True
    first.set_reviewed(True)
    first.result.postprocessing = SegmentationPostprocessing(20, expansion=2)
    other = result(method="cellpose", labels=[[0, 9, 9], [3, 0, 3]])
    other.input_ref = ElementRef("data.h5", "/Fe")
    duplicate = history.add_result(other)
    assert duplicate is first
    assert len(history.candidates) == 1
    assert history.active_id == first.candidate_id
    assert first.name == "Reviewed correction" and first.reviewed and first.edited and first.keep
    assert first.result.postprocessing == SegmentationPostprocessing(20, expansion=2)
    assert [run.method_id for run in first.provenance] == ["stardist", "cellpose"]
    assert first.provenance[-1].input_ref == other.input_ref
    assert first.provenance[-1].model_id == other.output.model_id
    history.add_candidate(first)
    assert len(first.provenance) == 2


def test_recent_limit_keeps_five_predictions_in_addition_to_protected_masks():
    history = SegmentationHistory("sample")
    retained = [history.add_result(result(index)) for index in range(1, 4)]
    retained[0].keep = True
    retained[1].edited = True
    retained[2].set_reviewed(True)
    incoming = [history.add_result(result(index)) for index in range(4, 12)]
    assert set(history.candidates) == {
        candidate.candidate_id for candidate in retained + incoming[-5:]
    }
    assert history.active is incoming[-1]


def test_selecting_old_mask_does_not_reorder_or_prune_it():
    history = SegmentationHistory("sample", recent_limit=2)
    first = history.add_result(result(1))
    second = history.add_result(result(2))
    before = tuple(history.candidates)
    history.activate(first.candidate_id)
    assert tuple(history.candidates) == before
    assert history.active is first
    assert not history.prune()
    with pytest.raises(KeyError):
        history.activate("missing")
    assert history.active is first
    assert second.candidate_id in history.candidates


def test_duplicate_new_run_updates_retention_recency_without_reordering_candidates():
    history = SegmentationHistory("sample", recent_limit=2)
    first = history.add_result(result(1))
    second = history.add_result(result(2))
    before = tuple(history.candidates)
    assert history.add_result(result(1, method="cellpose")) is first
    assert tuple(history.candidates) == before
    third = history.add_result(result(3))
    assert set(history.candidates) == {first.candidate_id, third.candidate_id}
    assert second.candidate_id not in history.candidates


def test_retained_correction_keeps_its_parent_and_does_not_inherit_review():
    history = SegmentationHistory("sample", recent_limit=1)
    parent = history.add_result(result(1))
    parent.set_reviewed(True)
    child = SegmentationCandidate.from_result(result(2))
    child.parent_id = parent.candidate_id
    child.edited = True
    child.reviewed_revision = parent.revision_id
    assert not child.reviewed
    history.add_candidate(child)
    parent.set_reviewed(False)
    history.add_result(result(3))
    assert parent.candidate_id in history.candidates
    assert child.candidate_id in history.candidates
    child.set_reviewed(True)
    child.result.postprocessing = SegmentationPostprocessing(50)
    assert child.reviewed


def test_cross_sample_or_invalid_identity_does_not_mutate_history():
    history = SegmentationHistory("sample")
    candidate = history.add_result(result())
    for invalid in (result(sample="other"),):
        with pytest.raises(ValueError):
            history.add_result(invalid)
    conflicting = replace(candidate, result=result(2))
    with pytest.raises(ValueError):
        history.add_candidate(conflicting)
    missing_parent = SegmentationCandidate.from_result(result(3))
    missing_parent.parent_id = "missing"
    with pytest.raises(ValueError):
        history.add_candidate(missing_parent)
    assert tuple(history.candidates) == (candidate.candidate_id,)
    assert history.active is candidate


def test_conflicting_id_cannot_merge_into_a_different_existing_candidate():
    history = SegmentationHistory("sample")
    first = history.add_result(result(1))
    second = history.add_result(result(2))
    conflicting = replace(first, result=result(2))
    with pytest.raises(ValueError):
        history.add_candidate(conflicting)
    assert len(first.provenance) == len(second.provenance) == 1
    assert history.active is second


def test_blank_mask_is_not_a_foreground_mask_and_distinct_samples_are_independent():
    assert partition_digest(np.zeros((2, 2), dtype=int)) != partition_digest(
        np.ones((2, 2), dtype=int)
    )
    first = SegmentationHistory("sample")
    second = SegmentationHistory("other")
    a = first.add_result(result())
    b = second.add_result(result(sample="other"))
    assert a.candidate_id != b.candidate_id
    assert a.revision_id != b.revision_id


def test_invalid_history_limits_are_rejected():
    for limit in (0, -1, 1.5, True):
        with pytest.raises(ValueError):
            SegmentationHistory("sample", limit)


def test_compared_mask_is_retained_while_new_predictions_are_added():
    history = SegmentationHistory("sample", recent_limit=1)
    first = history.add_result(result(1))
    first.compare = True
    history.add_result(result(2))
    history.add_result(result(3))
    assert first.candidate_id in history.candidates
    first.compare = False
    history.add_result(result(4))
    assert first.candidate_id not in history.candidates


def test_existing_result_import_skips_independent_invalid_entries():
    malformed = result(3)
    malformed.output.labels.resize((2, 2, 12), refcheck=False)
    history, issues = SegmentationHistory.from_results(
        "sample", [result(1), object(), malformed, result(2, method="cellpose")]
    )
    assert len(issues) == 2
    assert len(history.candidates) == 2
    assert {candidate.provenance[0].method_id for candidate in history.candidates.values()} == {
        "stardist",
        "cellpose",
    }


def test_project_owns_imports_and_clears_candidate_histories():
    project = ProjectData()
    project.create_sample("Sample", "sample")
    first = result(1)
    project.set_segmentation_result(first)
    history = project.segmentation_histories["sample"]
    assert history.active.provenance[0].method_id == "stardist"
    second = project.add_segmentation_candidate(result(2, method="cellpose"))
    assert history.active is second
    assert len(history.candidates) == 2
    project.remove_sample("sample")
    assert not project.segmentation_histories
    project.create_sample("Again", "sample")
    project.add_segmentation_candidate(result())
    project.clear()
    assert not project.segmentation_histories


def test_deliberate_removal_keeps_descendants_provenance_and_order():
    history = SegmentationHistory("sample")
    parent = history.add_result(result(1))
    child = SegmentationCandidate.from_result(result(2))
    child.edited = True
    child.parent_id = parent.candidate_id
    history.add_candidate(child)
    other = history.add_result(result(3))
    history.activate(parent.candidate_id)
    provenance = child.provenance
    removed = history.remove(parent.candidate_id)
    assert removed is parent
    assert child.parent_id is None and child.provenance == provenance
    assert child.edited and child.protected
    assert tuple(history.candidates) == (child.candidate_id, other.candidate_id)
    assert history.active is other
    assert history.equivalent(parent) is None
    history.remove(other.candidate_id)
    assert history.active is child
    history.remove(child.candidate_id)
    assert not history.candidates and history.active is None and not history.recency


def test_removing_a_missing_candidate_does_not_mutate_history():
    history = SegmentationHistory("sample")
    candidate = history.add_result(result())
    with pytest.raises(KeyError):
        history.remove("missing")
    assert history.active is candidate and tuple(history.candidates) == (candidate.candidate_id,)


def test_restore_recovers_identity_children_presentation_and_order():
    from exhale.data.projectdata import LayerPresentation

    history = SegmentationHistory("sample")
    parent = history.add_result(result(1))
    parent.name = "My mask"
    parent.keep = True
    child = SegmentationCandidate.from_result(result(2))
    child.parent_id = parent.candidate_id
    child.edited = True
    history.add_candidate(child)
    comparison = f"comparison:{parent.candidate_id}"
    child.result.layer_settings.order = ("nuclei", comparison)
    child.result.layer_settings.layers[comparison] = LayerPresentation(True, 0.4, "normal")
    original_order = tuple(history.candidates)
    history.remove(parent.candidate_id)
    assert history.can_restore_removed and child.parent_id is None
    assert comparison not in child.result.layer_settings.layers
    assert history.restore_removed() is parent
    assert tuple(history.candidates) == original_order
    assert history.active is parent and parent.name == "My mask" and parent.keep
    assert child.parent_id == parent.candidate_id
    assert child.result.layer_settings.order == ("nuclei", comparison)
    assert child.result.layer_settings.layers[comparison].opacity == 0.4
    assert not history.can_restore_removed


def test_restore_is_lifo_and_preserves_a_newer_review_assignment():
    history = SegmentationHistory("sample")
    first = history.add_result(result(1))
    second = history.add_result(result(2))
    history.set_reviewed(first.candidate_id)
    history.remove(first.candidate_id)
    history.set_reviewed(second.candidate_id)
    history.remove(second.candidate_id)
    assert history.restore_removed() is second and history.reviewed is second
    assert history.restore_removed() is first and history.reviewed is second
    assert not first.reviewed and history.restore_removed() is None


def test_removed_masks_are_not_serialized():
    history = SegmentationHistory("sample")
    candidate = history.add_result(result(1))
    history.remove(candidate.candidate_id)
    restored, issues = SegmentationHistory.restore(
        history.sample_id,
        list(history.candidates.values()),
        active_id=history.active_id,
        recency=history.recency,
    )
    assert not issues and not restored.candidates and not restored.can_restore_removed


def test_review_transfer_is_exclusive_revision_bound_and_independent_of_active_mask():
    history = SegmentationHistory("sample")
    first = history.add_result(result(1))
    second = history.add_result(result(2))
    order = tuple(history.candidates)
    history.set_reviewed(first.candidate_id)
    assert history.reviewed is first and first.reviewed_revision == first.revision_id
    assert history.active is second
    history.set_reviewed(second.candidate_id)
    assert history.reviewed is second and not first.reviewed
    assert tuple(history.candidates) == order
    history.set_reviewed(second.candidate_id, False)
    assert history.reviewed is None
    with pytest.raises(KeyError):
        history.set_reviewed("missing")
    assert history.reviewed is None


def test_adding_a_reviewed_candidate_transfers_review_and_editing_does_not_inherit_it():
    history = SegmentationHistory("sample")
    first = history.add_result(result(1))
    history.set_reviewed(first.candidate_id)
    child = SegmentationCandidate.from_result(result(2))
    child.edited = True
    child.parent_id = first.candidate_id
    history.add_candidate(child)
    assert history.reviewed is first and not child.reviewed
    child.set_reviewed(True)
    history.add_candidate(child)
    assert history.reviewed is child and not first.reviewed
