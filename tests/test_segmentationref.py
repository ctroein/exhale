"""Exact downstream mask inputs, stable resolution and explicit outdated checks."""

import json
from dataclasses import FrozenInstanceError, replace

import numpy as np
import pytest

from exhale.data.projectdata import ProjectData, SegmentationResult
from exhale.data.segmentation import (
    SegmentationOutput,
    SegmentationParameters,
    SegmentationPostprocessing,
)
from exhale.data.segmentationediting import SegmentationEditSession
from exhale.data.segmentationhistory import SegmentationCandidate
from exhale.data.segmentationref import SegmentationReference
from exhale.data.source_refs import ElementRef


@pytest.fixture
def project():
    model = ProjectData()
    model.create_sample("Sample", "sample")
    labels = np.zeros((7, 9), dtype=np.uint32)
    labels[1:5, 1:5] = 42
    labels[6, 8] = 7
    model.add_segmentation_candidate(
        SegmentationResult(
            "sample",
            "stardist",
            ElementRef("source", "/P"),
            SegmentationParameters(),
            SegmentationOutput(labels, "model", "1"),
        )
    )
    return model


def test_reference_is_an_immutable_json_roundtrip(project):
    candidate = project.segmentation_histories["sample"].active
    reference = project.segmentation_reference("sample")
    assert (reference.sample_id, reference.candidate_id, reference.revision_id) == (
        "sample",
        candidate.candidate_id,
        candidate.revision_id,
    )
    assert SegmentationReference.from_json(json.loads(json.dumps(reference.to_json()))) == reference
    assert hash(reference) == hash(SegmentationReference.from_candidate(candidate))
    with pytest.raises(FrozenInstanceError):
        reference.revision_id = "changed"
    with pytest.raises(FrozenInstanceError):
        reference.postprocessing.minimum_area = 50


def test_working_revision_replacement_retains_old_reference_ids_not_old_pixels(project):
    history = project.segmentation_histories["sample"]
    source = history.active
    source.edited = True
    old_reference = project.segmentation_reference("sample")
    old_json = old_reference.to_json()
    session = SegmentationEditSession(source)
    session.select(42)
    session.edit("remove", [(1, 1)], size=1)
    current = history.accept_edit(source.candidate_id, session.completed_candidate())
    assert current.candidate_id == source.candidate_id
    assert current.revision_id != source.revision_id
    assert len(history.candidates) == 1
    assert SegmentationReference.from_json(old_json) == old_reference
    assert not project.segmentation_reference_is_current(old_reference, current.candidate_id)
    with pytest.raises(ValueError, match="unavailable"):
        project.resolve_segmentation_reference(old_reference)
    assert project.segmentation_reference("sample").matches(current)


def test_processing_changes_mark_outdated_but_original_input_still_resolves(project):
    candidate = project.segmentation_histories["sample"].active
    candidate.result.postprocessing = SegmentationPostprocessing(minimum_area=3, expansion=1)
    reference = project.segmentation_reference("sample")
    original = project.resolve_segmentation_reference(reference).copy()
    candidate.result.postprocessing = SegmentationPostprocessing(minimum_area=999, expansion=-1)
    assert not project.segmentation_reference_is_current(reference, candidate.candidate_id)
    np.testing.assert_array_equal(project.resolve_segmentation_reference(reference), original)
    assert candidate.result.postprocessing == SegmentationPostprocessing(999, -1)
    assert not project.resolve_segmentation_reference(reference).flags.writeable
    candidate.result.postprocessing = reference.postprocessing
    assert project.segmentation_reference_is_current(reference, candidate.candidate_id)


def test_accepted_edits_are_outdated_for_the_new_input_without_replacing_results(project):
    history = project.segmentation_histories["sample"]
    source = history.active
    reference = project.segmentation_reference("sample")
    labels = project.resolve_segmentation_reference(reference).copy()
    session = SegmentationEditSession(source)
    session.select(42)
    session.edit("remove", [(1, 1)], size=1)
    assert project.segmentation_reference_is_current(reference, source.candidate_id)
    corrected = history.add_candidate(session.completed_candidate())
    assert not project.segmentation_reference_is_current(reference, corrected.candidate_id)
    np.testing.assert_array_equal(project.resolve_segmentation_reference(reference), labels)
    # The consumer explicitly decides which candidate is its input, not the viewer.
    assert project.segmentation_reference_is_current(reference, source.candidate_id)
    history.activate(source.candidate_id)
    assert not reference.matches(corrected)


def test_presentation_review_provenance_and_viewer_selection_do_not_change_input(project):
    history = project.segmentation_histories["sample"]
    source = history.active
    reference = project.segmentation_reference("sample")
    source.name = "Renamed"
    source.keep = True
    source.compare = True
    source.set_reviewed(True)
    source.result.layer_settings.order = ("nuclei_labels",)
    history.add_result(source.result)  # Equivalent run adds provenance, not a new identity.
    labels = source.result.output.labels.copy()
    labels[0, 0] = 42
    other = history.add_candidate(
        SegmentationCandidate.from_result(
            replace(
                source.result,
                output=SegmentationOutput(labels, "another-model", "2"),
            )
        )
    )
    assert history.active is other
    assert project.segmentation_reference_is_current(reference, source.candidate_id)
    assert reference.matches(source)


def test_removed_mask_or_sample_is_unavailable_without_fallback(project):
    history = project.segmentation_histories["sample"]
    original = history.active
    reference = project.segmentation_reference("sample")
    labels = original.result.output.labels.copy()
    labels[0, 0] = 42
    other = history.add_candidate(
        SegmentationCandidate.from_result(
            replace(
                original.result,
                output=SegmentationOutput(labels, "model", "2"),
            )
        )
    )
    history.remove(original.candidate_id)
    assert not project.segmentation_reference_is_current(reference, original.candidate_id)
    assert not project.segmentation_reference_is_current(reference, other.candidate_id)
    with pytest.raises(ValueError, match="unavailable"):
        project.resolve_segmentation_reference(reference)
    project.segmentation_histories.clear()
    assert not project.segmentation_reference_is_current(reference, original.candidate_id)
    with pytest.raises(ValueError, match="unavailable"):
        project.resolve_segmentation_reference(reference)


def test_exact_revision_is_required_even_if_candidate_id_matches(project):
    candidate = project.segmentation_histories["sample"].active
    reference = replace(project.segmentation_reference("sample"), revision_id="different")
    assert not reference.matches(candidate)
    with pytest.raises(ValueError, match="revision is unavailable"):
        project.resolve_segmentation_reference(reference)


@pytest.mark.parametrize("obj", [None, {}, [], {"sample_id": "sample"}])
def test_incomplete_saved_reference_is_not_silently_retargeted(obj):
    with pytest.raises(ValueError, match="Invalid segmentation reference"):
        SegmentationReference.from_json(obj)


def test_unavailable_capture_does_not_fall_back_to_another_candidate(project):
    with pytest.raises(ValueError, match="unavailable"):
        project.segmentation_reference("sample", "removed")
    with pytest.raises(ValueError, match="unavailable"):
        project.segmentation_reference("removed")
